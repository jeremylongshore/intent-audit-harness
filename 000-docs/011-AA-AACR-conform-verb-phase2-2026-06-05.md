# AAR — `conform` verb (comprehensive-audit Phase 2 / epic E4)

| | |
|---|---|
| **Date** | 2026-06-05 |
| **Epic** | Add the `conform` verb to audit-harness by reusing the `/validate-*` validators and bundled content-addressed schemas (E4) |
| **Plan** | `intent-eval-lab/000-docs/040-PP-PLAN-audit-trio-comprehensive-2026-06-04.md` (PP-PLAN-040), Phase 2 |
| **PR** | [jeremylongshore/intent-audit-harness#54](https://github.com/jeremylongshore/intent-audit-harness/pull/54) |
| **bd** | epic `bd_000-projects-b6qm` + children `rlp5l` (wire validators), `4hwdo` (bundle schemas + policy_hash), `smvjb` (pass/fail fixtures) — all CLOSED |

## What landed

The second piece of the read-only brain (after `classify` in Phase 1): **`audit-harness conform [repo]`**, a read-only conformance gate-runner.

- **`scripts/conform.py`** (stdlib + PyYAML, hash-pinned): for every `dimension: conformance` gate in a repo's `audit-profile/v1`, locate the artifact(s) and emit a `gate-result/v1` Evidence Bundle row (JSON array, stdout). Never writes, never live-fetches.
- **`schemas/conform/v1/`** — four bundled content-addressed schemas: `skillmd-frontmatter`, `mcp-config`, `plugin-manifest`, `agent-frontmatter`. Each schema's sha256 is recorded in the row's `policy_hash`, so a row re-verifies against the exact schema that produced it.
- **`tests/conform/`** — 31-check golden suite + valid/malformed fixtures (SKILL.md, .mcp.json, plugin manifest, agent). CI `conform` job.
- **`bin/audit-harness.js`** — registers `conform`; `.harness-hash` re-pinned (conform.py pinned, dispatcher re-pinned).

Result mapping: valid → `PASS`; advisory violation → `ADVISORY`(severity `error`, exit 0); `--strict`/blocking violation → `FAIL`(exit 1); missing artifact → `NOT_APPLICABLE`; missing bundled schema or absent external tool → `ADVISORY` indeterminate; kill-switch → `[]`.

## What worked

- **Data-first paid off.** Because the dimension→gate registry already routed each artifact kind to a conform gate (Phase 0), `conform` is a schema-driven engine: adding a kind = drop a schema into `schemas/conform/v1/`, no code change. `marketplace`/`hook` currently resolve to ADVISORY-indeterminate by that same path.
- **Reusing `classify` as the profile source** (subprocess, single source of truth) means `conform`'s gate set is provably identical to `classify`'s output — no second classifier to drift.
- **Dogfood caught nothing broken but proved the honesty path:** read-only run across all 6 IEP repos — TS/library repos correctly produce 0 conformance rows; `intent-rollout-gate` (a GitHub Action) correctly degrades to ADVISORY-indeterminate because `yamllint` is absent, rather than a false FAIL.

## Decisions worth recording

1. **Embedded subset JSON-Schema validator over ajv (deviation from bead `rlp5l`'s "ajv" wording).** The plan's reproducibility requirement — *same commit + same harness version ⇒ identical verdict* for signed evidence — is broken by an external ajv whose version varies per machine. So bundled JSON-Schemas are checked by a small embedded validator that is *complete for the closed bundled schemas* (which use only the keyword subset it supports). `spectral` (OpenAPI) and `yamllint` (Action) stay as shell-outs because reimplementing them genuinely *would* be reinvention; their absence degrades to indeterminate. The engine records `metadata.validator` so evidence is honest about provenance.
2. **conform's bundled schemas are the deterministic structural floor, not the IS rubric.** Frontmatter "does it parse + carry required keys + correct types" lives here; the 100-point grading + cross-artifact invariants stay in `/validate-*` + the SAK authoring kernel. The two are deliberately separate dirs (`schemas/conform/v1/` vs the forthcoming `schemas/authoring/v1/`); when SAK lands, conform can repoint (lab-schema-repoint precedent).
3. **PyYAML-absent ⇒ indeterminate, not a guessed parse.** Frontmatter kinds emit an honest ADVISORY-indeterminate rather than risk a wrong verdict from a hand-rolled YAML reader. JSON kinds use stdlib `json` (always present) → full verdict.

## What didn't work / friction

- **Stacked-PR CI gotcha.** `ci.yml` triggers only on `pull_request: branches: [main]`. The Phase 2 branch necessarily stacks on the unmerged Phase 0/1 branch (it imports `classify` + the registry, absent from `main` until #53 merges). Targeting the Phase 0/1 branch ran only the always-on doc-lint workflow — the full suite (incl. the new `conform` job) never fired. Fix: retargeted #54 to `main` + close/reopen to fire the `pull_request` event. Consequence: while #53 is unmerged, #54's diff includes the Phase 0/1 commits; it reduces to conform-only once #53 merges. **Lesson for Phase 3+:** either land each phase to `main` before starting the next, or accept the combined-diff-until-merge tradeoff; a `workflow_dispatch` trigger on `ci.yml` would also let stacked branches get signal without retargeting.
- **`bd-sync note` hit a DB lock** ("begin read tx: context canceled") under a `timeout` guard. Bead *state* was unaffected (closes persisted to JSONL with export-between-each per the rapid-write-race pattern); only the GH-comment mirror needed a direct `gh issue comment` fallback.

## Evidence

- conform golden suite **31/31**; classify suite **16/16** (no regression).
- PR #54 required CI all green: conform, classify, ruff, shellcheck, py_compile, self-check (Node 18/20/22), regression, manifest-alignment. Only advisory **Vale** fails (known `CVEs` false-positive, non-blocking).
- `escape-scan --staged` clean (REFUSE=0) after re-pinning; `harness verify` OK; `policy_hash == bundled-schema sha256` + reproducible across runs (suite-asserted).

## Follow-ups

- **Phase 3 (E5)** — testing-depth gates (L2/L4/L5 + property/fuzz/flakiness), shell-out, advisory-first, `--fast`/`--deep` split.
- Light up `marketplace` + `hook` conform by adding their bundled schemas (no code change).
- E9 (refactor `/audit-tests` + `/implement-tests` to call `classify`/`conform`) remains gated on these verbs being "trusted" per the plan — not just on E4 closing.
