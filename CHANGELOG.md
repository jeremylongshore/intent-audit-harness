# Changelog

## [v0.2.0] - 2026-05-10

- docs: add release.yml — complete /repo-dress 21-file canon (c0298ef)
- docs: fill baseline OSS governance gaps via /repo-dress (closes #10) (29a8520)
- docs: Part 2 Workstream A upgrade landscape (c967f3e)
- docs(CLAUDE.md): add three-repo convergence section (b8255a3)
- infra: convergence Phase A.0 + A — bd init, GH templates, CI workflow, design notes (8f30db4)
- bd init: initialize beads issue tracking (ffc7597)
- feat: add PyPI and crates.io wrappers for audit-harness (9b97217)


All notable changes to `@intentsolutions/audit-harness` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-21

Initial release. Extracted from the `audit-tests` Claude Code skill v7.0.0 to enable in-repo enforcement without global skill installation.

### Added

- `audit-harness verify` — SHA-256 hash verification for pinned policy files
- `audit-harness init` — initialize/re-init the `.harness-hash` manifest
- `audit-harness list` — list pinned files
- `audit-harness escape-scan` — detect AI escape patterns in a diff (coverage threshold lowering, test deletion, architecture bypasses, test skip markers)
- `audit-harness arch` — dispatch language-appropriate architecture checker (dependency-cruiser / import-linter / ArchUnit / deptrac / arch-go)
- `audit-harness bias` — count common test-bias patterns
- `audit-harness gherkin-lint` — advisory Gherkin quality check
- `audit-harness crap` — CRAP (Complexity × Coverage) scorer for Python, JS/TS, Go, Rust

### Key design decisions

- **Scripts stay as shell/python.** Not a TypeScript port — battle-tested implementations, language-portable, minimal dependencies.
- **Thin Node CLI.** `bin/audit-harness.js` is a dispatcher only; all logic lives in `scripts/`.
- **Policy-driven thresholds.** `escape-scan.sh` reads floors from `tests/TESTING.md` in the target repo, not from the script source.
- **Zero runtime dependencies** beyond Node 18+, bash, and Python 3 (only if using `crap` command).
