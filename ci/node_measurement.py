#!/usr/bin/env python3
"""Internal advisory native Node coverage; no thresholds or public CLI changes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


METRICS = ("statements", "branches", "functions", "lines")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def inventory(root):
    """Canonical runtime/test sources only; never credit fixture or mirror copies."""
    root = Path(root).resolve()
    candidates = [(p, "production") for pattern in ("bin/*.js", "scripts/*.mjs")
                  for p in root.glob(pattern)]
    candidates += [(p, "test") for extension in ("js", "mjs", "cjs")
                   for p in root.glob(f"tests/**/*.{extension}")
                   if "fixtures" not in p.relative_to(root).parts]
    return sorted([
        {"path": p.relative_to(root).as_posix(), "kind": kind, "sha256": digest(p)}
        for p, kind in candidates if p.is_file() and not any(
            item.is_symlink() for item in (p, *p.parents) if item != root.parent
        ) and p.resolve().is_relative_to(root)
    ], key=lambda item: item["path"])


def provider_identity(provider_root):
    """Record the explicit private CI provider without modifying module lookup/PATH."""
    if provider_root is None:
        return {"status": "unavailable", "reason": "Node measurement provider not requested"}
    root = Path(provider_root).resolve()
    try:
        node = shutil.which("node")
        if not node:
            raise ValueError("Node executable unavailable")
        node = str(Path(node).resolve())
        package = root / "node_modules/c8/package.json"
        c8 = root / "node_modules/c8/bin/c8.js"
        lock = root / "package-lock.json"
        manifest = root / "package.json"
        actual = json.loads(package.read_text())["version"]
        declared = json.loads(manifest.read_text())["devDependencies"]["c8"]
        pinned = json.loads(lock.read_text())["packages"]["node_modules/c8"]["version"]
        if actual != declared or actual != pinned or actual != "12.0.0":
            raise ValueError("c8 installed/declared/locked version mismatch")
        probe_env = dict(os.environ)
        probe_env.pop("NODE_V8_COVERAGE", None)
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=False, env=probe_env)
        if version.returncode:
            raise ValueError("Node version probe failed")
        hashes = {str(p): digest(p) for p in (Path(node), c8, package, lock, manifest)}
        # Lock integrity pins installed packages; record all converter JS/JSON bytes
        # as well so a local modification cannot hide behind a package version.
        for p in sorted((root / "node_modules").rglob("*")):
            if p.is_file() and not p.is_symlink() and p.suffix in (".js", ".cjs", ".mjs", ".json"):
                hashes[str(p)] = digest(p)
        return {"status": "available", "node": node, "node_version": version.stdout.strip(),
                "c8": str(c8), "version": actual, "provider_root": str(root), "hashes": hashes}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "unavailable", "reason": str(exc), "provider_root": str(root)}


def prepare(root, output, provider_root):
    """Prepare fresh child-process collection and exact source/provider identity."""
    raw = output / "node-v8"
    raw.mkdir()
    return {"schema_version": "audit-harness-node-self-measurement/v1",
            "status": "unavailable", "sources": inventory(root),
            "provider": provider_identity(provider_root), "raw_directory": str(raw),
            "source_identity_valid": True, "commands": [], "artifacts": {}, "reasons": [],
            "complexity": None, "crap": None, "thresholds": None,
            "limitations": [
                "Native V8/Istanbul coverage; native functions are not AST function identities.",
                "Only canonical Node production/test inventory is measured, not the whole repository.",
                "Temporary dispatcher copies in timeout tests are not remapped to canonical source.",
                "Killed processes, replaced environments and disabled instrumentation can lose observations.",
                "Shell, wrappers, CI tooling, mirrors, fixtures and mutation remain outside this measurement.",
            ]}


def _report_records(root, path, expected, summary=False):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("converter report is not a file mapping")
    records = {}
    for name, record in value.items():
        if summary and name == "total":
            continue
        source = Path(name)
        if not source.is_absolute() or str(source) != str(source.resolve()):
            raise ValueError("converter path is not direct canonical source")
        relative = source.relative_to(root).as_posix()
        if relative in records or relative not in expected:
            raise ValueError("duplicate or foreign converter source")
        if not isinstance(record, dict):
            raise ValueError("invalid converter file record")
        records[relative] = record
    if set(records) != expected:
        raise ValueError("converter inventory differs from eligible files")
    return records


def validate_reports(root, output, sources):
    expected = {item["path"] for item in sources}
    coverage = _report_records(root, output / "coverage-final.json", expected)
    summaries = _report_records(root, output / "coverage-summary.json", expected, summary=True)
    scopes = {kind: {"files": 0, **{metric: {"covered": 0, "total": 0} for metric in METRICS}}
              for kind in ("production", "test")}
    for item in sources:
        name, kind = item["path"], item["kind"]
        record = coverage[name]
        if record.get("path") != str(root / name):
            raise ValueError("Istanbul record source identity mismatch")
        observed = {}
        for mapping, hits, metric in (("statementMap", "s", "statements"),
                                      ("fnMap", "f", "functions"), ("branchMap", "b", "branches")):
            if not isinstance(record.get(mapping), dict) or not isinstance(record.get(hits), dict):
                raise ValueError("Istanbul coverage map unavailable")
            if set(record[mapping]) != set(record[hits]):
                raise ValueError("Istanbul coverage keys differ")
            counts = []
            for key, value in record[hits].items():
                if hits == "b":
                    definition = record[mapping][key]
                    locations = definition.get("locations") if isinstance(definition, dict) else None
                    if not isinstance(value, list) or not isinstance(locations, list) or len(value) != len(locations):
                        raise ValueError("Istanbul branch hits/locations differ")
                    counts.extend(value)
                else:
                    counts.append(value)
            if any(type(count) is not int or count < 0 for count in counts):
                raise ValueError("Istanbul hit count invalid")
            observed[metric] = {"total": len(counts), "covered": sum(count > 0 for count in counts)}
        # Match Istanbul FileCoverage.getLineCoverage: statements sharing a
        # start line contribute one line, covered when any statement has a hit.
        line_hits = {}
        for key, count in record["s"].items():
            definition = record["statementMap"][key]
            start = definition.get("start") if isinstance(definition, dict) else None
            line = start.get("line") if isinstance(start, dict) else None
            column = start.get("column") if isinstance(start, dict) else None
            if type(line) is not int or line < 1 or type(column) is not int or column < 0:
                raise ValueError("Istanbul statement start position invalid")
            line_hits[line] = max(line_hits.get(line, 0), count)
        observed["lines"] = {"total": len(line_hits),
                             "covered": sum(count > 0 for count in line_hits.values())}
        scopes[kind]["files"] += 1
        for metric in METRICS:
            counts = summaries[name].get(metric, {})
            if not isinstance(counts, dict):
                raise ValueError("native coverage metric is not a count object")
            covered, total = counts.get("covered"), counts.get("total")
            if type(total) is not int or type(covered) is not int or not 0 <= covered <= total:
                raise ValueError("invalid native coverage counts")
            if metric in observed and (covered != observed[metric]["covered"] or total != observed[metric]["total"]):
                raise ValueError("Istanbul hits and summary counts disagree")
            scopes[kind][metric]["covered"] += covered
            scopes[kind][metric]["total"] += total
    for scope in scopes.values():
        for metric in METRICS:
            counts = scope[metric]
            counts["percent"] = 100 * counts["covered"] / counts["total"] if counts["total"] else None
    return scopes


def finish(root, output, state):
    """Convert native data once; incomplete metrics never become a pass grade."""
    root = Path(root).resolve()
    provider = state["provider"]
    commands = state.get("behavioral_commands")
    state["behavioral_success"] = all(command.get("exit_code") == 0 for command in commands) if commands else None
    raw = Path(state["raw_directory"])
    report = output / "node-report"
    config = output / "node-c8.json"
    state["source_identity_valid"] = inventory(root) == state["sources"]
    try:
        if not state["source_identity_valid"]:
            raise ValueError("Node source changed during behavioral collection")
        if not state["sources"]:
            raise ValueError("Node source inventory empty; no measurement")
        if provider["status"] != "available":
            raise ValueError(provider.get("reason", "Node provider unavailable"))
        if any(not Path(p).is_file() or digest(p) != h for p, h in provider["hashes"].items()):
            raise ValueError("Node provider changed during collection")
        files = sorted(raw.glob("*.json"))
        if not files:
            raise ValueError("No native Node data collected; not measured zero")
        canonical_urls = {(root / item["path"]).as_uri() for item in state["sources"]}
        observed_canonical = False
        for path in files:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("result"), list):
                raise ValueError("Malformed native Node coverage")
            observed_canonical |= any(
                isinstance(entry, dict) and entry.get("url") in canonical_urls
                and isinstance(entry.get("functions"), list) and bool(entry["functions"])
                for entry in data["result"]
            )
            state["artifacts"][str(path.relative_to(output))] = digest(path)
        if not observed_canonical:
            raise ValueError("No eligible canonical Node source observed; instrumentation unproven")
        write_json(config, {"all": True, "src": [str(root)],
                            "include": [item["path"] for item in state["sources"]],
                            "exclude": [], "extension": [".js", ".mjs", ".cjs"],
                            "reporter": ["json", "json-summary"], "reports-dir": str(report),
                            "temp-directory": str(raw)})
        clean = dict(os.environ)
        for key in ("NODE_V8_COVERAGE", "COVERAGE_PROCESS_START", "COVERAGE_FILE",
                    "AUDIT_HARNESS_TYPESCRIPT_ROOT"):
            clean.pop(key, None)
        argv = [provider["node"], provider["c8"], "report", "--config", str(config)]
        log = output / "node-report.log"
        with log.open("w") as stream:
            result = subprocess.run(argv, cwd=root, env=clean, stdout=stream, stderr=subprocess.STDOUT,
                                    check=False)
        state["commands"].append({"argv": argv, "exit_code": result.returncode, "log": log.name})
        state["artifacts"][log.name] = digest(log)
        state["artifacts"][config.name] = digest(config)
        if result.returncode:
            raise ValueError(f"c8 report failed (exit {result.returncode})")
        state["scopes"] = validate_reports(root, report, state["sources"])
        for name in ("coverage-final.json", "coverage-summary.json"):
            state["artifacts"]["node-report/" + name] = digest(report / name)
        if inventory(root) != state["sources"]:
            state["source_identity_valid"] = False
            raise ValueError("Node source changed during conversion")
        if any(not Path(p).is_file() or digest(p) != h for p, h in provider["hashes"].items()):
            raise ValueError("Node provider changed during conversion")
        if sorted(raw.glob("*.json")) != files or any(
            digest(path) != state["artifacts"][str(path.relative_to(output))] for path in files
        ):
            raise ValueError("Native Node data changed during conversion")
        state["status"] = "measured"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        state["reasons"].append(str(exc))
        state.pop("scopes", None)
    write_json(output / "node-summary.json", state)
    paragraphs = ["## Advisory Node self-measurement", f"Status: **{state['status']}**."]
    if state["behavioral_success"] is False:
        paragraphs.append("Behavioral commands failed or did not run; coverage is not evidence of passing tests.")
    scopes = [f"- {kind}: {scope['files']} eligible files; native line coverage "
              f"{scope['lines']['covered']}/{scope['lines']['total']}."
              for kind, scope in state.get("scopes", {}).items()]
    if scopes:
        paragraphs.append("\n".join(scopes))
    paragraphs.append("No AST complexity/CRAP, threshold, mutation or whole-repository pass claim.")
    if state["reasons"]:
        paragraphs.append("\n".join(f"- {reason}" for reason in state["reasons"]))
    (output / "node-summary.md").write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
    return state
