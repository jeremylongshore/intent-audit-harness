# audit-harness Self-Pin — IEP Convergence Debt Plan Priority 3 next cut

**Filing**: 005-AA-AACR-iah-self-pin-iep-P3-2026-05-22.md
**Date**: 2026-05-22
**Author**: Jeremy Longshore (CTO + beads work; executed by Claude per CEO-mode delegation)
**Bead closed (pending PR merge)**: `iah-self-pin` (`bd_000-projects-itpl`, P1) — initialize `.harness-hash` against audit-harness's own policy files; flip CI from tolerant-exit-3 to hard fail
**Cluster**: IEP Convergence Debt Plan Priority 3 (`iep-P3-audit-harness-hardening`, `bd_000-projects-t3q8`)
**Unblocks**: `iep-harness-hash-platform-rollout` (`bd_000-projects-g6zu`, P2) — the 4 currently-uninitialized IEP repos (lab + j-rig + rollout-gate; kernel already pinned) can now adopt the same pattern

---

## 1. What this AAR records

The 2026-05-21 testing+CI/CD review surfaced that `.harness-hash` self-pinning was active on **1/5** IEP repos (only `intent-eval-core`). The audit-harness CI workflow itself ran with `|| true` tolerance on `audit-harness list` + `harness-hash --verify` because no `.harness-hash` manifest could be produced — the default harness-hash patterns target consumer-repo artifacts (`.feature` files, architecture rule configs, coverage threshold configs), none of which exist in audit-harness's own tree because audit-harness **IS** the policy enforcer.

Per `audit-harness/CLAUDE.md` design rule 5: "The harness tests itself." That rule was aspirational until this release.

## 2. What changed

| File | Change |
|---|---|
| `scripts/harness-hash.sh` | **NEW capability**: reads an optional `.harness-hash-extra-patterns` file at the repo root and appends its lines to the default `PATTERNS` array. Comments (`#`) + blank lines stripped. Backward-compatible — consumer repos without the file get exactly the previous behavior. |
| `.harness-hash-extra-patterns` (NEW, repo root) | Pins `scripts/*.sh`, `scripts/*.py`, `bin/audit-harness.js`, and the extras file itself (preventing silent edits to the self-pinning scope). |
| `.harness-hash` (NEW, repo root) | 9-file manifest produced by `bash scripts/harness-hash.sh --init`. Committed to main. |
| `.gitignore` | **REMOVED** the `.harness-hash` line. The manifest is now intentionally tracked. Pre-existing gitignore entry was load-bearing-wrong: if the manifest weren't committed, CI's `--verify` would compare against a locally-regenerated manifest (no integrity guarantee) or fail exit-3 (no manifest). Replaced the line with an inline comment block explaining the intent. |
| `.github/workflows/ci.yml` | `audit-harness list` + `harness-hash --verify` self-check steps drop `\|\| true` suffixes. Comment block updated to reference this AAR. Hard-fail in place. |
| `package.json` + `version.txt` + `python/pyproject.toml` + `python/src/intent_audit_harness/__init__.py` + `rust/Cargo.toml` | Version bumped `1.0.2` → `1.1.0` across all 5 manifests. Minor bump per SemVer — additive feature surface. The version-canonical-check CI gate (landed in v1.0.2, PR #35) enforces this. |
| `CHANGELOG.md` | `[v1.1.0] - 2026-05-22` entry with full rationale. |
| THIS AAR | Closeout. |

## 3. Why minor not patch

The `.harness-hash-extra-patterns` mechanism is a new authored feature surface. Repos that opt in get a new capability (additional pin patterns beyond the canonical defaults). Per SemVer:

- **Adding** new capability without removing or breaking existing behavior → minor bump.
- Repos that don't create `.harness-hash-extra-patterns` get exactly the previous behavior (the file-existence check no-ops gracefully).
- audit-harness is the **first adopter** of the mechanism — the dogfood.

Patch would have understated the change. Major would have overstated it (no breaking change for any consumer).

## 4. Why it matters (the silent-tamper failure mode)

Before v1.1.0, audit-harness CI's self-check looked like:

```yaml
- name: audit-harness list (self-check enumeration)
  run: node bin/audit-harness.js list || true
- name: harness-hash --verify
  run: bash scripts/harness-hash.sh --verify || true
```

A silent edit to `scripts/escape-scan.sh` — the gate that REFUSES threshold-lowering changes — would pass CI. The harness could not enforce its own policy. That was the failure mode design rule 5 ("the harness tests itself") existed to prevent and didn't.

After v1.1.0:

- The 9 policy files (scripts/arch-check.sh, scripts/bias-count.sh, scripts/crap-score.py, scripts/emit-evidence.sh, scripts/escape-scan.sh, scripts/gherkin-lint.sh, scripts/harness-hash.sh, bin/audit-harness.js, .harness-hash-extra-patterns) are SHA-256 pinned at the repo root.
- Any byte change to any of those files without a fresh `bash scripts/harness-hash.sh --init` + commit of the regenerated `.harness-hash` causes `--verify` to exit 2 (HARNESS_TAMPERED).
- The CI step now hard-fails on exit-2. The PR is blocked.

The discipline is now structural, not advisory.

## 5. Bootstrap note (pinning the pinning surface)

A subtle concern: `.harness-hash-extra-patterns` declares which files to pin, and `scripts/harness-hash.sh` is the code that reads that declaration. Both files MUST themselves be pinned, otherwise a silent edit to either could subvert the entire mechanism:

- An edit to `.harness-hash-extra-patterns` could remove `scripts/*.sh` from the pin list, then a follow-up edit to `scripts/escape-scan.sh` would not be caught.
- An edit to `scripts/harness-hash.sh` could silently ignore the extras file or skip certain patterns.

Both files are now in the pin list:

- `scripts/harness-hash.sh` matches `scripts/*.sh` in the extras file.
- `.harness-hash-extra-patterns` is explicitly pinned by the literal pattern `.harness-hash-extra-patterns` in the extras file.

Bootstrap order matters: the `--init` that produced the committed `.harness-hash` ran AFTER both files were written, so both files' current bytes are the locked baseline. Any subsequent edit to either requires a fresh `--init`.

## 6. Out-of-scope (deferred to follow-up beads)

| Concern | Bead | Why deferred |
|---|---|---|
| Roll out the same pattern to `intent-eval-lab` (pin partner-name-guard.yml + validate workflow + schema-drift.yml + DRs + Blueprint docs) | `iep-harness-hash-platform-rollout` (`bd_000-projects-g6zu`) per-repo child | This AAR closes the audit-harness side; the platform-rollout coordinator is now unblocked |
| Roll out to `j-rig-binary-eval` (pin vendored .audit-harness/ wrapper + tests/TESTING.md) | Same | Same |
| Roll out to `intent-rollout-gate` | Same | DEFERRED until M5 MVP lands (no policy files yet to pin) |
| Roll out to `intent-eval-core` extension (currently only `.dependency-cruiser.cjs` pinned via the default patterns; could add Decision Records + Blueprint docs) | Could file as `iec-harness-hash-extras` | Optional follow-up; kernel already has the discipline at minimum scope |
| Audit-harness's regression-suite schema URL — currently pulls from intent-eval-lab redirect stub | `iah-regression-schema-url-kernel` (`bd_000-projects-1g2v`) | Separate bead, separate PR |
| Audit-harness sigstore on publish | `iah-sigstore` (`bd_000-projects-t0ba`) | Separate P3 sub-bead, needs release.yml restoration |

## 7. Verification

- Local `bash scripts/harness-hash.sh --init`: pins 9 files cleanly.
- Local `bash scripts/harness-hash.sh --verify`: `harness-hash: OK`.
- Local `node bin/audit-harness.js list`: enumerates all 9 pinned files; exit 0.
- Local version-canonical-check dry-run: all 5 manifests at `1.1.0`, license `Apache-2.0` across the polyglot wrappers.
- `bash scripts/escape-scan.sh --staged` (CLAUDE.md design rule 5): expected REFUSE=0 CHALLENGE=0 FLAG=0 — to be verified after staging.

## 8. References

- IEP Convergence Debt Plan Priority 3 — `iep-P3-audit-harness-hardening` (`bd_000-projects-t3q8`)
- Audit-harness self-pin bead — `iah-self-pin` (`bd_000-projects-itpl`)
- Platform-rollout coordinator — `iep-harness-hash-platform-rollout` (`bd_000-projects-g6zu`)
- 2026-05-21 testing+CI/CD review (gap recheck) — `iep-recheck-harness-hash-status` (`bd_000-projects-74m8`, CLOSED)
- audit-harness/CLAUDE.md design rule 5 — "The harness tests itself"
- v1.0.2 release (PR #35) — version-canonical-check CI gate; precondition for this version bump

— Jeremy Longshore
intentsolutions.io
