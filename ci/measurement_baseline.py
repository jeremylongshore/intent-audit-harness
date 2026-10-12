#!/usr/bin/env python3
"""Internal advisory Python baseline; never a public gate or threshold decision."""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import sys


INPUT_SCHEMA = "audit-harness-self-measurement-input/v1"
REPORT_SCHEMA = "audit-harness-self-measurement/v1"
PROXY = "file line coverage used as a function coverage proxy"
EXCLUDED_SCOPES = (
    ("bin/*.js", "Node dispatcher: unmeasured"),
    ("scripts/*.sh", "shell implementation: unmeasured"),
    ("python/src/intent_audit_harness/*.py", "Python package wrapper: unmeasured"),
    ("python/src/intent_audit_harness/scripts/*.py", "packaged canonical mirror: excluded"),
    ("rust/scripts/*.py", "packaged canonical mirror: excluded"),
    ("rust/src/*.rs", "Rust wrapper: unmeasured"),
    ("ci/*.py", "CI tooling: outside measured scopes"),
    ("ci/*.ts", "CI tooling: outside measured scopes"),
    ("ci/signing-reconciler/src/*.ts", "CI TypeScript: unmeasured"),
    ("tests/fixtures/**/*.py", "fixture: excluded"),
)


def _regular(root, path):
    return path.is_file() and not any(
        part.is_symlink() for part in (path, *path.parents) if part != root.parent
    ) and path.resolve().is_relative_to(root)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_inventory(root):
    root = Path(root).resolve()
    candidates = [(path, "production") for path in root.glob("scripts/*.py")]
    candidates += [(path, "test") for path in root.glob("tests/**/*.py")
                   if not path.relative_to(root).as_posix().startswith("tests/fixtures/")]
    return sorted([
        {"path": path.relative_to(root).as_posix(), "sha256": _digest(path), "kind": kind}
        for path, kind in candidates if _regular(root, path)
    ], key=lambda item: item["path"])


def _excluded_inventory(root):
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": _digest(path), "reason": reason}
        for pattern, reason in EXCLUDED_SCOPES for path in sorted(root.glob(pattern))
        if _regular(root, path)
    ]


def _definitions(path):
    tree = ast.parse(path.read_bytes(), filename=str(path))
    definitions = {}

    def visit(node, prefix=""):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = prefix + node.name
            if not isinstance(node, ast.ClassDef):
                definitions[(node.lineno, node.name)] = qualified
            prefix = qualified + "."
        for child in ast.iter_child_nodes(node):
            visit(child, prefix)

    visit(tree)
    return definitions


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _percentage(covered, total):
    return 100.0 * covered / total if total else None


def _provenance_errors(provenance, inventory):
    if not isinstance(provenance, dict):
        return ["provenance missing or malformed"]
    errors = []
    if provenance.get("schema_version") != INPUT_SCHEMA:
        errors.append("provenance schema_version invalid")
    if not isinstance(provenance.get("commit_sha"), str) or not re.fullmatch(
        r"[a-f0-9]{40}", provenance["commit_sha"]
    ):
        errors.append("provenance requires a full commit SHA")
    recorded = provenance.get("source_files")
    if not isinstance(recorded, list) or any(not isinstance(item, dict) for item in recorded):
        errors.append("provenance source inventory malformed")
    elif sorted(recorded, key=lambda item: str(item.get("path"))) != inventory:
        errors.append("source inventory or SHA256 differs from collection provenance")
    if "source_unchanged_after_commands" in provenance and provenance["source_unchanged_after_commands"] is not True:
        errors.append("source changed during collection; provider evidence is not bound to one inventory")
    commands = provenance.get("commands")
    if not isinstance(commands, list) or any(
        not isinstance(command, dict)
        or not isinstance(command.get("argv"), list) or not command["argv"]
        or any(not isinstance(arg, str) for arg in command["argv"])
        or (command.get("exit_code") is not None and not _integer(command["exit_code"], -255))
        for command in commands
    ):
        errors.append("provenance commands malformed")
    limits = provenance.get("limitations", [])
    if not isinstance(limits, list) or any(not isinstance(limit, str) for limit in limits):
        errors.append("provenance limitations malformed")
    pins = provenance.get("artifacts", {})
    if not isinstance(pins, dict) or any(
        name not in ("coverage.json", "complexity.json")
        or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
        for name, digest in pins.items()
    ):
        errors.append("provenance artifact SHA256 mapping malformed")
    return errors


def _provider(provenance, name, artifact, reasons):
    providers = provenance.get("providers", {})
    record = providers.get(name) if isinstance(providers, dict) else None
    if not isinstance(record, dict):
        reasons.append(f"{name}: provider provenance missing")
        return False
    if record.get("status") != "available":
        reasons.append(f"{name}: provider {record.get('status', 'status missing')}")
        return False
    if (type(record.get("exit_code")) is not int or record["exit_code"] != 0
            or not isinstance(record.get("version"), str) or not record["version"]):
        reasons.append(f"{name}: successful provider exit and version required")
        return False
    if artifact is None:
        reasons.append(f"{name}: artifact missing")
        return False
    return True


def _paths(root, records, eligible, label, reasons):
    if not isinstance(records, dict):
        reasons.append(f"{label}: file mapping malformed")
        return {}
    mapped = {}
    duplicates = set()
    for raw, value in records.items():
        if not isinstance(raw, str):
            reasons.append(f"{label}: non-string path")
            continue
        candidate = root / raw
        try:
            path = candidate.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            reasons.append(f"{label}: path outside root: {raw}")
            continue
        if path not in eligible or not _regular(root, candidate):
            reasons.append(f"{label}: path outside eligible scope: {raw}")
        elif path in mapped:
            duplicates.add(path)
            reasons.append(f"{label}: duplicate normalized path: {path}")
        else:
            mapped[path] = value
    for path in duplicates:
        mapped.pop(path, None)
    return mapped


def _line_set(value, line_count):
    if not isinstance(value, list) or any(not _integer(line, 1) or line > line_count for line in value):
        raise ValueError("line list malformed or outside source")
    if len(set(value)) != len(value):
        raise ValueError("duplicate line in coverage artifact")
    return set(value)


def _arcs(value, line_count):
    if not isinstance(value, list) or any(
        not isinstance(arc, list) or len(arc) != 2
        or not _integer(arc[0], 1) or arc[0] > line_count
        or type(arc[1]) is not int or arc[1] == 0 or abs(arc[1]) > line_count
        for arc in value
    ):
        raise ValueError("branch arc list malformed or outside source")
    pairs = {tuple(arc) for arc in value}
    if len(pairs) != len(value):
        raise ValueError("duplicate branch arc")
    return pairs


def _coverage_file(record, line_count):
    if not isinstance(record, dict) or not isinstance(record.get("summary"), dict):
        raise ValueError("file coverage malformed")
    summary = record["summary"]
    fields = ("covered_lines", "num_statements", "missing_lines", "excluded_lines",
              "covered_branches", "num_branches", "missing_branches", "num_partial_branches")
    if any(not _integer(summary.get(key)) for key in fields):
        raise ValueError("coverage counts must be nonnegative integers")
    for key, value in summary.items():
        if key.startswith("percent_") and not key.endswith("_display"):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("coverage percentage must be finite and within 0..100")
    executed = _line_set(record.get("executed_lines"), line_count)
    missing = _line_set(record.get("missing_lines"), line_count)
    excluded = _line_set(record.get("excluded_lines"), line_count)
    if (executed & missing or missing & excluded or len(missing) != summary["missing_lines"]
            or len(excluded) != summary["excluded_lines"]
            or summary["covered_lines"] > len(executed - excluded)
            or summary["num_statements"] > line_count
            or summary["covered_lines"] + len(missing) != summary["num_statements"]):
        raise ValueError("coverage line counts disagree with line evidence")
    executed_arcs = _arcs(record.get("executed_branches"), line_count)
    missing_arcs = _arcs(record.get("missing_branches"), line_count)
    if (executed_arcs & missing_arcs or len(executed_arcs) != summary["covered_branches"]
            or len(missing_arcs) != summary["missing_branches"]
            or len(executed_arcs) + len(missing_arcs) != summary["num_branches"]
            or summary["num_partial_branches"] > summary["missing_branches"]):
        raise ValueError("coverage branch counts disagree with arc evidence")
    return {
        "status": "measured" if summary["num_statements"] else "empty",
        "covered_lines": summary["covered_lines"], "num_statements": summary["num_statements"],
        "line_percent": _percentage(summary["covered_lines"], summary["num_statements"]),
        "covered_branches": summary["covered_branches"], "num_branches": summary["num_branches"],
        "branch_percent": _percentage(summary["covered_branches"], summary["num_branches"]),
    }


def _complexity_file(blocks, definitions, line_count):
    found = {}

    def visit(items):
        if not isinstance(items, list):
            raise ValueError("complexity blocks malformed")
        for block in items:
            if not isinstance(block, dict) or block.get("type") not in ("class", "method", "function"):
                raise ValueError("complexity block type malformed")
            if block["type"] != "class":
                name, line, complexity = block.get("name"), block.get("lineno"), block.get("complexity")
                if (not isinstance(name, str) or not _integer(line, 1) or line > line_count
                        or not _integer(complexity, 1)):
                    raise ValueError("complexity identity or value malformed")
                try:
                    finite = math.isfinite(complexity ** 2 * 1.0)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("complexity cannot produce a finite CRAP value")
                key = (line, name)
                if key not in definitions:
                    raise ValueError(f"complexity function absent from source: {name}:{line}")
                if key in found and found[key] != complexity:
                    raise ValueError(f"conflicting duplicate complexity: {name}:{line}")
                found[key] = complexity
            for children in ("methods", "closures", "inner_classes"):
                if children in block:
                    visit(block[children])

    visit(blocks)
    return found


def _scope(files):
    coverage_files = [item for item in files if item["coverage"] is not None]
    functions = [function for item in files for function in item["functions"]]
    covered = sum(item["coverage"]["covered_lines"] for item in coverage_files)
    statements = sum(item["coverage"]["num_statements"] for item in coverage_files)
    branches = sum(item["coverage"]["num_branches"] for item in coverage_files)
    covered_branches = sum(item["coverage"]["covered_branches"] for item in coverage_files)
    eligible_functions = sum(item["eligible_functions"] for item in files)
    scored = sum(function["crap"] is not None for function in functions)
    complete = bool(files) and all(not item["reasons"] for item in files)
    status = "empty" if not files else (
        "measured" if complete and scored else "partial" if coverage_files or functions else "unavailable"
    )
    return {
        "status": status, "eligible_files": len(files), "eligible_functions": eligible_functions,
        "coverage_matched_files": len(coverage_files),
        "complexity_matched_files": sum(item["complexity_available"] for item in files),
        "complexity_functions": len(functions), "scored_functions": scored,
        "coverage": {
            "denominator": "validated matched files only; missing files have unknown coverage",
            "complete": len(coverage_files) == len(files),
            "covered_lines": covered, "num_statements": statements,
            "line_percent": _percentage(covered, statements),
            "covered_branches": covered_branches, "num_branches": branches,
            "branch_percent": _percentage(covered_branches, branches),
        },
    }


def build_report(root, provenance, coverage, complexity):
    root = Path(root).resolve()
    inventory = source_inventory(root)
    reasons = _provenance_errors(provenance, inventory)
    identity_valid = not reasons
    provenance = provenance if isinstance(provenance, dict) else {}
    coverage_files, complexity_files = {}, {}
    if identity_valid and _provider(provenance, "coverage", coverage, reasons):
        meta = coverage.get("meta") if isinstance(coverage, dict) else None
        if (not isinstance(meta, dict) or meta.get("branch_coverage") is not True
                or meta.get("version") != provenance["providers"]["coverage"]["version"]):
            reasons.append("coverage: artifact metadata/version invalid or branch data absent")
        else:
            coverage_files = _paths(root, coverage.get("files"), {item["path"] for item in inventory},
                                    "coverage", reasons)
    if identity_valid and _provider(provenance, "radon", complexity, reasons):
        complexity_files = _paths(root, complexity, {item["path"] for item in inventory}, "radon", reasons)
    files = []
    for item in inventory:
        path = item["path"]
        file_reasons = []
        line_count = len((root / path).read_bytes().splitlines())
        try:
            definitions = _definitions(root / path)
        except (SyntaxError, ValueError) as error:
            definitions = {}
            file_reasons.append(f"source AST unavailable: {error}")
        measured_coverage = None
        if path in coverage_files:
            try:
                measured_coverage = _coverage_file(coverage_files[path], line_count)
            except ValueError as error:
                file_reasons.append(f"coverage invalid: {error}")
        else:
            file_reasons.append("coverage missing")
        found, complexity_available = {}, False
        if path in complexity_files:
            try:
                found = _complexity_file(complexity_files[path], definitions, line_count)
                complexity_available = True
            except ValueError as error:
                file_reasons.append(f"complexity invalid: {error}")
        else:
            file_reasons.append("complexity missing")
        if len(found) != len(definitions):
            file_reasons.append(f"complexity matched {len(found)} of {len(definitions)} eligible functions")
        functions = []
        for key, value in sorted(found.items()):
            percent = measured_coverage["line_percent"] if measured_coverage else None
            score = value ** 2 * (1 - percent / 100) ** 3 + value if percent is not None else None
            functions.append({"name": definitions[key], "lineno": key[0], "complexity": value,
                              "coverage_percent": percent, "coverage_basis": PROXY, "crap": score})
        files.append({**item, "eligible_functions": len(definitions), "coverage": measured_coverage,
                      "complexity_available": complexity_available, "functions": functions,
                      "reasons": file_reasons})
        reasons.extend(f"{path}: {reason}" for reason in file_reasons)
    commands = provenance.get("commands", [])
    commands = commands if isinstance(commands, list) else []
    failed_commands = [command for command in commands if isinstance(command, dict) and command.get("exit_code") != 0]
    if failed_commands:
        reasons.append("recorded command failed or did not complete; baseline is partial")
    elif not commands:
        reasons.append("no behavioral commands recorded")
    scopes = {kind: _scope([item for item in files if item["kind"] == kind]) for kind in ("production", "test")}
    all_files = _scope(files)
    status = all_files["status"]
    if reasons and status == "measured":
        status = "partial"
    if not identity_valid:
        status = "unavailable"
    if not any(scope["scored_functions"] for scope in scopes.values()):
        reasons.append("no functions scored; no CRAP baseline available")
    limitations = provenance.get("limitations", [])
    return {
        "schema_version": REPORT_SCHEMA, "status": status, "enforcement": "advisory",
        "thresholds": None, "commit_sha": provenance.get("commit_sha"),
        "source_identity_valid": identity_valid, "providers": provenance.get("providers", {}),
        "commands": commands, "failed_commands": failed_commands,
        "artifacts": provenance.get("artifacts", {}),
        "collection": {key: provenance[key] for key in (
            "source_root", "source_mapping", "git_status_before", "git_status_after",
            "source_unchanged_after_commands", "behavioral_radon_executable",
        ) if key in provenance},
        "scopes": scopes, "files": files, "excluded_files": _excluded_inventory(root),
        "reasons": reasons, "limitations": [
            "Python canonical scripts and Python tests only; not whole-repository coverage.",
            PROXY + "; branch coverage is reported separately.",
            "AST def/async-def inventory excludes lambdas and module/class body complexity.",
            "Mutation measurement unavailable; thresholds are undeclared.",
            *(limitations if isinstance(limitations, list) else []),
        ],
    }


def render_markdown(report):
    lines = ["# Advisory Python self-measurement", "", f"Status: **{report['status']}**",
             f"Commit: `{report['commit_sha']}`", "", "No thresholds or grade are assigned.", "",
             "| Scope | Eligible files | Coverage matched | Eligible functions | CRAP scored | Line % | Branch % |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for kind, scope in report["scopes"].items():
        line = scope["coverage"]["line_percent"]
        branch = scope["coverage"]["branch_percent"]
        line = f"{line:.2f}" if line is not None else "unavailable"
        branch = f"{branch:.2f}" if branch is not None else "unavailable"
        lines.append(f"| {kind} | {scope['eligible_files']} | {scope['coverage_matched_files']} | "
                     f"{scope['eligible_functions']} | {scope['scored_functions']} | {line} | {branch} |")
    lines += ["", "Percentages use validated matched files; consult JSON for missing files and exact counts.", ""]
    lines += [f"- {limit}" for limit in report["limitations"]]
    if report["reasons"]:
        lines += ["", "Collection findings:", ""] + [f"- {reason}" for reason in report["reasons"]]
    return "\n".join(lines) + "\n"


def _json_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def _load(path):
    if path is None or not path.exists():
        return None, "artifact missing"
    try:
        return json.loads(path.read_text(), object_pairs_hook=_json_pairs, parse_constant=_invalid_constant), None
    except (OSError, ValueError) as error:
        return None, f"artifact unreadable or malformed: {error}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--complexity", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error("--root must be an existing directory")
    try:
        loaded = {name: _load(getattr(args, name)) for name in ("provenance", "coverage", "complexity")}
        provenance = loaded["provenance"][0]
        # Bind declared raw payload hashes before accepting parsed provider evidence.
        pins = provenance.get("artifacts", {}) if isinstance(provenance, dict) else {}
        for name, filename in (("coverage", "coverage.json"), ("complexity", "complexity.json")):
            if isinstance(pins, dict) and filename in pins and loaded[name][0] is not None:
                if pins[filename] != _digest(getattr(args, name)):
                    loaded[name] = (None, "artifact SHA256 differs from provenance")
        report = build_report(args.root, provenance, loaded["coverage"][0], loaded["complexity"][0])
        report["reasons"].extend(f"{name}: {error}" for name, (_, error) in loaded.items() if error)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        (args.output_dir / "summary.md").write_text(render_markdown(report))
    except (OSError, ValueError) as error:
        print(f"measurement report could not be written: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
