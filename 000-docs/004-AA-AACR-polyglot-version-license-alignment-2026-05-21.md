# Polyglot Manifest Alignment — Version + License (P3 first cut)

**Filing**: 004-AA-AACR-polyglot-version-license-alignment-2026-05-21.md
**Date**: 2026-05-21
**Author**: Jeremy Longshore (CTO + beads work; executed by Claude per CEO-mode delegation)
**Beads closed (pending PR merge)**:
- `iah-version-drift` (`bd_000-projects-uoz3`, P2)
- `iah-license-drift` (`bd_000-projects-ck2e`, P2)
- `iah-version-canonical-check` (`bd_000-projects-hd5y`, P2)
**Cluster**: IEP Convergence Debt Plan Priority 3 (`iep-P3-audit-harness-hardening`, `bd_000-projects-t3q8`)
**Scope**: first cut of Priority 3. Subsequent PRs cover `iah-sigstore` (npm provenance + restored release workflow), `iah-self-pin` (`.harness-hash` + CI hard fail), `iah-py-sigstore` + `iah-rust-attest` (polyglot signing), `iah-bash-floor` (bash >= 4.0 check), `iah-dependabot-polyglot` (pip + cargo coverage), and `iah-kernel-shadow-check` (Priority 0 standing safety rule).

---

## 1. What this AAR records

Priority 3 (audit-harness supply-chain hardening) of the IEP Convergence Debt Plan opens with the lowest-risk, highest-leverage fixes: align the four polyglot manifests that disagreed on version + license, and add a CI gate that fails any future drift. Drift was originally flagged in `000-docs/003-AA-AUDT-appaudit-devops-playbook.md` lines 296 / 331 / 335 / 341 — those notes are now resolved.

## 2. Drift before this PR

| Manifest | Version | License |
|---|---|---|
| `package.json` (npm — canonical) | **1.0.1** | **Apache-2.0** |
| `version.txt` | 0.2.0 | n/a |
| `python/pyproject.toml` | 0.1.0 | MIT |
| `python/src/intent_audit_harness/__init__.py` `__version__` | 0.1.0 | n/a |
| `rust/Cargo.toml` | 0.1.0 | MIT |
| `rust/Cargo.lock` (`intent-audit-harness` entry) | 0.1.0 — gitignored; not committed | n/a |

Six independent version locations, three different version numbers, two different licenses. The licensing gap was the more consequential of the two: the npm package shipped Apache-2.0 (and the README + LICENSE file at the repo root say Apache-2.0), but anyone fetching the package via PyPI or crates.io got MIT classifier metadata. That is precisely the supply-chain integrity gap Priority 3 exists to close.

## 3. State after this PR

All five committed locations now report `version = 1.0.1` and (where applicable) `license = Apache-2.0`. The CI gate `version-canonical-check` runs on every PR + push to main + nightly self-check and fails on any divergence. The gate also opportunistically checks `rust/Cargo.lock` — currently gitignored, so the check no-ops gracefully on the CI checkout; if the lockfile is ever committed (Rust convention for binary crates) the gate will already enforce alignment.

### CI gate behavior

The gate reads `package.json#version` and `package.json#license` as the canonical source. It then checks each of the five other locations against the canonical pair. The gate fails with a precise per-file error annotation (`::error file=...::`) if any drift is detected. The error message tells the engineer how to bump: `npm version <bump>` first to set the canonical, then mirror the four other manifests.

### Future bump procedure

```bash
# 1. Bump npm canonical (this writes package.json)
npm version patch   # or minor, major

# 2. Mirror to the polyglot manifests
new_version=$(node -p "require('./package.json').version")
sed -i "1s/.*/${new_version}/" version.txt
sed -i "s/^version = \".*\"/version = \"${new_version}\"/" python/pyproject.toml
sed -i "s/^__version__ = \".*\"/__version__ = \"${new_version}\"/" python/src/intent_audit_harness/__init__.py
sed -i "/^\[package\]/,/^\[/ s/^version = \".*\"/version = \"${new_version}\"/" rust/Cargo.toml
# Cargo.lock auto-updates on next `cargo build`; for clean lockfile bumps:
(cd rust && cargo update -p intent-audit-harness)

# 3. Verify locally (matches the CI gate)
bash -c 'node -p "require(\"./package.json\").version"'   # echoes canonical
# Then re-run the alignment block from .github/workflows/ci.yml `version-canonical-check`

# 4. Commit + push; CI confirms
```

This procedure will be folded into a future `scripts/version-bump.sh` helper as part of the sigstore-restore work (`iah-sigstore`).

## 4. Out-of-scope for this PR (filed as follow-up beads)

| Concern | Bead | Why deferred |
|---|---|---|
| npm provenance / sigstore signing on publish | `iah-sigstore` (bd_000-projects-t0ba, P1) | Needs separate release workflow restore (`release.yml` was removed in commit `d5cef4e`); the work is bigger than alignment and warrants its own PR |
| `.harness-hash` self-pin + flip CI tolerant-exit-3 to hard fail | `iah-self-pin` (bd_000-projects-itpl, P1) | Touches the self-check job semantics; better as its own PR for review clarity |
| Python wheel sigstore signing | `iah-py-sigstore` (bd_000-projects-kyk1, P2) | Downstream of `iah-sigstore` — copies the kernel pattern once it's restored |
| Rust crate attestation | `iah-rust-attest` (bd_000-projects-13ty, P2) | Same as above |
| Bash version floor check | `iah-bash-floor` (bd_000-projects-jcgw, P3) | Trivial, can ride on any subsequent PR |
| Dependabot pip + cargo coverage | `iah-dependabot-polyglot` (bd_000-projects-cp2n, P3) | Trivial dependabot.yml edit, can ride on any subsequent PR |
| Priority 0 standing safety rule: `audit-harness kernel-shadow-check` subcommand | `iah-kernel-shadow-check` (bd_000-projects-873c, P1) | Per the audit-harness CLAUDE.md design rule "scripts are the source of truth; node CLI is a thin dispatcher" + Discovery 1 in the IEP Convergence Debt Plan, the parent `iah-E02` audit-harness kernel-adoption question has open architectural ambiguity that needs user resolution before subcommand implementation lands |
| Regression-suite schema source URL (currently pulls from lab redirect stub) | NEW follow-up bead to be filed | Side effect of Priority 5 lab schema repoint — the audit-harness regression suite's CI step at `.github/workflows/ci.yml` line 121 fetches the schema from `raw.githubusercontent.com/jeremylongshore/intent-eval-lab/main/specs/.../gate-result.schema.json`, which is now a redirect stub. The suite needs to switch to the kernel canonical URL. Not in scope of this PR. |

## 5. Verification

- Local dry-run of the CI gate logic against the new state: all 6 locations agree on `version=1.0.1`, license=`Apache-2.0` where applicable. Passes.
- `bash scripts/escape-scan.sh --staged` against the staged diff (per audit-harness CLAUDE.md design rule 5): clean.
- No CLI surface change. No runtime behavior change. No new dependencies. No new npm scripts.

## 6. References

- IEP Convergence Debt Plan (Priority 3 specification) — local plan reference, 2026-05-20 enhanced 2026-05-21
- audit-harness `000-docs/003-AA-AUDT-appaudit-devops-playbook.md` — original drift findings (now resolved)
- audit-harness CLAUDE.md — design rules (scripts source of truth, zero runtime deps, backward compat on CLI)
- Canonical kernel patterns — `intent-eval-core/.github/workflows/release.yml` is the sigstore-provenance reference implementation for `iah-sigstore`

— Jeremy Longshore
intentsolutions.io
