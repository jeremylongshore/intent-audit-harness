# AAR — v1.1.4 Cleanup Bundle (4 deferred upstream fixes)

| Field | Value |
|---|---|
| **Doc code** | AA-AACR (After-Action / Audit-Closure Report) |
| **Date** | 2026-05-25 |
| **Author** | Jeremy Longshore |
| **Plan** | IEP Convergence Debt Plan Priority 3 (audit-harness hardening) + Priority 6 follow-ups |
| **Beads closed** | `iah-gherkin-prev-blank-noise` (o9q1), `iah-gherkin-single-awk-opt` (vawm), `iah-crap-score-exclusion-dedup` (niv8), `iah-shellcheck-version-pin` (v1ds) |
| **Release** | v1.1.4 (patch) |

## 1. Context

Over the past week the IEP Convergence Debt Plan execution chain produced 4 audit-harness PRs (#37 v1.1.1, #38 v1.1.2, #39 v1.1.3) plus 3 lab re-vendor PRs (#67, #70, #71). Each Gemini review on those PRs surfaced 1-2 substantive findings. Per vendor-discipline (no patches in vendored copies), those findings were filed as upstream beads for batch fix.

This v1.1.4 bundle addresses 4 deferred items in one focused release. Pure cleanup — no new features, no API change.

## 2. What changed

### 2.1 `scripts/gherkin-lint.sh` — `prev_blank` print-every-line noise (o9q1, Gemini #71)

Pre-fix state: the third awk block (And-at-scenario-start checker) opened with a bare `prev_blank = 1` expression at the top of the awk script. Awk interprets bare top-level expressions as patterns; the expression evaluates to `1` (truthy) on every line; a pattern without an explicit action gets awk's default `{ print }` action; result was every line of every feature file printed to stdout alongside the intentional ERROR printf.

Verified `prev_blank` had ZERO USES anywhere in the awk script (via `grep -n prev_blank` against the original file). Both touches (top-level + blank-line pattern assignment) deleted entirely.

Verified post-fix: deliberate-failure test from v1.1.2 AAR (feature with `Scenario: ... \n And ...`) produces ONLY the ERROR line, no feature-content noise. Compared bytes vs pre-fix output to confirm noise reduction.

### 2.2 `scripts/gherkin-lint.sh` — `process_awk_output()` single awk pass (vawm, Gemini #39)

v1.1.2 (PR #38) introduced `process_awk_output()` helper with 2 separate awk subprocesses per call — one counting `^WARN ` lines, one counting `^ERROR ` lines. 4 callsites × 2 subprocesses = 8 awk processes per feature file. Gemini PR #39 suggested collapsing to a single awk pass with `read -r w e < <(awk '...' <<< "$out")` syntax that handles both counters at once.

Adopted verbatim. Verified with mixed-finding test: 2 WARNs + 1 ERROR in one feature produces summary `2 warning(s), 1 error(s)` and exit 1 (correct).

### 2.3 `scripts/crap-score.py` — `EXCLUDED_DIRS` constant deduplication (niv8, Gemini #71)

Pre-fix state: TWO separate sets of directory-exclusion strings with overlapping intent but DIVERGENT contents:

```python
# score_python() at line 85
ignore = {".git", ".venv", "venv", "node_modules", "dist", "build", "target",
          ".tox", ".mypy_cache", ".pytest_cache", "reports", "__pycache__"}

# main() at line 394 (added v1.1.1 for --json input-hash walk)
prune = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
         "target", ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt", ".cache"}
```

`ignore` had `"reports"` but lacked `.next` / `.nuxt` / `.cache`. `prune` had the modern web-framework dirs but lacked `"reports"`. Asymmetric coverage = real latent bug:

- Repo with `reports/` dir: score_python correctly skips it as a candidate, but the --json input-hash walk descends into it and hashes any `.py` files there. JSON envelope's `input_hash` then differs depending on whether `reports/` contains Python.
- Repo with `.next/` (Next.js): opposite asymmetry. Candidate scan may include it; input-hash walk correctly skips.

Fixed by extracting module-level `EXCLUDED_DIRS = { union-of-both }` and referencing from both call sites. Set contents documented in the constant's docstring along with the asymmetry rationale so a future reader knows WHY.

### 2.4 `.github/workflows/ci.yml` — shellcheck version pin (v1ds)

v1.1.2 (Phase A1) installed shellcheck via `apt-get install -y shellcheck` — pulls whatever Ubuntu's runner image ships (currently 0.9.0). v1.1.3 (Phase A2) proactively pinned ruff to 0.15.4 per the iah-shellcheck-version-pin lesson (filed during Phase A1 AAR). v1.1.4 brings shellcheck up to parity.

New pin: shellcheck v0.10.0 downloaded from `https://github.com/koalaman/shellcheck/releases/download/v0.10.0/shellcheck-v0.10.0.linux.x86_64.tar.xz` and installed to `/usr/local/bin/shellcheck`. CI prints `shellcheck --version` for audit trail. The `SHELLCHECK_VERSION` env var at the job level is the single source of truth for the pin; bumping requires explicit PR.

Note: pinning to v0.10.0 (newer than local 0.9.0) means CI might surface findings we haven't seen locally if v0.10.0 has stricter rules. Risk accepted because (a) the scripts are clean against 0.9.0 + ruff B+E+F, and (b) if v0.10.0 finds new issues that's exactly what the hard-fail gate exists to detect.

## 3. What worked

- **Bundling 4 deferred items into one focused release** — coherent scope (Gemini-surfaced quality fixes + CI hardening), each item small + independent, single AAR easier to read than 4 separate ones.
- **Verify-before-claim discipline reused** — ran shellcheck + ruff + py_compile + deliberate-failure tests BEFORE writing the PR description. Caught nothing this time (clean) but the habit is now muscle memory.
- **The mixed WARN+ERROR test** for the single-awk-pass change — better coverage than the v1.1.2 test which only exercised ERROR. Future change to the counter logic would be caught by either test.
- **Extracted constant pattern** for `EXCLUDED_DIRS` — small refactor with disproportionate clarity gain. Documents the asymmetry rationale at the constant's definition so a future reader doesn't need to dig through git blame to understand why those specific dirs are in the set.

## 4. What didn't work / what to watch

- **bd parallel-create race continues to bite** — claiming 4 beads in_progress via a for-loop only updated 2 per shell invocation (same buffer-issue pattern observed earlier in the session for dep adds). Mitigated by running the remaining bd updates as separate parallel Bash calls. Worth filing upstream eventually if it persists across bd releases.
- **Pinning shellcheck UP from runner-default 0.9.0 to 0.10.0** is technically a version bump in the OPPOSITE direction of what the iah-shellcheck-version-pin bead anticipated. The bead's spirit was "don't let CI silently upgrade" — pinning to a NEWER specific version achieves the same goal (deterministic) but means we're running stricter rules than local. Acceptable risk; if v0.10.0 finds findings on next CI run, that's the gate working.
- **iah-python-wrapper-scripts-sync (65k4) explicitly deferred** — too big for this bundle. Documented in CHANGELOG's "Not bundled" section so it's not invisible.

## 5. Verification

- `shellcheck scripts/*.sh` → exit 0 (local 0.9.0; CI will run pinned 0.10.0 on PR open)
- `ruff check` → `All checks passed!`
- `bash -n scripts/*.sh` → all pass
- `python3 -m py_compile scripts/crap-score.py + cli.py` → exit 0
- `bash scripts/harness-hash.sh --verify` → OK after `--init`
- gherkin-lint deliberate-failure test (And-at-start): exit 1, summary `0 warning(s), 1 error(s)`, output noise gone
- gherkin-lint mixed test (2 WARN + 1 ERROR): summary `2 warning(s), 1 error(s)`, exit 1
- All 5 manifests grep-verified at `1.1.4`

## 6. References

- IEP Convergence Debt Plan § Priority 3 (audit-harness hardening) + Priority 6 follow-ups
- Predecessor AARs:
  - 006: v1.1.1 script robustness (PR #37, Gemini #67 source-driven fixes)
  - 007: v1.1.2 shellcheck hard-fail + dead-code + awk-counter bug fix (PR #38, Phase A1)
  - 008: v1.1.3 ruff CI gate + dead-code (PR #39, Phase A2 + Gemini bugbear+PEP-8)
- Beads closed by this PR: o9q1, vawm, niv8, v1ds
- Bead still open + deferred: 65k4 (iah-python-wrapper-scripts-sync) — separate scope

— end AAR —
