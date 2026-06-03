# AAR — Script Robustness + Portability Upstream Fixes (v1.1.1)

| Field | Value |
|---|---|
| **Doc code** | AA-AACR (After-Action / Audit-Closure Report) |
| **Date** | 2026-05-23 |
| **Author** | Jeremy Longshore |
| **Plan** | IEP Convergence Debt Plan Priority 3 (`iep-P3-audit-harness-hardening`) |
| **Bead** | `iah-script-robustness-upstream` (`bd_000-projects-qqkq`) |
| **Release** | v1.1.1 (patch) |
| **Trigger** | Gemini code review on `intent-eval-lab` PR #67 (harness-hash rollout to lab) flagged 6 medium-severity findings in vendored audit-harness scripts |

## 1. Context

`iep-harness-hash-platform-rollout` (`bd_000-projects-g6zu`) propagates the v1.1.0 self-pin mechanism across the IEP ecosystem. The first rollout (`intent-eval-lab` PR #67) vendors the audit-harness scripts snapshot at `846ff6a` into the lab repo. On 2026-05-23 Gemini's automated review of PR #67 surfaced 6 medium-severity issues — none lab-side defects, all upstream-script concerns. Fixing them at the source (audit-harness v1.1.1) before the rollout reaches the remaining 3 consumer repos (j-rig, intent-rollout-gate, kernel already pinned) avoids re-publishing buggy vendored copies that would immediately need replacement.

## 2. What changed

| # | File | Finding | Fix |
|---|---|---|---|
| 1 | `scripts/escape-scan.sh` | `--staged` + `--range` mktemp temp file leaked | `trap 'rm -f "$DIFF_SRC"' EXIT` registered immediately after each `mktemp` |
| 2 | `scripts/crap-score.py` | `go test -coverprofile=...` ran without checking if `go` is on PATH (FileNotFoundError on Go-less systems) | Wrapped in existing `which_or_none("go")` guard pattern used elsewhere in the same function |
| 3 | `scripts/crap-score.py` | `--json` input-hash `rglob("*")` walked `node_modules` / `.venv` / `.git` etc. before filtering | Replaced with `os.walk` + `dirs[:] = [...]` in-place pruning of 13 noisy directories |
| 4 | `scripts/emit-evidence.sh` | `python3 -c "...open('$PKG_JSON')..."` interpolated shell var into Python source; paths with quotes broke parse | Pass `$PKG_JSON` via `sys.argv[1]` instead |
| 5 | `scripts/bias-count.sh` | `find ... -exec sha256sum {} \;` forked one process per file | Changed `\;` → `+` to batch arguments per `find` invocation |
| 6 | `scripts/harness-hash.sh` | `sha256sum` is Linux/coreutils-only; broke on macOS | Cross-platform detection: `SHA256_CMD=(sha256sum)` else `SHA256_CMD=(shasum -a 256)`; replaced all sha256sum sites in this script with `"${SHA256_CMD[@]}"` |

Manifest bumps (per the v1.0.2 canonical-check gate):

- `package.json`, `version.txt`, `python/pyproject.toml`, `python/src/intent_audit_harness/__init__.py`, `rust/Cargo.toml` → `1.1.1`

Hash manifest regeneration:

- `.harness-hash` re-initialized via `bash scripts/harness-hash.sh --init`; 4 of 9 pinned-file hashes changed (the 4 modified scripts); 5 unchanged (`bin/audit-harness.js`, 3 unchanged scripts, `.harness-hash-extra-patterns`).

CHANGELOG: top of file gained the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) reference line that should have been present from v1.0.0 onwards. Surfaced by user feedback during this session ("please gosh make sure all the keepachangelogs in all the repos are staying up to date"). The cross-repo CHANGELOG sweep is recorded in a follow-up bead (filed alongside this AAR).

## 3. What worked

- **The self-pin mechanism actually caught the script changes.** First action after editing the scripts was `bash scripts/harness-hash.sh --verify`, which correctly reported `HARNESS_TAMPERED` with a diff of the 4 modified file hashes. The v1.1.0 self-pin mechanism (closed yesterday) is doing exactly what it advertised — silent edits would have been impossible. Validation of the prior priority's value, in production, on the next priority's first work.
- **Single-PR scope held.** Tempting to also fix the same `sha256sum` portability gap in `bias-count.sh:39` (also Linux-only) and `escape-scan.sh:192/195` (more sha256sum sites), but Gemini specifically called out `harness-hash.sh:102`. Out-of-finding fixes get their own bead (filed below). PR stays surgical.
- **No scope creep into Priority 6.** The risk-mitigation table called for landing script fixes BEFORE flipping shellcheck to hard-fail. Honored. Priority 6 Phase A1 opens as the next PR, not the same one.

## 4. What didn't work / what to watch

- **`rust/Cargo.lock` is gitignored**, so the canonical-check gate cannot detect drift in it. The v1.1.0 release left `Cargo.lock` at `1.0.2`, which was technically wrong but undetectable. Cargo regenerates it on `cargo build` so the published crate is correct. Filing a follow-up to either (a) commit `Cargo.lock` and trust the canonical-check gate or (b) add explicit guidance to `RELEASING.md`. Not a v1.1.1 blocker.
- **`sha256sum` portability is not yet universal.** This release fixes the harness-hash hot path. `escape-scan.sh` (lines 192, 195) and `bias-count.sh` (line 39 outer pipe — the inner `-exec` was the one Gemini flagged) still use bare `sha256sum`. Follow-up bead `iah-sha256-portability-completion` filed for the remaining sites.
- **CHANGELOG hygiene across IEP repos is uneven.** Per user feedback this session, scheduled a cross-repo CHANGELOG sweep as a follow-up bead. The audit-harness CHANGELOG is now the reference template — Keep-a-Changelog 1.1.0 + SemVer 2.0.0 references at top of file.

## 5. Follow-ups filed

| Bead | Scope |
|---|---|
| `iah-sha256-portability-completion` (P3) | Apply the same `SHA256_CMD` array pattern to the remaining bare `sha256sum` sites in escape-scan.sh + bias-count.sh's outer pipe. Patch release. |
| `iah-cargo-lock-tracking` (P3) | Decide whether to commit `rust/Cargo.lock` or document its untracked status in `RELEASING.md`. Closes a gap in the canonical-check gate's coverage. |
| `iep-changelog-hygiene-sweep` (P2) | Verify every IEP repo's `CHANGELOG.md` is Keep-a-Changelog 1.1.0 compliant + has an entry for every shipped tag. Cross-cutting under `iep-P3` cluster. Triggered by user feedback this session. |

## 6. Verification

- `bash scripts/harness-hash.sh --verify` → `harness-hash: OK`
- `python3 -m py_compile scripts/crap-score.py` → exit 0
- `bash -n scripts/{escape-scan,bias-count,emit-evidence,harness-hash}.sh` → exit 0
- `node bin/audit-harness.js --version` → `1.1.1`
- All 5 manifest files report `1.1.1` (locally verified via grep)
- CI on the PR exercises shellcheck (tolerant), python compile-check, version-canonical-check, self-pin verify, and the synthetic-threshold escape-scan smoke

## 7. References

- IEP Convergence Debt Plan: `~/.claude/plans/intent-eval-platform-convergence-debt-fix.md` (the master execution plan being followed)
- Triggering review: `intent-eval-lab` PR #67 (Gemini comment timestamp 2026-05-23T01:23:16Z, commit `2f6d9d3...`)
- Prior priority AAR: `000-docs/005-AA-AACR-iah-self-pin-iep-P3-2026-05-22.md`
- Parent bead: `iep-P3-audit-harness-hardening` (`bd_000-projects-t3q8`)

— end AAR —
