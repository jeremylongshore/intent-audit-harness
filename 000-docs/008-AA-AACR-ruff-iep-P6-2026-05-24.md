# AAR — Ruff CI Gate (v1.1.3, P6 Phase A2)

| Field | Value |
|---|---|
| **Doc code** | AA-AACR (After-Action / Audit-Closure Report) |
| **Date** | 2026-05-24 |
| **Author** | Jeremy Longshore |
| **Plan** | IEP Convergence Debt Plan Priority 6 Phase A2 (`iep-P6-linter-rollout`) |
| **Bead** | `iah-ruff` (`bd_000-projects-x9bs`) |
| **Release** | v1.1.3 (patch) |

## 1. Context

P6 Phase A2 follows the same Phase A1 model: add a hard-fail lint gate to audit-harness CI, fix any findings the gate surfaces (or grandfather with documented justification), bump version. Phase A1 (shellcheck, v1.1.2, PR #38) shipped earlier today. This adds ruff for Python.

## 2. Reconnaissance findings

Pre-claim ruff run against own-code Python (`scripts/crap-score.py` + `python/src/intent_audit_harness/*.py`) surfaced 5 findings — plus 2 more after adding bundled-content exclusions plus 4 line-length findings after first config attempt. Final scope: **3 dead-code findings + 1 long-line fix.**

| File:Line | Code | Verdict |
|---|---|---|
| `scripts/crap-score.py:20` (originally flagged) | F401 — `import os` unused at module level | False positive caused by shadowing local re-import inside `if args.json:` block (line 385: `import hashlib, os`). Module-level `os` IS used by that same block once shadow removed. Fix: remove `, os` from local import. |
| `scripts/crap-score.py:266` | F841 — `metrics = rec.get(...).get("cyclomatic", {})` assigned but never read | Real dead code. The actual cyclomatic value is fetched freshly inside the loop on line 268. Delete the assignment. |
| `python/src/intent_audit_harness/cli.py:12` | F401 — `import os` unused | Real dead code. Zero `os.*` usages in the file. Delete. |
| `scripts/crap-score.py:84` | E501 — `ignore` set literal at 155 chars | Genuinely too long (>>120). Reformat to multi-line set. |

3 additional E501 findings (104-112 chars on lines 205, 391, 404) eliminated by setting `line-length = 120` (modern Python default, above PEP 8's 79). The 4-line ignore set on line 84 was reformatted because it was genuinely long even at 120.

## 3. What changed

| File | Change |
|---|---|
| `scripts/crap-score.py` | (1) Removed `, os` from local re-import on line 385; (2) Removed dead `metrics = ...` assignment on line 266; (3) Reformatted long `ignore` set on line 84 into multi-line shape. |
| `python/src/intent_audit_harness/cli.py` | Removed dead `import os` on line 12. |
| `ruff.toml` (NEW, repo root) | Lint config: `select = ["E", "F"]`, `line-length = 120`, `target-version = "py38"`, excludes `python/.venv/` + 2 bundled-content script mirrors. |
| `.github/workflows/ci.yml` | New `ruff` CI job: pinned `ruff==0.15.4` via pip install, prints `ruff --version` for audit trail, runs `ruff check` (hard-fail). |
| 5 manifests | All bumped 1.1.2 → 1.1.3 per canonical-check gate. |
| `CHANGELOG.md` | New v1.1.3 entry per Keep-a-Changelog 1.1.0 format. |
| `.harness-hash` | Regenerated via `--init`. 1 of 9 pinned-file hashes changes (`scripts/crap-score.py`). |

## 4. Bundled-content discovery + follow-up bead

While running ruff, surfaced that `python/src/intent_audit_harness/scripts/crap-score.py` and `rust/scripts/crap-score.py` are **stale mirrors** of the canonical `scripts/crap-score.py` (~1 month behind; missing the v1.1.1 `--json` envelope emission, `which_or_none("go")` PATH guard, rglob-walk pruning). The Python wrapper distributed via PyPI bundles a stale `crap-score.py` — users `pip install intent-audit-harness && audit-harness crap` would get the older script.

Filed `iah-python-wrapper-scripts-sync` as separate follow-up bead. Either (a) build-time copy in Python/Rust wrapper packaging, (b) symlink, or (c) hand-sync discipline with CI check. Currently excluded from ruff scope; exclusion drops once the sync mechanism ships.

This is exactly the kind of latent issue a lint-gate rollout surfaces — the reconnaissance discipline (Phase A1 + A2) finds problems beyond the immediate scope. Logged for follow-up; not in this PR.

## 4a. Gemini PR #39 review — 2 substantive findings, both adopted verbatim

Gemini surfaced two code-quality findings on the initial push; both were addressed in a fix-up commit before merge:

1. **Add `B` (flake8-bugbear) to the ruleset.** Initial config used `select = ["E", "F"]` per bead spec. Gemini noted bugbear catches Python-specific bugs (mutable default args, unreliable exception handling) and recommended adopting from the outset. Empirical check via `ruff check --select B,E,F` confirmed zero new findings on our codebase. Adopted: `select = ["B", "E", "F"]`. The ratchet-later principle still applies for I (import order), UP (pyupgrade), etc.

2. **Move local `import hashlib` to module-level (PEP 8 alignment).** The initial fix removed `, os` from the local `import hashlib, os` re-import to eliminate the shadow, but kept `import hashlib` local with a band-aid comment ("# local; os is module-level"). Gemini correctly noted PEP 8 prefers all imports at module top; the comment was a workaround marker for a fix that should have been done properly. Adopted: moved `hashlib` to module-level imports alongside the other stdlib imports; removed the local re-import + the comment entirely.

Both fixes preserve correctness (verified via re-run `ruff check` → All checks passed; `python3 -m py_compile` → exit 0) and produce cleaner code than the initial commit. This is the third Gemini-surfaced quality fix in three consecutive audit-harness PRs this week (#37 bias-count extension alignment, #38 awk subprocess counter bug, #39 bugbear + PEP-8 imports) — the review loop is producing consistent value.

## 5. What worked

- **Reconnaissance-before-claim caught the bundled-content sprawl** — would have been very noisy CI failures if I'd just enabled ruff with default scope.
- **Pinned ruff version (0.15.4)** + `ruff --version` printed in CI step — directly applies the iah-shellcheck-version-pin lesson surfaced in Phase A1's AAR (deferred to its own bead but the principle applied here proactively).
- **Shadow-import discovery** — the `import os` at module top wasn't truly unused; ruff was confused by a redundant local `import hashlib, os`. Fixing the local import (drop `, os`) was the right answer, not deleting the module-level import.
- **No grandfathering needed** — all findings either fixed cleanly or eliminated by the 120-char line-length choice. Codebase is actually clean against E + F.

## 6. What didn't work / what to watch

- **Bundled-content mirrors** are a real architectural issue (stale-by-design unless build-time sync added). Tracked via follow-up bead; will need careful handling when iah-python-wrapper-scripts-sync ships (re-vendor pattern again).
- **Line-length 120 is a project style choice** — if a future contributor wants 100 (Black default) we'd need to refactor a few lines. Not pressing; 120 is widely accepted.
- **`__main__.py` and `__init__.py` of the wrapper are tiny** — could ratchet up the ruleset (add `I` for import order, `UP` for pyupgrade, `B` for bugbear) without major refactor. Deferred to a future "ruff ratchet" bead.

## 7. Verification

- `ruff check` → `All checks passed!` on clean checkout
- `python3 -m py_compile scripts/crap-score.py` → exit 0
- `python3 -m py_compile python/src/intent_audit_harness/cli.py` → exit 0
- `shellcheck scripts/*.sh` → exit 0 (no Phase A1 regression)
- `bash scripts/harness-hash.sh --verify` → OK after `--init`
- All 5 manifests grep-verified at `1.1.3`
- CI ruff job will hard-fail on any future PR introducing F401/F841/E*/etc.

## 8. References

- IEP Convergence Debt Plan § Priority 6 Phase A2
- Phase A1 AAR: `000-docs/007-AA-AACR-shellcheck-hard-fail-iep-P6-2026-05-24.md`
- Bead: `bd_000-projects-x9bs` `iah-ruff`
- Parent umbrella: `bd_000-projects-wdfd` `iep-P6-linter-rollout`
- Follow-up bead surfaced: `iah-python-wrapper-scripts-sync` (filed alongside this commit)
- Related: `iah-shellcheck-version-pin` (proactively applied here for ruff via pinned 0.15.4)

— end AAR —
