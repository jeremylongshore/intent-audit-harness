#!/usr/bin/env python3
"""CRAP (Change Risk Analyzer and Predictor) calculator — multi-language.

Reads language-native complexity and coverage outputs, computes
    CRAP(m) = C(m)^2 * (1 - cov(m)/100)^3 + C(m)
for every method, ranks them, and emits CSV + JSON.

Walls 5 and 6 of the Seven Walls (audit-tests skill):
  - Production code: no method CRAP > 30; project average <= 10.
  - Test code:       no method CRAP > 15.

Thresholds are configurable via --threshold (local tuning is logged).
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class MethodScore:
    language: str
    path: str
    method: str
    complexity: int
    coverage: float
    crap: float
    kind: str  # "src" or "test"


class MeasurementError(ValueError):
    """The collector did not supply usable measurement evidence."""


def positive_complexity(value) -> int:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 1 or int(value) != value):
        raise MeasurementError("missing or invalid method complexity")
    return int(value)


def source_inventory(root: Path, lang: str) -> dict[str, list[Path]]:
    extensions = {"python": (".py",), "go": (".go",),
                  "js": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"),
                  "rust": (".rs",)}
    partitions: dict[str, list[Path]] = {"src": [], "test": []}
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not is_excluded_dir(d))
        for filename in sorted(files):
            if not filename.endswith(extensions.get(lang, ())):
                continue
            path = Path(directory) / filename
            rel = path.relative_to(root)
            test = (any(p in {"tests", "test", "spec", "specs", "__tests__"} for p in rel.parts[:-1])
                    or filename.startswith("test_") or filename.endswith(("_test.py", "_test.go"))
                    or any(marker in filename for marker in (".test.", ".spec.")))
            partitions["test" if test else "src"].append(path)
    return partitions


# Directories to skip during candidate discovery AND the --json input-hash
# walk. Single source of truth — both call sites MUST use this set so a repo
# with `reports/` (or `.next/`, `.nuxt/`, `.cache/`) gets identical treatment
# in both the candidate scan and the input-hash computation. Adding a dir
# here removes it from BOTH passes; that's the invariant this constant exists
# to preserve.
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", "target", ".tox", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", ".cache", "reports",
}


def is_excluded_dir(name: str) -> bool:
    """Single exclusion predicate shared by the candidate-discovery walk and
    the --json input-hash walk.

    Both walks MUST agree on which directories they descend into; otherwise the
    set of files that feed the CRAP score can diverge from the set that feeds
    the input_hash, and the score/hash desync (a hash that claims to cover
    files the score never saw, or vice versa). The rule is: skip any dot-dir
    (e.g. `.idea`, `.svn`, `.git`) OR any explicitly-named build/vendor dir in
    EXCLUDED_DIRS. Previously discovery dropped all dot-dirs while the hash walk
    dropped only the named subset, so a dot-dir not in EXCLUDED_DIRS was hashed
    but never scored.
    """
    return name.startswith(".") or name in EXCLUDED_DIRS


def crap(complexity: int, coverage_pct: float) -> float:
    cov = max(0.0, min(100.0, coverage_pct)) / 100.0
    return (complexity ** 2) * ((1.0 - cov) ** 3) + complexity


def detect_language(root: Path) -> str:
    candidates = [
        ("pyproject.toml", "python"),
        ("setup.py", "python"),
        ("package.json", "js"),
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("build.gradle.kts", "java"),
        ("composer.json", "php"),
        ("Gemfile", "ruby"),
        ("*.csproj", "dotnet"),
    ]
    for pattern, lang in candidates:
        if "*" in pattern:
            if any(root.glob(pattern)):
                return lang
        elif (root / pattern).is_file():
            return lang
    return "unknown"


def which_or_none(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    return p.returncode, p.stdout, p.stderr


# ---------- Python: radon + coverage ----------

def score_python(root: Path, kind: str, *, read_only: bool = False) -> list[MethodScore]:
    if kind == "src":
        candidates = ["src", "myapp", "app"]
        scanned = [t for t in candidates if (root / t).is_dir()]
        if not scanned:
            test_dirs = {"tests", "test", "spec", "specs", "features", "__tests__"}
            scanned = [
                p.name for p in root.iterdir()
                if p.is_dir()
                and not is_excluded_dir(p.name)
                and p.name not in test_dirs
                and any(p.rglob("*.py"))
            ]
    else:
        candidates = ["tests", "test"]
        scanned = [t for t in candidates if (root / t).is_dir()]
    if not scanned:
        return []

    if which_or_none("radon") is None:
        raise MeasurementError("radon not installed")

    complexity: dict[tuple[str, str, int], int] = {}

    def visit(fpath, blocks):
        if not isinstance(blocks, list):
            raise MeasurementError("malformed radon blocks")
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") not in {"class", "method", "function"}:
                raise MeasurementError("invalid radon block type")
            if block["type"] != "class":
                name, line = block.get("name"), block.get("lineno")
                if not isinstance(name, str) or not name or type(line) is not int or line < 1:
                    raise MeasurementError("invalid radon function identity")
                key = (fpath, name, line)
                value = positive_complexity(block["complexity"])
                if key in complexity and complexity[key] != value:
                    raise MeasurementError("conflicting duplicate radon function")
                complexity[key] = value
            for field in ("methods", "closures", "inner_classes"):
                if field in block:
                    visit(fpath, block[field])

    for tgt in scanned:
        rc, out, err = run(["radon", "cc", "-s", "-a", "-j", tgt], root)
        if rc != 0 or not out.strip():
            raise MeasurementError("radon failed or returned empty output")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise MeasurementError("invalid radon JSON") from None
        for fpath, blocks in data.items():
            resolved = (root / fpath).resolve()
            if root not in resolved.parents or not resolved.is_file():
                raise MeasurementError("radon path is outside the source root")
            visit(fpath, blocks)
            tree = ast.parse((root / fpath).read_text())
            definitions = {(node.name, node.lineno) for node in ast.walk(tree)
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            measured = {(name, line) for path, name, line in complexity if path == fpath}
            if definitions != measured:
                raise MeasurementError("radon function inventory differs from source definitions")

    coverage: dict[str, float] = {}
    cov_json = root / "coverage.json"
    if not read_only and not cov_json.is_file() and which_or_none("coverage"):
        run(["coverage", "json", "-o", "coverage.json", "--fail-under=0"], root)
    if cov_json.is_file():
        try:
            cov_data = json.loads(cov_json.read_text())
            for fpath, summary in cov_data.get("files", {}).items():
                pct = summary.get("summary", {}).get("percent_covered", 0.0)
                coverage[fpath] = float(pct)
        except (OSError, json.JSONDecodeError):
            pass

    scores: list[MethodScore] = []
    for (fpath, name, line), c in complexity.items():
        cov = coverage.get(fpath, 0.0)
        scores.append(
            MethodScore(
                language="python",
                path=fpath,
                method=f"{name}:{line}",
                complexity=c,
                coverage=cov,
                crap=crap(c, cov),
                kind=kind,
            )
        )
    return scores


# ---------- Go: gocyclo + go test -cover ----------

def score_go(root: Path, kind: str, *, read_only: bool = False) -> list[MethodScore]:
    if which_or_none("gocyclo") is None:
        raise MeasurementError("gocyclo not installed")

    # For kind="src", ignore *_test.go at the gocyclo level. For kind="test",
    # do NOT pass -ignore: a pattern like `.*\.go$` matches every analyzable
    # file (gocyclo only reads .go files), which silenced all test-kind output.
    # The include-filter below keeps only *_test.go rows for kind="test".
    gocyclo_cmd = ["gocyclo"]
    if kind == "src":
        gocyclo_cmd += ["-ignore", "_test.go"]
    gocyclo_cmd.append(".")
    rc, out, _ = run(gocyclo_cmd, root)
    if rc != 0:
        raise MeasurementError("gocyclo failed")
    complexity: list[tuple[str, str, int, int]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.strip().split()
        if len(parts) < 4:
            raise MeasurementError("malformed gocyclo row")
        try:
            c = int(parts[0])
        except ValueError:
            raise MeasurementError("invalid gocyclo complexity") from None
        pkg = parts[1]
        func = parts[2]
        location = parts[3].rsplit(":", 2)
        if len(location) != 3 or not location[1].isdigit() or not location[2].isdigit():
            raise MeasurementError("invalid gocyclo source location")
        fpath, line_number = location[0], int(location[1])
        include = fpath.endswith("_test.go") if kind == "test" else not fpath.endswith("_test.go")
        if include:
            complexity.append((fpath, f"{pkg}.{func}", line_number, c))

    coverage: dict[tuple[str, int, str], float] = {}
    cov_out = root / "coverage.out"
    if not read_only and not cov_out.is_file() and which_or_none("go"):
        run(["go", "test", "-coverprofile=coverage.out", "-covermode=atomic", "./..."], root)
    if cov_out.is_file() and which_or_none("go"):
        # `go tool cover -func` reports module-qualified paths
        # (github.com/user/repo/pkg/file.go) while gocyclo reports repo-relative
        # paths (pkg/file.go). Strip the module prefix read from go.mod so the
        # coverage keys join the complexity keys.
        module_prefix = ""
        go_mod = root / "go.mod"
        if go_mod.is_file():
            try:
                for mod_line in go_mod.read_text().splitlines():
                    mod_line = mod_line.strip()
                    if mod_line.startswith("module ") or mod_line.startswith("module\t"):
                        module_prefix = mod_line.split(None, 1)[1].strip() + "/"
                        break
            except OSError:
                pass
        rc, out, _ = run(["go", "tool", "cover", "-func=coverage.out"], root)
        if rc != 0:
            raise MeasurementError("go coverage reader failed")
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[-1].endswith("%"):
                location = parts[0].rstrip(":").rsplit(":", 1)
                if len(location) != 2 or not location[1].isdigit():
                    continue  # `total: (statements) ...` is not a function.
                fpath, line_number = location[0], int(location[1])
                if module_prefix and fpath.startswith(module_prefix):
                    fpath = fpath[len(module_prefix):]
                try:
                    pct = float(parts[-1].rstrip("%"))
                except ValueError:
                    continue
                key = (fpath, line_number, parts[1])
                if key in coverage and coverage[key] != pct:
                    raise MeasurementError("conflicting duplicate Go function coverage")
                coverage[key] = pct

    scores: list[MethodScore] = []
    for fpath, name, line_number, c in complexity:
        cov = coverage.get((fpath, line_number, name.rsplit(".", 1)[-1]), 0.0)
        scores.append(
            MethodScore(
                language="go", path=fpath, method=name, complexity=c,
                coverage=cov, crap=crap(c, cov), kind=kind,
            )
        )
    return scores


# ---------- JS/TS: complexity-report + c8 ----------

def score_js(root: Path, kind: str, *, read_only: bool = False) -> list[MethodScore]:
    cr_bin = which_or_none("cr") or which_or_none("complexity-report")
    if cr_bin is None:
        raise MeasurementError("complexity-report not installed")
    target = "src" if kind == "src" else "tests"
    if not (root / target).is_dir():
        return []
    rc, out, _ = run([cr_bin, "--format", "json", target], root)
    if rc != 0 or not out.strip():
        raise MeasurementError("complexity-report failed or returned empty output")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise MeasurementError("invalid complexity-report JSON") from None

    # c8/istanbul's json-summary reporter keys files by ABSOLUTE path while
    # complexity-report (run with a repo-relative target) reports repo-relative
    # paths. Normalize both sides to repo-relative so the coverage join works.
    def _rel_to_root(p: str) -> str:
        if os.path.isabs(p):
            try:
                return os.path.relpath(p, str(root))
            except ValueError:
                return p  # e.g. different drive on Windows — keep as-is
        return p

    cov_path = root / "coverage" / "coverage-summary.json"
    coverage: dict[str, float] = {}
    if cov_path.is_file():
        try:
            cov_data = json.loads(cov_path.read_text())
            for fpath, summary in cov_data.items():
                if fpath == "total":
                    continue
                lines_pct = summary.get("lines", {}).get("pct", 0.0)
                coverage[_rel_to_root(fpath)] = float(lines_pct)
        except (OSError, json.JSONDecodeError):
            pass

    scores: list[MethodScore] = []
    for report in data.get("reports", []):
        fpath = report.get("path", "")
        cov = coverage.get(_rel_to_root(fpath), 0.0)
        for func in report.get("functions", []):
            c = positive_complexity(func["cyclomatic"])
            scores.append(
                MethodScore(
                    language="js", path=fpath, method=func.get("name", "<anon>"),
                    complexity=c, coverage=cov, crap=crap(c, cov), kind=kind,
                )
            )
    return scores


# ---------- Rust: rust-code-analysis + tarpaulin ----------

def score_rust(root: Path, kind: str, *, read_only: bool = False) -> list[MethodScore]:
    rca = which_or_none("rust-code-analysis-cli")
    if rca is None:
        raise MeasurementError("rust-code-analysis-cli not installed")
    target = "src" if kind == "src" else "tests"
    if not (root / target).is_dir():
        return []
    rc, out, _ = run([rca, "-m", "-O", "json", "-p", target], root)
    if rc != 0 or not out.strip():
        raise MeasurementError("rust-code-analysis failed or returned empty output")
    complexity: list[tuple[str, str, int]] = []

    def visit(fpath, space):
        if not isinstance(space, dict) or not isinstance(space.get("spaces"), list):
            raise MeasurementError("invalid rust-code-analysis space")
        space_kind = space.get("kind")
        if space_kind == "function":
            c = positive_complexity(space["metrics"]["cyclomatic"]["sum"])
            complexity.append((fpath, space.get("name") or "<anon>", c))
        elif space_kind not in {"unit", "impl", "class", "struct", "trait", "namespace", "interface"}:
            raise MeasurementError("unsupported rust-code-analysis space kind")
        for nested in space["spaces"]:
            visit(fpath, nested)

    # RCA serializes one nested FuncSpace per file. A container's aggregate
    # metric is not a method; traverse to actual function spaces instead.
    decoder = json.JSONDecoder()
    remaining = out.strip()
    while remaining:
        try:
            rec, offset = decoder.raw_decode(remaining)
        except json.JSONDecodeError:
            raise MeasurementError("invalid rust-code-analysis JSON") from None
        if not isinstance(rec, dict) or rec.get("kind") != "unit" or not isinstance(rec.get("name"), str):
            raise MeasurementError("missing rust-code-analysis file unit")
        visit(rec["name"], rec)
        remaining = remaining[offset:].lstrip()
    scores: list[MethodScore] = []
    for fpath, name, c in complexity:
        scores.append(
            MethodScore(
                language="rust", path=fpath, method=name, complexity=c,
                coverage=0.0, crap=crap(c, 0.0), kind=kind,
            )
        )
    return scores


DISPATCH = {
    "python": score_python,
    "go": score_go,
    "js": score_js,
    "rust": score_rust,
}


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="Repository root")
    ap.add_argument("--target", choices=["src", "test", "both"], default="both")
    ap.add_argument("--format", choices=["csv", "json", "both"], default="both")
    ap.add_argument("--out", default="reports/crap", help="Output directory")
    ap.add_argument("--read-only", action="store_true",
                    help="Use existing coverage only; require --out outside the subject")
    ap.add_argument("--lang", default="auto",
                    help="Force language (python|go|js|rust); default auto-detect")
    ap.add_argument("--threshold-prod", type=float, default=30.0,
                    help="Production CRAP max (default 30)")
    ap.add_argument("--threshold-test", type=float, default=15.0,
                    help="Test CRAP max (default 15)")
    ap.add_argument("--threshold-avg", type=float, default=10.0,
                    help="Project average max (default 10)")
    ap.add_argument("--json", action="store_true",
                    help="Emit gate-result envelope JSON on stdout (suitable for piping "
                         "to `audit-harness emit-evidence`). Preserves existing CSV/JSON "
                         "files written under --out.")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    lang = args.lang if args.lang != "auto" else detect_language(root)
    out_dir = (root / args.out).resolve()
    if args.read_only and (out_dir == root or root in out_dir.parents):
        ap.error("--read-only requires --out outside the subject")

    if any(t != d for t, d in (
        (args.threshold_prod, 30.0),
        (args.threshold_test, 15.0),
        (args.threshold_avg, 10.0),
    )):
        print(f"[crap-score] threshold override: prod={args.threshold_prod} "
              f"test={args.threshold_test} avg={args.threshold_avg}",
              file=sys.stderr)

    kinds = ["src", "test"] if args.target == "both" else [args.target]
    inventory = source_inventory(root, lang)
    partitions = {}
    all_scores: list[MethodScore] = []
    for kind in kinds:
        files = inventory[kind]
        observation = {"candidate_files": len(files), "methods_scored": 0,
                       "status": "empty", "reason": "no candidate source files"}
        partitions[kind] = observation
        if lang not in DISPATCH:
            observation.update(status="unmeasured", reason=f"unsupported language: {lang}")
            continue
        if not files:
            continue
        try:
            scores = DISPATCH[lang](root, kind, read_only=args.read_only)
            expected = {str(p.resolve()) for p in files}
            measured = set()
            for score in scores:
                path = str((root / score.path).resolve())
                if (path not in expected or score.kind != kind or not score.method
                        or type(score.complexity) is not int or score.complexity < 1
                        or not math.isfinite(score.coverage) or not 0 <= score.coverage <= 100
                        or not math.isfinite(score.crap)
                        or not math.isclose(score.crap, crap(score.complexity, score.coverage))):
                    raise MeasurementError("invalid or out-of-scope collector method")
                measured.add(path)
            observation["methods_scored"] = len(scores)
            all_scores.extend(scores)
            if not scores or measured != expected:
                raise MeasurementError("candidate files were not all measured; zero-method files remain unresolved")
            observation.update(status="measured", reason="all candidate files have method measurements")
        except (OSError, ValueError, TypeError, AttributeError, KeyError, ArithmeticError) as exc:
            observation.update(status="unmeasured", reason=str(exc))

    out_dir.mkdir(parents=True, exist_ok=True)

    if args.format in ("csv", "both"):
        for kind in kinds:
            ranked = sorted(
                [s for s in all_scores if s.kind == kind],
                key=lambda s: s.crap, reverse=True,
            )
            csv_path = out_dir / f"crap-{kind}.csv"
            with csv_path.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["rank", "crap", "complexity", "coverage_pct", "path", "method"])
                for i, s in enumerate(ranked, 1):
                    w.writerow([i, f"{s.crap:.2f}", s.complexity,
                                f"{s.coverage:.1f}", s.path, s.method])

    src_scores = [s for s in all_scores if s.kind == "src"]
    test_scores = [s for s in all_scores if s.kind == "test"]
    prod_max = max((s.crap for s in src_scores), default=0.0)
    test_max = max((s.crap for s in test_scores), default=0.0)
    prod_avg = (sum(s.crap for s in src_scores) / len(src_scores)) if src_scores else 0.0

    prod_blockers = [asdict(s) for s in src_scores if s.crap > args.threshold_prod]
    test_blockers = [asdict(s) for s in test_scores if s.crap > args.threshold_test]
    avg_fail = prod_avg > args.threshold_avg

    complete = all(p["status"] == "measured" for p in partitions.values())
    threshold_fail = bool(prod_blockers or test_blockers or avg_fail)
    pass_ = complete and not threshold_fail
    result = "FAIL" if threshold_fail else "PASS" if pass_ else "ADVISORY"

    summary = {
        "language": lang,
        "thresholds": {
            "production_max": args.threshold_prod,
            "test_max": args.threshold_test,
            "project_avg_max": args.threshold_avg,
        },
        "production": {
            "methods_scored": len(src_scores),
            "max_crap": round(prod_max, 2),
            "avg_crap": round(prod_avg, 2),
            "blockers": prod_blockers,
        },
        "test": {
            "methods_scored": len(test_scores),
            "max_crap": round(test_max, 2),
            "blockers": test_blockers,
        },
        "pass": pass_,
        "result": result,
        "partitions": partitions,
    }

    if args.format in ("json", "both"):
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    if args.json:
        side = os.environ.get("AUDIT_HARNESS_SIDE", "ci")
        # input_hash: SHA256 over all production+test source-file contents under root, sorted.
        # Use os.walk with directory pruning instead of rglob — large vendored trees
        # (node_modules, .venv, .git, build outputs) would otherwise dominate the walk
        # cost on big repos and waste IO on files we already filter out by extension.
        digest = hashlib.sha256()
        exts = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
                ".go", ".rs", ".java", ".kt", ".cs", ".php", ".rb")
        collected: list[Path] = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not is_excluded_dir(d)]
            for fn in files:
                if fn.endswith(exts):
                    collected.append(Path(dirpath) / fn)
        for fp in sorted(collected):
            digest.update(fp.read_bytes())
        input_hash = f"sha256:{digest.hexdigest()}"
        # policy_hash: SHA256 over the threshold tuple (stable, deterministic)
        policy_repr = f"prod={args.threshold_prod}|test={args.threshold_test}|avg={args.threshold_avg}".encode()
        policy_hash = f"sha256:{hashlib.sha256(policy_repr).hexdigest()}"
        envelope = {
            "gate_id": f"audit-harness:{side}:crap-score",
            "result": result,
            "input_hash": input_hash,
            "policy_hash": policy_hash,
            "metadata": {
                "language": lang,
                "thresholds": summary["thresholds"],
                "production_max_crap": summary["production"]["max_crap"],
                "production_avg_crap": summary["production"]["avg_crap"],
                "production_methods_scored": summary["production"]["methods_scored"],
                "production_blockers_count": len(prod_blockers),
                "test_max_crap": summary["test"]["max_crap"],
                "test_methods_scored": summary["test"]["methods_scored"],
                "test_blockers_count": len(test_blockers),
                "avg_fail": avg_fail,
                "requested_partitions": kinds,
                "partitions": partitions,
                "coverage_policy": "existing coverage joined where available; otherwise conservative zero",
                "indeterminate": not complete,
                "summary_path": str(out_dir / "summary.json"),
            },
        }
        if result == "FAIL":
            envelope["failure_mode"] = "crap-threshold-exceeded"
        elif result == "ADVISORY":
            envelope["advisory_severity"] = "warn" if any(
                p["status"] == "unmeasured" for p in partitions.values()) else "info"
        print(json.dumps(envelope))
    else:
        print(json.dumps({"pass": pass_, "result": result,
                          "summary_path": str(out_dir / "summary.json")}))
    return {"PASS": 0, "FAIL": 1, "ADVISORY": 2}[result]


if __name__ == "__main__":
    sys.exit(main())
