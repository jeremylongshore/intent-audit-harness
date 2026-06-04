# intent-audit-harness (Python)

Python-native install of the Intent Solutions deterministic test-enforcement toolkit.

Mirrors the CLI surface of the Node package
[`@intentsolutions/audit-harness`](https://www.npmjs.com/package/@intentsolutions/audit-harness)
so the command line is identical across ecosystems.

## Install

```bash
pip install intent-audit-harness
# or, inside a project venv:
python -m pip install intent-audit-harness
```

This ships a console script `audit-harness` and a module entry point
`python -m intent_audit_harness`.

## Requirements

- Python 3.8+
- `bash` available on `PATH` (Linux, macOS, or WSL)
- `python3` on `PATH` for the `crap` subcommand
- Optional per-subcommand tools: `radon` / `gocyclo` / `dependency-cruiser` / `import-linter`

## Usage

```bash
audit-harness --help
audit-harness verify
audit-harness escape-scan --staged
audit-harness crap src/
```

See the root project for the full docs:
<https://github.com/jeremylongshore/intent-audit-harness>

## What this package does

Dispatches to the same shell/python scripts shipped with the canonical npm package.
The Python wheel bundles:

- `harness-hash.sh`  — pinning / verification
- `escape-scan.sh`   — diff scanner for AI escape grammar
- `arch-check.sh`    — language-appropriate architecture checker
- `bias-count.sh`    — test-bias heuristics
- `gherkin-lint.sh`  — advisory Gherkin quality check
- `crap-score.py`    — CRAP (complexity x coverage) scorer

## License

MIT
