# Changelog

## [v0.3.0] - 2026-05-12

### Added — Evidence Bundle emission (Milestone 2 of the build journey)

- `--json` flag on every gate (`escape-scan`, `harness-hash --verify`, `arch`, `bias`,
  `gherkin-lint`, `crap`). Emits a machine-readable gate-result envelope to stdout while
  preserving the existing human-readable text on stderr. Exit codes unchanged.
- `emit-evidence` subcommand. Reads a gate-result envelope from stdin (or `--input`),
  augments it with `timestamp`, `runner`, `commit_sha`, and emits a complete
  [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
  with `predicateType` `https://evals.intentsolutions.io/gate-result/v1` per
  [`evidence-bundle/v0.1.0-draft/SPEC.md`](https://github.com/jeremylongshore/intent-eval-lab/blob/main/specs/evidence-bundle/v0.1.0-draft/SPEC.md).
  Optional `--sign` (cosign keyless or `--key`), `--rekor-url` for transparency-log push.
  OTel `agent.rollout.gate.evaluated` event when `AUDIT_HARNESS_OTEL=1` or
  `OTEL_EXPORTER_OTLP_ENDPOINT` set (best-effort no-op otherwise).
- `SEMVER.md` — explicit SemVer commitment doc covering exit codes, stream contracts,
  and the predicate URI freeze.
- `tests/regression/run-regression.sh` — backward-compat regression suite. 11 checks
  across text-mode parity, `--json` stream separation, schema validation, and the
  `emit-evidence` pipeline.
- CI: `regression` job in `.github/workflows/ci.yml` runs the regression suite on every PR.

### Changed

- `bin/audit-harness.js` dispatcher exposes the new `emit-evidence` subcommand.
- `scripts/arch-check.sh` `--json` output reshaped to the gate-result envelope shape
  (the prior single-line `{"tool","status","violations","log"}` was internal — no
  documented adopter parsed it).

### Notes

- **No breaking changes.** Pre-v0.3.0 callers see identical text-mode output and exit
  codes. The `--json` flag is purely additive.
- **CISO gate (per ISEDC v1 Q1, 2026-05-10):** pushing a signed Statement to Rekor
  against `evals.intentsolutions.io/gate-result/v1` is BLOCKED until DNSSEC + CAA
  records are verified on the namespace. The script supports unsigned envelope
  emission until that gate clears (tracked in `intent-eval-lab/.beads/` as `iel-4zr`).
- **Plan reference:** `~/.claude/plans/se-the-council-bubbly-frog.md` Milestone 2.

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
