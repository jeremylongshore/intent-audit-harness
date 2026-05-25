"""CLI dispatcher — thin wrapper that shells out to the bundled scripts.

Mirrors the command surface of ``@intentsolutions/audit-harness``:

    verify | init | list | escape-scan | arch | bias | gherkin-lint | crap

The scripts are shipped inside the wheel as package data; we resolve their
filesystem path via ``importlib.resources`` and invoke ``bash``/``python3``.
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Iterable

from . import __version__

COMMANDS: dict[str, tuple[str, list[str]]] = {
    "verify":       ("harness-hash.sh",  ["--verify"]),
    "init":         ("harness-hash.sh",  ["--init"]),
    "list":         ("harness-hash.sh",  ["--list"]),
    "escape-scan":  ("escape-scan.sh",   []),
    "arch":         ("arch-check.sh",    []),
    "bias":         ("bias-count.sh",    []),
    "gherkin-lint": ("gherkin-lint.sh",  []),
    "crap":         ("crap-score.py",    []),
}

USAGE = """audit-harness — deterministic test-enforcement toolkit (Python)

Usage:
  audit-harness <command> [args...]

Commands:
  verify                   Verify hash-pinned artifacts (exit 2 = HARNESS_TAMPERED)
  init                     Initialize or re-init the .harness-hash manifest
  list                     List currently pinned files
  escape-scan <source>     Scan a diff for escape attempts
                           source: --staged | --range A..B | - (stdin) | path.patch
  arch                     Run architecture-rule checks (Wall 7)
  bias                     Count test-bias patterns (tautology, smoke-only, etc.)
  gherkin-lint             Advisory Gherkin quality check
  crap [args...]           CRAP complexity x coverage scorer (multi-language)

Options:
  --version, -v            Print version
  --help, -h               Print this help

Exit codes (escape-scan):
  0 = clean
  1 = CHALLENGE (engineer-approved comment required)
  2 = REFUSE (pipeline halted)
"""


def _script_path(name: str) -> Path:
    """Return the on-disk path of a bundled script, ensuring it's executable."""
    # importlib.resources.files -> Traversable; .joinpath returns a Path-like
    # When installed from a wheel, this resolves to the extracted scripts/ dir.
    pkg_scripts = resources.files("intent_audit_harness").joinpath("scripts")
    path = Path(str(pkg_scripts.joinpath(name)))
    if not path.exists():
        print(f"audit-harness: script not found at {path}", file=sys.stderr)
        sys.exit(2)
    # Ensure executable bit for shell scripts (wheels don't always preserve it)
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass  # best-effort; we always invoke via explicit interpreter anyway
    return path


def _interpreter_for(script: str) -> str:
    return "python3" if script.endswith(".py") else "bash"


def _dispatch(cmd: str, extra_args: Iterable[str]) -> int:
    script, default_args = COMMANDS[cmd]
    script_path = _script_path(script)
    interpreter = _interpreter_for(script)

    if shutil.which(interpreter) is None:
        print(
            f"audit-harness: required interpreter '{interpreter}' not found on PATH",
            file=sys.stderr,
        )
        return 2

    argv = [interpreter, str(script_path), *default_args, *extra_args]
    try:
        completed = subprocess.run(argv, check=False)
    except OSError as exc:
        print(f"audit-harness: failed to spawn {interpreter}: {exc}", file=sys.stderr)
        return 2
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    if not args or args[0] in ("--help", "-h"):
        print(USAGE)
        return 0

    if args[0] in ("--version", "-v"):
        print(__version__)
        return 0

    cmd, rest = args[0], args[1:]
    if cmd not in COMMANDS:
        print(f"audit-harness: unknown command '{cmd}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    rc = _dispatch(cmd, rest)
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
