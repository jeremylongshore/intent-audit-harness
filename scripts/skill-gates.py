#!/usr/bin/env python3
"""Read-only verifier for the opt-in skill-gates operational pilot (not a kernel contract)."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

POLICY = "audit-harness/skill-gates/v1"
RECEIPT = "audit-harness/skill-gate-receipt/v1"
LIMIT = 1024 * 1024
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("JSON input exceeds limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite(_value):
        raise ValueError("non-finite JSON number")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("overflowing JSON number")
        return parsed

    return json.loads(raw, object_pairs_hook=unique, parse_constant=finite, parse_float=number), digest(raw)


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError("unexpected or missing fields")


def strings(value, identifiers=False):
    if (not isinstance(value, list) or not 1 <= len(value) <= 256
            or any(not isinstance(v, str) or not v or len(v) > 4096 for v in value)
            or len(set(value)) != len(value)):
        raise ValueError("expected unique nonempty strings")
    if identifiers and any(not IDENTIFIER.fullmatch(v) for v in value):
        raise ValueError("invalid identifier")


def relative(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or Path(value).is_absolute() or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError("expected a normalized workspace-relative file")
    return value


def file_path(root, relative_path):
    path = root / relative(relative_path)
    if root not in path.resolve().parents or not path.is_file() or path.is_symlink():
        raise ValueError("input is missing, linked, or outside workspace")
    if path.stat().st_size > LIMIT:
        raise ValueError("input exceeds limit")
    return path


def policy_at(path):
    policy, policy_hash = load(path)
    exact(policy, "schema mode skill inputs must_read must_run checklist deny_tools")
    if policy["schema"] != POLICY or policy["mode"] not in ("observe", "enforce"):
        raise ValueError("unknown policy schema or mode")
    if not isinstance(policy["skill"], str) or not IDENTIFIER.fullmatch(policy["skill"]):
        raise ValueError("invalid skill")
    for field in ("inputs", "must_read", "checklist"):
        strings(policy[field], identifiers=field == "checklist")
    for path in policy["inputs"] + policy["must_read"]:
        relative(path)
    deny = policy["deny_tools"]
    if deny != []:
        strings(deny)
    commands = policy["must_run"]
    if not isinstance(commands, list) or not 1 <= len(commands) <= 32:
        raise ValueError("expected bounded commands")
    ids = []
    for command in commands:
        exact(command, "id argv timeout_ms min_tests")
        strings([command["id"]], identifiers=True)
        argv = command["argv"]
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 64
                or any(not isinstance(a, str) or not a or "\0" in a or len(a) > 4096 for a in argv)):
            raise ValueError("expected shell-free argv")
        for key, maximum in (("timeout_ms", 600000), ("min_tests", 1000000000)):
            v = command[key]
            if type(v) is not int or not 1 <= v <= maximum:
                raise ValueError("invalid command bound")
        ids.append(command["id"])
    strings(ids, identifiers=True)
    return policy, policy_hash


def identity(root, policy, policy_hash, collector):
    """Declare every source/config input; bind command executables and both implementations."""
    root = Path(root).resolve()
    paths = set(policy["inputs"] + policy["must_read"])
    tools = {}
    for command in policy["must_run"]:
        executable = resolve_executable(root, command["argv"][0])
        if executable is None:
            raise ValueError("command executable unavailable")
        executable = str(Path(executable).resolve())
        tools[command["id"]] = {"path": executable, "sha256": digest(Path(executable).read_bytes())}
        # Explicit files in argv are inputs too; directories/globs still require authored inventory.
        for arg in command["argv"][1:]:
            candidate = arg.split("=", 1)[1] if arg.startswith("-") and "=" in arg else arg
            path = root / candidate
            if not candidate.startswith("-") and path.is_file():
                if path.is_absolute():
                    try:
                        candidate = str(path.relative_to(root))
                    except ValueError as error:
                        raise ValueError("file argument outside workspace") from error
                paths.add(relative(candidate))
    return {
        "root": str(root), "policy_sha256": policy_hash,
        "inputs": {p: digest(file_path(root, p).read_bytes()) for p in sorted(paths)},
        "tools": tools, "verifier_sha256": digest(Path(__file__).read_bytes()),
        "collector_sha256": digest(Path(collector).read_bytes()),
        "python_sha256": digest(Path(sys.executable).read_bytes()), "python_version": sys.version,
    }


def resolve_executable(root, name):
    """Match execution's declared cwd, including relative/empty PATH entries."""
    if os.path.dirname(name):
        return shutil.which(str(root / name))
    entries = os.environ.get("PATH", os.defpath).split(os.pathsep)
    search = os.pathsep.join(str((root / entry).resolve()) for entry in entries)
    return shutil.which(name, path=search)


def assess(policy, receipt, current, session):
    """Missing, stale, failed, partial and zero-test observations cannot establish compliance."""
    errors = []
    expected = "schema session identity reads commands report"
    try:
        exact(receipt, expected)
    except ValueError:
        return ["receipt:invalid-shape"]
    if receipt["schema"] != RECEIPT or receipt["session"] != session:
        errors.append("receipt:session-or-schema")
    if receipt["identity"] != current:
        errors.append("receipt:stale-identity")
    binding = digest(canonical(current))
    reads = receipt["reads"]
    for path in policy["must_read"]:
        if not isinstance(reads, dict) or reads.get(path) != current["inputs"][path]:
            errors.append("read:" + path)
    commands = receipt["commands"]
    for required in policy["must_run"]:
        evidence = commands.get(required["id"]) if isinstance(commands, dict) else None
        valid = isinstance(evidence, dict)
        if valid:
            valid = (evidence.get("status") == "completed" and type(evidence.get("exit_code")) is int
                     and evidence["exit_code"] == 0 and type(evidence.get("tests_passed")) is int
                     and evidence["tests_passed"] >= required["min_tests"]
                     and type(evidence.get("tests_failed")) is int and evidence["tests_failed"] == 0
                     and evidence.get("identity_sha256") == binding
                     and isinstance(evidence.get("stdout_sha256"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", evidence["stdout_sha256"]) is not None)
        if not valid:
            errors.append("run:" + required["id"])
    report = receipt["report"]
    if (not isinstance(report, dict) or report.get("checklist") != policy["checklist"]
            or report.get("identity_sha256") != binding):
        errors.append("report:missing-or-stale")
    return errors


def row(policy_hash, receipt, errors, strict):
    report = receipt.get("report") if isinstance(receipt, dict) else None
    checklist = report.get("checklist") if isinstance(report, dict) else None
    result = {
        "gate_id": "audit-harness:local:skill-compliance",
        "result": ("FAIL" if strict else "ADVISORY") if errors else "PASS",
        "policy_hash": "sha256:" + policy_hash, "input_hash": "sha256:" + digest(canonical(receipt)),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runner": "audit-harness@" + json.loads((Path(__file__).parent.parent / "package.json").read_text())["version"],
        "commit_sha": "unknown",
        "metadata": {"validator": POLICY, "errors": errors[:256], "trusted_local_evidence": True,
                     "reported_checklist": checklist},
    }
    if errors and not strict:
        result["advisory_severity"] = "error"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("policy", "receipt", "root", "session", "collector"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    receipt = {}
    policy_hash = digest(b"")
    try:
        policy, policy_hash = policy_at(args.policy)
        receipt, _ = load(args.receipt)
        current = identity(args.root, policy, policy_hash, args.collector)
        errors = assess(policy, receipt, current, args.session)
    except (ValueError, OSError, TypeError, RecursionError):
        errors = ["evidence:unavailable-or-invalid"]
    result = row(policy_hash, receipt, errors, args.strict)
    print(json.dumps(result, sort_keys=True) if args.json else result["result"])
    return int(bool(errors) and args.strict)


if __name__ == "__main__":
    sys.exit(main())
