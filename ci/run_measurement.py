#!/usr/bin/env python3
"""Collect advisory Python measurements without changing the public harness CLI.

Providers are installed separately by CI. Only Python launchers are projected
into the behavioral PATH: radon must stay invisible to the legacy golden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from measurement_baseline import source_inventory


BEHAVIOR_COMMANDS = (
    ("npm", "test"),
    ("bash", "tests/report-lineage/run-report-lineage-tests.sh"),
    ("bash", "tests/emit-evidence/run-emit-evidence-tests.sh"),
)

COMPLEXITY_PROGRAM = """
import json, pathlib, sys, tokenize
from radon.complexity import cc_visit
from radon.cli.tools import cc_to_dict
root = pathlib.Path(sys.argv[1])
inventory = json.loads(pathlib.Path(sys.argv[2]).read_text())
result = {}
for item in inventory:
    with tokenize.open(root / item['path']) as stream:
        blocks = cc_visit(stream.read())
    result[item['path']] = [cc_to_dict(block) for block in blocks
                            if not getattr(block, 'is_method', False)]
pathlib.Path(sys.argv[3]).write_text(json.dumps(result, indent=2) + '\\n')
"""

COVERAGE_PROGRAM = """
import json, pathlib, sys
import coverage
root = pathlib.Path(sys.argv[1])
inventory = json.loads(pathlib.Path(sys.argv[2]).read_text())
cov = coverage.Coverage(config_file=sys.argv[3])
cov.load()
paths = [str(root / item['path']) for item in inventory]
# touch_files adds unexecuted eligible scripts, including non-importable names.
# It does not add executed lines or invent execution evidence.
cov.get_data().touch_files(paths)
cov.save()
cov.json_report(outfile=sys.argv[4], include=paths, pretty_print=True)
"""


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def provider(python: str, module: str) -> dict:
    """Probe the exact interpreter without changing its installed environment."""
    try:
        result = subprocess.run(
            [python, "-c", f"import {module}; print({module}.__version__)"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        return {"status": "unavailable", "version": None, "exit_code": None, "reason": str(exc)}
    return {
        "status": "available" if result.returncode == 0 else "unavailable",
        "version": result.stdout.strip() if result.returncode == 0 else None,
        "exit_code": result.returncode,
        "python": python,
        "reason": result.stderr.strip() if result.returncode else None,
    }


def behavioral_environment(
    scratch: Path, python: str, provider_pythons: list[str], config: Path | None,
) -> dict[str, str]:
    """Preserve ordinary tools while hiding provider executables from lookups."""
    launchers = scratch / "python-bin"
    launchers.mkdir()
    for name in ("python", "python3", f"python{sys.version_info.major}.{sys.version_info.minor}"):
        path = launchers / name
        path.write_text(f"#!/bin/sh\nexec {shlex.quote(python)} \"$@\"\n", encoding="utf-8")
        path.chmod(0o755)
    provider_dirs = {str(Path(p).absolute().parent) for p in provider_pythons}
    paths = [p for p in os.environ.get("PATH", os.defpath).split(os.pathsep)
             if str(Path(p).absolute()) not in provider_dirs]
    env = dict(os.environ, PATH=os.pathsep.join([str(launchers), *paths]), PYTHONDONTWRITEBYTECODE="1")
    # An ambient provider would change frozen golden expectations. Do not run
    # the regression suite in that environment and mislabel its result.
    if shutil.which("radon", path=env["PATH"]):
        raise ValueError("radon remains on behavioral PATH; use a provider-free parent PATH")
    env.pop("COVERAGE_PROCESS_START", None)
    env.pop("COVERAGE_FILE", None)
    if config:
        startup = scratch / "startup"
        startup.mkdir()
        (startup / "sitecustomize.py").write_text(
            "import coverage\ncoverage.process_startup()\n", encoding="utf-8",
        )
        previous = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(startup) + (os.pathsep + previous if previous else "")
        env["COVERAGE_PROCESS_START"] = str(config)
    return env


def run_command(argv: list[str], root: Path, env: dict[str, str], log: Path) -> dict:
    with log.open("w", encoding="utf-8") as stream:
        try:
            result = subprocess.run(argv, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
            code = result.returncode
        except OSError as exc:
            stream.write(str(exc) + "\n")
            code = 127
    return {"argv": argv, "exit_code": code, "log": log.name}


def git_value(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def collect(root: Path, output: Path, coverage_python: str, complexity_python: str) -> int:
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty to prevent stale measurement artifacts")
    output.mkdir(parents=True, exist_ok=True)
    sources = source_inventory(root)
    inventory = output / "source-files.json"
    write_json(inventory, sources)
    providers = {"coverage": provider(coverage_python, "coverage"), "radon": provider(complexity_python, "radon")}
    provenance = {
        "schema_version": "audit-harness-self-measurement-input/v1",
        "commit_sha": git_value(root, "rev-parse", "HEAD"),
        "source_root": str(root),
        "source_mapping": "direct working-tree paths; no temporary-copy coverage remapped",
        "collection": {
            "mode": "direct-working-tree",
            "source_root": str(root),
            "identity": "HEAD identifies the base; source_files hashes identify exact measured working-tree bytes",
            "path_mapping": "identity; temporary or packaged copies are not remapped",
        },
        "git_status_before": git_value(root, "status", "--porcelain", "--untracked-files=all"),
        "source_files": sources,
        "providers": providers,
        "commands": [],
        "limitations": [
            "Only canonical scripts/*.py and eligible tests/**/*.py are measured; not whole-repository coverage.",
            "Temporary copies, packaged mirrors, fixtures, shell, Node, Rust and CI code are outside this denominator.",
            "Python children need inherited PYTHONPATH and site startup; -I/-S, replaced environments or other "
            "interpreters can escape instrumentation. Unobserved paths remain uncovered.",
            "File line coverage is a function CRAP proxy; no mutation provider or blocking thresholds are installed.",
            "Aggregate and supplemental results are recorded separately; counters are not summed as test counts.",
        ],
    }
    failed_behavior = False
    with tempfile.TemporaryDirectory(prefix="audit-measurement-") as temp:
        scratch = Path(temp)
        data = output / "coverage-data"
        data.mkdir()
        config = output / "coverage.ini"
        config.write_text(
            "[run]\nbranch = true\nparallel = true\nsigterm = true\ndisable_warnings = no-data-collected\n"
            f"data_file = {data / '.coverage'}\ninclude =\n"
            + "".join(f"    {root / item['path']}\n" for item in sources), encoding="utf-8",
        )
        coverage_ready = providers["coverage"]["status"] == "available"
        # Failure to install measurement tooling does not suppress behavioral
        # commands. They use the ordinary interpreter and report actual exits.
        behavior_python = coverage_python if coverage_ready else sys.executable
        try:
            env = behavioral_environment(
                scratch, behavior_python, [coverage_python, complexity_python], config if coverage_ready else None,
            )
        except ValueError as exc:
            provenance["limitations"].append(str(exc))
            failed_behavior = True
            for argv in BEHAVIOR_COMMANDS:
                provenance["commands"].append({"argv": list(argv), "exit_code": None, "reason": str(exc)})
        else:
            provenance["behavioral_radon_executable"] = shutil.which("radon", path=env["PATH"])
            for index, argv in enumerate(BEHAVIOR_COMMANDS):
                record = run_command(list(argv), root, env, output / f"behavior-{index + 1}.log")
                provenance["commands"].append(record)
                failed_behavior |= record["exit_code"] != 0
        # Provider commands do not inherit child-process instrumentation.
        clean_env = dict(os.environ)
        clean_env.pop("COVERAGE_PROCESS_START", None)
        clean_env.pop("COVERAGE_FILE", None)
        if coverage_ready:
            combine = run_command(
                [coverage_python, "-m", "coverage", "combine", f"--rcfile={config}", "--keep", str(data)],
                root, clean_env, output / "coverage-combine.log",
            )
            provenance["commands"].append(combine)
            if combine["exit_code"] == 0:
                coverage_result = run_command(
                    [coverage_python, "-c", COVERAGE_PROGRAM, str(root), str(inventory), str(config),
                     str(output / "coverage.json")], root, clean_env, output / "coverage-report.log",
                )
                provenance["commands"].append(coverage_result)
            else:
                coverage_result = combine
            providers["coverage"]["exit_code"] = coverage_result["exit_code"]
            if coverage_result["exit_code"]:
                providers["coverage"]["status"] = "failed"
        if providers["radon"]["status"] == "available":
            result = run_command(
                [complexity_python, "-c", COMPLEXITY_PROGRAM, str(root), str(inventory),
                 str(output / "complexity.json")], root, clean_env, output / "complexity.log",
            )
            provenance["commands"].append(result)
            providers["radon"]["exit_code"] = result["exit_code"]
            if result["exit_code"]:
                providers["radon"]["status"] = "failed"
    provenance["source_unchanged_after_commands"] = source_inventory(root) == sources
    if not provenance["source_unchanged_after_commands"]:
        provenance["limitations"].append("Eligible source changed during collection; measurements are invalid.")
    provenance["git_status_after"] = git_value(root, "status", "--porcelain", "--untracked-files=all")
    provenance["artifacts"] = {}
    for name in ("coverage.json", "complexity.json"):
        artifact = output / name
        if not artifact.exists():
            write_json(artifact, None)
        provenance["artifacts"][name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    write_json(output / "provenance.json", provenance)
    report = run_command(
        [sys.executable, str(Path(__file__).with_name("measurement_baseline.py")), "--root", str(root),
         "--provenance", str(output / "provenance.json"), "--coverage", str(output / "coverage.json"),
         "--complexity", str(output / "complexity.json"), "--output-dir", str(output)],
        root, dict(os.environ), output / "adapter.log",
    )
    if report["exit_code"]:
        return report["exit_code"]
    if not provenance["source_unchanged_after_commands"]:
        return 2
    return 1 if failed_behavior else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--coverage-python", required=True)
    parser.add_argument("--complexity-python", required=True)
    args = parser.parse_args()
    try:
        return collect(args.root.resolve(), args.output_dir.resolve(),
                       str(Path(args.coverage_python).absolute()), str(Path(args.complexity_python).absolute()))
    except (OSError, ValueError) as exc:
        print(f"measurement runner: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
