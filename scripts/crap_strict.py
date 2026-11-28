#!/usr/bin/env python3
"""Opt-in complete Python or TypeScript CRAP measurement; legacy scoring is unchanged.

Python uses Radon complexity and a file line coverage proxy. TypeScript uses
the caller-installed compiler AST and a file statement coverage proxy. Neither
proxy is per-function coverage. The canonical TypeScript helper owns function
inventory; no independent second parser checks its completeness. Caller-supplied
coverage is validated but its execution provenance is not attested.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess


PROXY = "file line coverage used as a function coverage proxy"


def decode(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique)


def regular(root, path):
    return (
        path.is_file()
        and (path.resolve() == root or root in path.resolve().parents)
        and not any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent)
    )


def relative(root, value):
    if not isinstance(value, str) or not value:
        raise ValueError("invalid file path")
    path = Path(value)
    path = path if path.is_absolute() else root / path
    if ".." in path.parts or not regular(root, path):
        raise ValueError("file path outside root, missing, or symlinked")
    return path.relative_to(root).as_posix()


def definitions(data):
    tree = ast.parse(data)
    return {
        (node.lineno, node.name) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def complexity_rows(blocks, expected):
    found, representations = {}, {}

    def visit(items, context="top"):
        if not isinstance(items, list):
            raise ValueError("complexity blocks must be a list")
        for block in items:
            if not isinstance(block, dict) or block.get("type") not in ("function", "method", "class"):
                raise ValueError("invalid complexity block")
            if block["type"] != "class":
                key = (block.get("lineno"), block.get("name"))
                value = block.get("complexity")
                if (
                    type(key[0]) is not int
                    or not isinstance(key[1], str)
                    or type(value) is not int
                    or not 1 <= value <= 1_000_000
                    or key not in expected
                ):
                    raise ValueError("invalid, duplicate, or unknown complexity function")
                if key in found:
                    previous, contexts = representations[key]
                    # Radon emits class methods both inside class.methods and at
                    # top level. Only this exact duplicate representation is valid.
                    if (
                        block["type"] != "method"
                        or block != previous
                        or context in contexts
                        or {context, *contexts} != {"top", "methods"}
                    ):
                        raise ValueError("invalid, duplicate, or unknown complexity function")
                    contexts.add(context)
                    continue
                found[key] = value
                representations[key] = (block, {context})
            for name in ("methods", "closures", "inner_classes"):
                if name in block:
                    visit(block[name], name)

    visit(blocks)
    if set(found) != expected:
        raise ValueError("complexity omitted source functions")
    return found


def line_coverage(record, line_count):
    if not isinstance(record, dict) or not isinstance(record.get("summary"), dict):
        raise ValueError("invalid coverage record")
    summary = record["summary"]
    for key, value in summary.items():
        if key.startswith("percent_") and not key.endswith("_display"):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("invalid coverage percentage")
    sets = {}
    for name in ("executed_lines", "missing_lines", "excluded_lines"):
        lines = record.get(name)
        if (
            not isinstance(lines, list)
            or any(type(n) is not int or not 1 <= n <= line_count for n in lines)
            or len(lines) != len(set(lines))
        ):
            raise ValueError("invalid coverage line evidence")
        sets[name] = set(lines)
    covered, total = summary.get("covered_lines"), summary.get("num_statements")
    if (
        type(covered) is not int
        or type(total) is not int
        or not 0 <= covered <= total <= line_count
        or total == 0
        or covered + len(sets["missing_lines"]) != total
        or covered != len(sets["executed_lines"] - sets["excluded_lines"])
        or sets["executed_lines"] & sets["missing_lines"]
        or sets["missing_lines"] & sets["excluded_lines"]
    ):
        raise ValueError("coverage counts disagree with line evidence")
    return 100.0 * covered / total


def measure(root, requested, coverage_path, language):
    reasons, inventory, rows = [], {}, []
    scopes = {
        kind: {
            "requested_patterns": patterns,
            "discovered_files": 0,
            "discovered_functions": 0,
            "scored_files": 0,
            "scored_functions": 0,
        }
        for kind, patterns in requested.items()
    }
    for kind, patterns in requested.items():
        if not patterns:
            reasons.append(f"{kind}: missing requested scope")
        for pattern in patterns:
            if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                reasons.append(f"{kind}: invalid scope pattern {pattern!r}")
                continue
            try:
                # pathlib's ** silently skips symlink directories. Check only
                # directories reached by the prefix preceding the first **;
                # e.g. packages/*/src must not scan unrelated node_modules.
                parts = Path(pattern).parts
                if "**" in parts:
                    index = parts.index("**")
                    prefixes = list(root.glob("/".join(parts[:index]))) if index else [root]
                    for prefix in prefixes:
                        if any(p.is_symlink() for p in (prefix, *prefix.parents) if p != root.parent):
                            raise ValueError("symlink directory in scope search")
                        for directory, dirs, _ in os.walk(prefix, followlinks=False):
                            if any((Path(directory) / d).is_symlink() for d in dirs):
                                raise ValueError("symlink directory in scope search")
                matches = list(root.glob(pattern))
            except (OSError, ValueError, NotImplementedError):
                reasons.append(f"{kind}: invalid scope pattern {pattern!r}")
                continue
            if not matches:
                reasons.append(f"{kind}: unmatched scope pattern {pattern!r}")
            for path in matches:
                try:
                    name = relative(root, str(path))
                    if name in inventory:
                        if inventory[name]["kind"] != kind:
                            raise ValueError("overlapping source/test classification")
                        continue
                    data = path.read_bytes()
                    item = {"kind": kind, "sha256": hashlib.sha256(data).hexdigest()}
                    inventory[name] = item
                    scopes[kind]["discovered_files"] += 1
                    if language in ("auto", "typescript") and path.suffix in (".ts", ".tsx", ".mts", ".cts"):
                        item["typescript"] = True
                        continue
                    if language not in ("auto", "python") or path.suffix != ".py":
                        raise ValueError("unsupported strict provider; Python or TypeScript files only")
                    item["definitions"] = definitions(data)
                    item["line_count"] = len(data.splitlines())
                    scopes[kind]["discovered_functions"] += len(item["definitions"])
                except (OSError, ValueError, SyntaxError) as error:
                    reasons.append(f"{kind}: {path.relative_to(root)}: {error}")
    if language == "typescript" or (language == "auto" and any(i.get("typescript") for i in inventory.values())):
        return measure_typescript(root, inventory, scopes, reasons, coverage_path)
    coverage = {}
    coverage_hash = None
    try:
        coverage_bytes = coverage_path.read_bytes()
        coverage_hash = hashlib.sha256(coverage_bytes).hexdigest()
        raw = decode(coverage_bytes.decode())
        if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict):
            raise ValueError("coverage files must be an object")
        for path, record in raw["files"].items():
            name = relative(root, path)
            if name in coverage:
                raise ValueError("duplicate normalized coverage file")
            coverage[name] = record
    except (OSError, ValueError, TypeError) as error:
        reasons.append(f"coverage unavailable or invalid: {error}")
    if language == "auto":
        language = "python" if inventory and all("definitions" in item for item in inventory.values()) else "unknown"
    provider = shutil.which("radon") if language == "python" else None
    provider_hash = None
    if provider:
        try:
            provider_hash = hashlib.sha256(Path(provider).read_bytes()).hexdigest()
        except OSError as error:
            reasons.append(f"provider identity unavailable: {error}")
            provider = None
    if not provider:
        reasons.append("missing or unsupported complexity provider")
    for name, item in sorted(inventory.items()):
        if "definitions" not in item or not provider:
            continue
        try:
            result = subprocess.run(
                [provider, "cc", "-s", "-j", name], cwd=root, capture_output=True, text=True, timeout=60, check=False
            )
            if result.returncode:
                raise ValueError(f"complexity provider failed (exit {result.returncode})")
            reports = decode(result.stdout)
            if not isinstance(reports, dict):
                raise ValueError("invalid complexity provider output")
            normalized = {}
            for path, blocks in reports.items():
                key = relative(root, path)
                if key in normalized:
                    raise ValueError("duplicate normalized complexity file")
                normalized[key] = blocks
            # Radon omits files with no blocks; their AST inventory must also be empty.
            if not normalized and not item["definitions"]:
                normalized[name] = []
            if set(normalized) != {name}:
                raise ValueError("complexity file inventory mismatch")
            complexities = complexity_rows(normalized[name], item["definitions"])
            if name not in coverage:
                raise ValueError("coverage missing for requested file")
            percent = line_coverage(coverage[name], item["line_count"])
            current = root / name
            if not regular(root, current) or hashlib.sha256(current.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("source changed during measurement")
            scopes[item["kind"]]["scored_files"] += 1
            scopes[item["kind"]]["scored_functions"] += len(complexities)
            for (line, method), complexity in sorted(complexities.items()):
                score = complexity**2 * (1 - percent / 100) ** 3 + complexity
                rows.append(
                    {
                        "path": name,
                        "method": method,
                        "line": line,
                        "kind": item["kind"],
                        "complexity": complexity,
                        "coverage": percent,
                        "crap": score,
                    }
                )
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
            reasons.append(f"{name}: {error}")
    for kind, scope in scopes.items():
        if not scope["scored_functions"]:
            reasons.append(f"{kind}: no functions scored")
    for name, item in inventory.items():
        try:
            path = root / name
            if not regular(root, path) or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                reasons.append(f"{name}: source changed during measurement")
        except OSError:
            reasons.append(f"{name}: source unavailable after measurement")
    for label, path, expected in (
        ("coverage", coverage_path, coverage_hash),
        ("provider", Path(provider) if provider else None, provider_hash),
    ):
        if path is not None and expected is not None:
            try:
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    reasons.append(f"{label} changed during measurement")
            except OSError:
                reasons.append(f"{label} unavailable after measurement")
    public_inventory = [
        {"path": name, "kind": item["kind"], "sha256": item["sha256"]} for name, item in sorted(inventory.items())
    ]
    return {
        "schema_version": "crap-measurement/v1",
        "complete": not reasons,
        "coverage_basis": PROXY,
        "scopes": scopes,
        "inventory": public_inventory,
        "inputs": {
            "coverage_sha256": coverage_hash,
            "provider_executable_sha256": provider_hash,
            "provider": "radon" if provider else None,
        },
        "reasons": reasons,
        "methods": rows,
    }


TS_PROXY = "file statement coverage used as a function coverage proxy"


def statement_coverage(record, path, root, text, type_only):
    if not isinstance(record, dict) or relative(root, record.get("path")) != path:
        raise ValueError("invalid Istanbul path")
    locations, counts = record.get("statementMap"), record.get("s")
    if not isinstance(locations, dict) or not isinstance(counts, dict) or set(locations) != set(counts):
        raise ValueError("Istanbul statement/count inventory mismatch")
    lines = text.split("\n")

    def point(value):
        if not isinstance(value, dict):
            raise ValueError("invalid Istanbul location")
        line, column = value.get("line"), value.get("column")
        if (
            type(line) is not int
            or type(column) is not int
            or not 1 <= line <= len(lines)
            or not 0 <= column <= len(lines[line - 1].encode("utf-16-le")) // 2
        ):
            raise ValueError("invalid Istanbul location")
        return line, column

    for key, location in locations.items():
        if not isinstance(location, dict) or point(location.get("start")) > point(location.get("end")):
            raise ValueError("invalid Istanbul statement range")
        if type(counts[key]) is not int or not 0 <= counts[key] <= 2**53 - 1:
            raise ValueError("invalid Istanbul statement count")
    # Validate the other Istanbul counters even though they are not the proxy.
    for map_name, count_name in (("fnMap", "f"), ("branchMap", "b")):
        mapping, hits = record.get(map_name), record.get(count_name)
        if not isinstance(mapping, dict) or not isinstance(hits, dict) or set(mapping) != set(hits):
            raise ValueError("Istanbul counter inventory mismatch")
        for key, entry in mapping.items():
            if not isinstance(entry, dict):
                raise ValueError("invalid Istanbul counter entry")
            ranges = entry.get("locations") if map_name == "branchMap" else [entry.get("loc")]
            values = hits[key] if map_name == "branchMap" else [hits[key]]
            if not isinstance(ranges, list) or not isinstance(values, list) or len(ranges) != len(values):
                raise ValueError("invalid Istanbul branch counters")
            # ast-v8-to-istanbul emits an absent IfStatement.alternate as
            # undefined endpoints, serialized to exactly {start: {}, end: {}}.
            # It has a counter but no source span. No other missing location
            # is exempt, and the enclosing if and its first arm must be valid.
            implicit_else = (
                map_name == "branchMap"
                and entry.get("type") == "if"
                and len(ranges) == 2
                and ranges[1] == {"start": {}, "end": {}}
            )
            if implicit_else:
                parent = entry.get("loc")
                if not isinstance(parent, dict) or point(parent.get("start")) > point(parent.get("end")):
                    raise ValueError("invalid Istanbul implicit-else parent location")
            for index, (location, value) in enumerate(zip(ranges, values)):
                if type(value) is not int or not 0 <= value <= 2**53 - 1:
                    raise ValueError("invalid Istanbul counter or location")
                if implicit_else and index == 1:
                    continue
                if not isinstance(location, dict) or point(location.get("start")) > point(location.get("end")):
                    raise ValueError("invalid Istanbul counter or location")
    if not counts and not type_only:
        raise ValueError("empty Istanbul statements for runtime file")
    return 100 * sum(value > 0 for value in counts.values()) / len(counts) if counts else None


def ts_inventory(record, item, text):
    if not isinstance(record, dict) or record.get("sha256") != item["sha256"]:
        raise ValueError("TypeScript source identity mismatch")
    if type(record.get("type_only")) is not bool:
        raise ValueError("invalid TypeScript type-only classification")
    definitions, methods = record.get("inventory"), record.get("methods")
    if not isinstance(definitions, list) or not isinstance(methods, list):
        raise ValueError("invalid TypeScript function inventory")
    expected = {}
    encoded = text.encode("utf-16-le")
    length = len(encoded) // 2
    for entry in definitions:
        if not isinstance(entry, dict):
            raise ValueError("invalid TypeScript function")
        start, end, line = entry.get("start"), entry.get("end"), entry.get("line")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= length
            or type(line) is not int
            or not 1 <= line <= len(text.split("\n"))
            or line != encoded[: start * 2].decode("utf-16-le", errors="surrogatepass").count("\n") + 1
            or entry.get("id") != f"{start}:{end}"
            or entry["id"] in expected
            or not isinstance(entry.get("name"), str)
            or not entry["name"]
            or entry.get("kind")
            not in (
                "FunctionDeclaration",
                "FunctionExpression",
                "ArrowFunction",
                "MethodDeclaration",
                "Constructor",
                "GetAccessor",
                "SetAccessor",
            )
        ):
            raise ValueError("invalid or duplicate TypeScript function")
        expected[entry["id"]] = entry
    return expected


def ts_complexities(record, expected):
    found = {}
    for entry in record["methods"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("invalid TypeScript complexity")
        identifier, value = entry["id"], entry.get("complexity")
        if identifier not in expected or identifier in found or type(value) is not int or not 1 <= value <= 1_000_000:
            raise ValueError("invalid or duplicate TypeScript complexity")
        found[identifier] = value
    if set(found) != set(expected) or (record["type_only"] and expected):
        raise ValueError("TypeScript function inventory mismatch")
    return [(expected[key], value) for key, value in found.items()]


def measure_typescript(root, inventory, scopes, reasons, coverage_path):
    rows, public_inventory, coverage, records = [], [], {}, {}
    inputs = {"provider": "typescript", "coverage_sha256": None}
    checks = []

    def capture(label, path):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        inputs[label + "_sha256"] = digest
        checks.append((label, path, digest))
        return data

    try:
        coverage = decode(capture("coverage", coverage_path).decode())
        if not isinstance(coverage, dict):
            raise ValueError("Istanbul coverage must be an object")
        normalized = {}
        for path, record in coverage.items():
            name = relative(root, path)
            if name in normalized:
                raise ValueError("duplicate normalized Istanbul file")
            normalized[name] = record
        coverage = normalized
    except (OSError, ValueError, TypeError) as error:
        reasons.append(f"coverage unavailable or invalid: {error}")
        coverage = {}
    try:
        if any(not item.get("typescript") for item in inventory.values()):
            raise ValueError("mixed or unsupported TypeScript source inventory")
        helper = Path(__file__).with_name("crap_typescript.mjs")
        capture("helper", helper)
        node = shutil.which("node")
        if not node:
            raise ValueError("missing Node TypeScript provider executable")
        capture("provider_executable", Path(node))
        # Explicit target-root installation; never search parent/global packages.
        parser = (root / "node_modules/typescript/lib/typescript.js").resolve(strict=True)
        parser_hash = hashlib.sha256(capture("parser", parser)).hexdigest()
        result = subprocess.run(
            [node, str(helper)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            input=json.dumps(
                {
                    "root": str(root),
                    "files": [{"path": name, "sha256": item["sha256"]} for name, item in sorted(inventory.items())],
                }
            ),
        )
        if result.returncode:
            raise ValueError(f"TypeScript provider failed (exit {result.returncode}): {result.stderr.strip()}")
        report = decode(result.stdout)
        if not isinstance(report, dict) or report.get("schema_version") != "crap-typescript/v1":
            raise ValueError("invalid TypeScript provider report")
        identity = report.get("provider")
        if (
            not isinstance(identity, dict)
            or identity.get("name") != "typescript"
            or identity.get("path") != str(parser)
            or identity.get("sha256") != parser_hash
            or not isinstance(identity.get("version"), str)
            or not identity["version"]
            or report.get("complexity_definition") != "typescript-function-decisions/v1"
        ):
            raise ValueError("TypeScript provider identity mismatch")
        inputs["parser_version"] = identity["version"]
        records = report.get("files")
        if not isinstance(records, dict) or set(records) != set(inventory):
            raise ValueError("TypeScript provider file inventory mismatch")
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
        reasons.append(str(error))
        records = {}
    for name, item in sorted(inventory.items()):
        public = {"path": name, "kind": item["kind"], "sha256": item["sha256"]}
        public_inventory.append(public)
        if name not in records:
            continue
        try:
            text = (root / name).read_bytes().decode("utf-8")
            expected = ts_inventory(records[name], item, text)
            scope = scopes[item["kind"]]
            scope["discovered_functions"] += len(expected)
            public["type_only"] = records[name]["type_only"]
            public["functions"] = list(expected.values())
            functions = ts_complexities(records[name], expected)
            if name not in coverage:
                if not public["type_only"]:
                    raise ValueError("coverage missing for requested runtime file")
                percent = None
            else:
                percent = statement_coverage(coverage[name], name, root, text, public["type_only"])
            if public["type_only"]:
                scope["type_only_files"] = scope.get("type_only_files", 0) + 1
            else:
                scope["scored_files"] += 1
            scope["scored_functions"] += len(functions)
            for function, complexity in functions:
                rows.append(
                    {
                        "path": name,
                        "method": function["name"],
                        "line": function["line"],
                        "function_id": function["id"],
                        "kind": item["kind"],
                        "complexity": complexity,
                        "coverage": percent,
                        "crap": complexity**2 * (1 - percent / 100) ** 3 + complexity,
                    }
                )
        except (OSError, ValueError, TypeError) as error:
            reasons.append(f"{name}: {error}")
    for kind, scope in scopes.items():
        if not scope["scored_functions"]:
            reasons.append(f"{kind}: no functions scored")
    for name, item in inventory.items():
        checks.append((name, root / name, item["sha256"]))
    try:
        if (
            "parser_sha256" in inputs
            and (root / "node_modules/typescript/lib/typescript.js").resolve(strict=True) != parser
        ):
            reasons.append("parser resolution changed during measurement")
    except OSError:
        reasons.append("parser unavailable after measurement")
    for label, path, expected in checks:
        try:
            if (label in inventory and not regular(root, path)) or hashlib.sha256(
                path.read_bytes()
            ).hexdigest() != expected:
                reasons.append(f"{label} changed during measurement")
        except OSError:
            reasons.append(f"{label} unavailable after measurement")
    return {
        "schema_version": "crap-measurement/v1",
        "complete": not reasons,
        "coverage_basis": TS_PROXY,
        "complexity_definition": "typescript-function-decisions/v1",
        "scopes": scopes,
        "inventory": public_inventory,
        "inputs": inputs,
        "reasons": reasons,
        "methods": rows,
    }


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-measurement", action="store_true")
    parser.add_argument("--root", default=".")
    parser.add_argument("--lang", default="auto")
    parser.add_argument("--target", choices=("src", "test", "both"), default="both")
    parser.add_argument("--source-glob", action="append", default=[])
    parser.add_argument("--test-glob", action="append", default=[])
    parser.add_argument("--coverage-json", required=True)
    parser.add_argument("--out", default="reports/crap")
    parser.add_argument("--format", choices=("csv", "json", "both"), default="both")
    parser.add_argument("--json", action="store_true")
    for name, default in (("prod", 30.0), ("test", 15.0), ("avg", 10.0)):
        parser.add_argument(f"--threshold-{name}", type=float, default=default)
    args = parser.parse_args(argv)
    thresholds = {
        "production_max": args.threshold_prod,
        "test_max": args.threshold_test,
        "project_avg_max": args.threshold_avg,
    }
    if any(not math.isfinite(n) or n < 0 for n in thresholds.values()):
        parser.error("thresholds must be finite nonnegative numbers")
    if (args.target == "src" and args.test_glob) or (args.target == "test" and args.source_glob):
        parser.error("scope supplied for an unrequested target kind")
    requested = {}
    if args.target in ("src", "both"):
        requested["src"] = args.source_glob
    if args.target in ("test", "both"):
        requested["test"] = args.test_glob
    root = Path(args.root).resolve()
    report = measure(root, requested, root / args.coverage_json, args.lang)
    prod = [m["crap"] for m in report["methods"] if m["kind"] == "src"]
    test = [m["crap"] for m in report["methods"] if m["kind"] == "test"]
    breached = (
        any(n > args.threshold_prod for n in prod)
        or any(n > args.threshold_test for n in test)
        or (bool(prod) and sum(prod) / len(prod) > args.threshold_avg)
    )
    report.update(thresholds=thresholds, **{"pass": report["complete"] and not breached})
    out = root / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    if args.format in ("csv", "both"):
        for kind in requested:
            with (out / f"crap-{kind}.csv").open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["rank", "crap", "complexity", "coverage_pct", "path", "method"])
                ranked = sorted(
                    (m for m in report["methods"] if m["kind"] == kind), key=lambda m: m["crap"], reverse=True
                )
                for rank, row in enumerate(ranked, 1):
                    writer.writerow([rank, row["crap"], row["complexity"], row["coverage"], row["path"], row["method"]])
    if args.json:
        import os

        def digest(value):
            return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

        envelope = {
            "gate_id": f"audit-harness:{os.environ.get('AUDIT_HARNESS_SIDE', 'ci')}:crap-score",
            "result": "PASS" if report["pass"] else "FAIL",
            "input_hash": digest({"inventory": report["inventory"], "inputs": report["inputs"]}),
            "policy_hash": digest({"thresholds": thresholds, "requested": requested}),
            "metadata": {"measurement": report, "summary_path": str(out / "summary.json")},
        }
        if not report["pass"]:
            envelope["failure_mode"] = (
                "crap-measurement-incomplete" if not report["complete"] else "crap-threshold-exceeded"
            )
        print(json.dumps(envelope))
    else:
        print(
            json.dumps(
                {"pass": report["pass"], "complete": report["complete"], "summary_path": str(out / "summary.json")}
            )
        )
    return 2 if not report["complete"] else 1 if breached else 0
