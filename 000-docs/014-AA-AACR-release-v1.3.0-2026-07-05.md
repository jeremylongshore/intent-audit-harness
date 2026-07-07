# Release Report: @intentsolutions/audit-harness v1.3.0

## Executive Summary

- **Version:** 1.2.3 → **1.3.0**
- **Release date:** 2026-07-05
- **Type:** MINOR (new CLI command)
- **Trigger:** `/release` ceremony (cluster-wide pass)
- **Result:** ✅ Published to all three registries

## What shipped

- **`audit-harness migration-notes` subcommand** (iah-E05d) — the adopter-facing
  migration-notes generator (the 4th and final AC of the `iah-E05` SemVer
  regression epic). Stdlib-Python, read-only, no network; turns
  `CHANGELOG.md` + `SEMVER.md` into a single migration document. `--json` emits a
  `migration-notes/v1` envelope. Wired to a dedicated 12-assertion CI suite
  (`tests/migration-notes/`). A new CLI command → MINOR bump per the repo's
  versioning policy.

The deferred OTel v2.1 event-name polish (iah-E07b/c) stays in `[Unreleased]`.

## Version bump (polyglot lockstep)

Bumped to 1.3.0 across all canonical manifests, verified aligned by the
`version-canonical-check` gate logic:

| Manifest | 1.2.3 → 1.3.0 |
|---|---|
| `package.json` (canonical) | ✓ |
| `version.txt` | ✓ |
| `python/pyproject.toml` | ✓ |
| `python/src/intent_audit_harness/__init__.py` | ✓ |
| `rust/Cargo.toml` | ✓ |

(`rust/Cargo.lock` is gitignored/untracked — CI regenerates it at `cargo package`;
the stale local `1.1.5` value was a no-op for git and is irrelevant to the publish.)

## Verification

| Registry / artifact | Result |
|---|---|
| npm `@intentsolutions/audit-harness` | **1.3.0** (dist-tag latest), Sigstore provenance |
| PyPI `intent-audit-harness` | **1.3.0**, sigstore-python keyless signature |
| crates.io `intent-audit-harness` | **1.3.0**, cargo attest-build-provenance |
| GitHub Release | `v1.3.0` created (`--generate-notes --latest`) |
| Release workflow | all publish jobs `success` |
| Pre-commit | escape-scan `REFUSE=0 CHALLENGE=0 FLAG=0`; harness-hash `OK` |
| CHANGELOG/SemVer gate | dated `## [1.3.0]` header + `### Added` + bullet; `1.3.0 > 1.2.3` |

## Rollback

```bash
git push origin --delete v1.3.0
git tag -d v1.3.0
gh release delete v1.3.0 --yes
# npm/PyPI/crates publishes are immutable — a bad release is superseded by 1.3.1,
# never unpublished. (npm deprecate / yank if genuinely broken.)
```
