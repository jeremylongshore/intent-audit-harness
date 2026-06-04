# intent-audit-harness (Rust)

Rust-native install of the Intent Solutions deterministic test-enforcement toolkit.

Mirrors the CLI surface of the Node package
[`@intentsolutions/audit-harness`](https://www.npmjs.com/package/@intentsolutions/audit-harness)
and the Python package `intent-audit-harness` so the command line is identical across
ecosystems.

## Install

```bash
cargo install intent-audit-harness
```

This installs a single binary, `audit-harness`, into `$CARGO_HOME/bin` (usually
`~/.cargo/bin/audit-harness`).

## Requirements

- `cargo` / `rustc` 1.70+ to install.
- `bash` and `python3` on `PATH` at runtime (the binary dispatches to bundled shell
  and Python scripts).
- Optional per-subcommand tools: `radon` / `gocyclo` / `dependency-cruiser` /
  `import-linter`.

## How it works

The shell and Python scripts are embedded into the binary at compile time via
`include_bytes!`. On first invocation they're extracted to
`$XDG_CACHE_HOME/audit-harness/<version>/scripts/` (falling back to
`~/.cache/audit-harness/<version>/scripts/`) and invoked via `bash` or `python3`.

The cache is version-scoped, so upgrading the binary naturally picks up the new
scripts. Delete the cache dir to force re-extraction.

## Usage

```bash
audit-harness --help
audit-harness verify
audit-harness escape-scan --staged
audit-harness crap src/
```

See the root project for the full docs:
<https://github.com/jeremylongshore/intent-audit-harness>

## License

MIT
