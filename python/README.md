# intent-audit-harness (Python)

The PyPI distribution is frozen at `1.4.0`; use the canonical npm package
[`@intentsolutions/audit-harness`](https://www.npmjs.com/package/@intentsolutions/audit-harness)
or the root project's `install.sh` for new rollouts, including Python projects.

This wrapper exposes `verify`, `init`, `list`, `escape-scan`, `arch`, `bias`,
`gherkin-lint`, and `crap`. It does not expose `classify` or `conform`, or bundle
their registry and conformance schemas. Source-tree version alignment does not
mean a new wheel was published. See the [distribution contract](../000-docs/015-AT-DECR-classify-conform-distribution-contract-2026-11-12.md).

## Existing frozen installation

```bash
pip install intent-audit-harness==1.4.0
# or, inside a project venv:
python -m pip install intent-audit-harness==1.4.0
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

Dispatches to the shell/Python scripts bundled in that wheel; these are not
automatically updated from the current npm package.
The Python wheel bundles:

- `harness-hash.sh`  — pinning / verification
- `escape-scan.sh`   — diff scanner for AI escape grammar
- `arch-check.sh`    — language-appropriate architecture checker
- `bias-count.sh`    — test-bias heuristics
- `gherkin-lint.sh`  — advisory Gherkin quality check
- `crap-score.py`    — CRAP (complexity x coverage) scorer

## License

MIT
