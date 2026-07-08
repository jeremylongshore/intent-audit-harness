# AT-SPEC-010 — `audit-profile/v1` (the data-first value)

**Date:** 2026-06-04
**Type:** AT-SPEC (specification)
**Status:** ACCEPTED — `audit-profile/v1` is a live contract. The schema (`schemas/audit-profile/v1.schema.json` + `registry.v1.json`) ships in the published package and the `classify` verb that emits it is live in the CLI (audit-harness 1.2.x).
**Authority:** PP-PLAN-040 (`intent-eval-lab/000-docs/040-PP-PLAN-audit-trio-comprehensive-2026-06-04.md`) §§ 3.3, 4.4, 5, 7 Phase 0
**Artifacts:** `schemas/audit-profile/v1.schema.json` + fixtures under `tests/fixtures/audit-profile/`
**Relationship:** mirrors `tests/fixtures/gate-result.schema.json` (`gate-result/v1`) conventions so the two predicates compose in one Evidence Bundle.

---

## 0. Why this exists (data-first, before any verb)

The plan's central engineering discipline is **data-first values before verbs**: specify the value a
verb produces as a *closed, versioned, hash-bearing* thing *before* writing the verb. `audit-profile/v1`
is the value the read-only `classify` verb (Phase 1) will emit. It is authored and tested here, in
Phase 0, with golden fixtures — **no `classify` code lands until this value and its fixtures are green.**

`audit-profile/v1` answers one question deterministically: **given a repo at a commit, which audit
gates apply, with what applicability and what enforcement, and what could the classifier not resolve?**

---

## 1. Shape (closed / versioned / hashed)

Exactly the conventions `gate-result/v1` already uses:

- **Versioned in `$id`:** `https://evals.intentsolutions.io/audit-profile/v1.schema.json`. A breaking
  change ships as `v2` alongside `v1`; `v1` is never mutated (prior profiles must re-validate forever).
- **Closed:** `additionalProperties: false` at every object level. Unknown keys are an error, not silently dropped.
- **Self-describing:** top-level `schema_version` MUST equal `"audit-profile/v1"`.
- **Hash-bearing:** `registry_hash` records the SHA-256 of the canonical dimension-to-gate registry the
  profile was resolved against, so a profile is reproducible against the exact registry version.

Required top-level fields: `schema_version`, `subject`, `classifier`, `registry_hash`, `timestamp`,
`classifications`, `gates`, `unresolved`. Optional: `dimensions` (a convenience projection of
`gates[].dimension`), `overrides` (provenance of any `.audit-harness.yml` directives applied).

---

## 2. The four load-bearing invariants

1. **Classifications are a UNION, not a winner** (`classifications` is an array, `minItems: 1`).
   A repo that is a TS monorepo *and* ships a SKILL.md *and* an MCP server carries all three entries.
   Picking one silently drops the others' gates — a false-negative, which is worse than a false-positive.
   (PP-PLAN-040 § 4 principle 11.)
2. **`unresolved[]` is the only surface Claude may refine.** The deterministic classifier emits its
   residue explicitly. `/audit-tests` operates *only* on `unresolved[]`, proposing patches a human pins —
   it never co-authors the deterministic `classifications`/`gates`, so CI stays reproducible.
   (PP-PLAN-040 § 4 principle 4 + § 5.) An empty `unresolved` array means a fully deterministic profile.
3. **`waived` ⇒ `disabled`.** A schema `allOf` enforces that a gate whose `applicability` is `waived`
   has `enforcement: disabled`. You cannot block (or even advise) on a gate that does not run for this
   repo type. (Proven by `tests/fixtures/audit-profile/invalid-waived-gate-marked-blocking.json`.)
4. **`registry_hash` makes the profile reproducible.** The registry — "which gates apply to repo-type X" —
   is the *single canonical datum* (Phase 0 collapses `layer-applicability.md`, each repo's `TESTING.md`,
   and `harness-hash.sh` into projections of it). The hash pins which registry version produced the profile.

---

## 3. Field reference (summary)

| Field | Meaning |
|---|---|
| `schema_version` | const `audit-profile/v1` |
| `subject` | `{name, commit_sha, root}` — what was classified (`root` ≠ `.` for an independently-classified monorepo package) |
| `classifier` | `tool@semver` that produced the profile (same shape as gate-result `runner`) |
| `registry_hash` | `sha256:…` of the canonical dimension-to-gate registry datum |
| `timestamp` | RFC 3339 UTC; moment the profile was emitted |
| `classifications[]` | UNION of `{kind, confidence, signals[]}` — repo types + Claude-artifact kinds + `regulated` overlay |
| `dimensions[]` | convenience projection of `gates[].dimension` (consumers treat `gates[]` as authoritative) |
| `gates[]` | `{gate_id, dimension, applicability, enforcement, result_class_default?, tool?}` — the resolved gate set |
| `unresolved[]` | `{kind, reason, candidates[]}` — the deterministic residue Claude may refine |
| `overrides` | `{source, override_hash, kill_switch}` — provenance of `.audit-harness.yml` directives applied |

**`gate_id`** reuses the gate-result/v1 regex `tool:side:gate-id` so the `gate-result` row a run later
emits for a gate carries the *same* `gate_id` — the profile and its results join on that key.

**`dimension`** enum is the comprehensive "what to look for": `testing-depth`, `conformance`, `currency`,
`security`, `hygiene`, `skill-quality` (PP-PLAN-040 § 6).

**`applicability`** maps the registry's severity glyphs: `required` (✅ P0), `recommended` (⭕ P1 advisory),
`conditional` (⚠ fires only with a sibling signal), `waived` (❌ not run).

**`enforcement`**: new gates ship `advisory`; `blocking` is earned (engineer-pinned in the hash-pinned
`TESTING.md` after a measured FP-rate below the stated bar on the IEP corpus); `disabled` = waived or kill-switched.

**`result_class_default`** introduces `INDETERMINATE` (infra failure ≠ policy failure): pure-local policy
gates fail closed (`FAIL`); network-touching checks fail open/advisory (`INDETERMINATE`).

---

## 4. Validation (proven in Phase 0)

```bash
# positive fixture is VALID; negative fixture (waived gate marked blocking) is correctly REJECTED
npx -p ajv-cli@5 -p ajv-formats@3 ajv validate \
  -s schemas/audit-profile/v1.schema.json \
  -d tests/fixtures/audit-profile/union-monorepo-with-skill-and-mcp.json \
  -c ajv-formats --spec=draft2020
```

The positive fixture is the canonical UNION case: a monorepo that is *also* a library + cli + skill + mcp,
producing gates across five dimensions — the case where picking a single classification would lose coverage.

---

## 5. What this is NOT (scope boundary)

- **Not a verb.** `classify` (Phase 1) produces this value; `conform` (Phase 2) records the schema
  version+hash in its `gate-result.policy_hash`. This doc specifies only the value.
- **Not live-fetched.** When bundled into a harness release, this schema is content-addressed and
  validated against the bundled copy at gate-time — never fetched over the network.
- **Not mutated.** `v1` is frozen once published. `currency` *proposes* a `v2` alongside; it never
  overwrites `v1`.

---

## 6. Predicate baseline — what the harness recognizes vs. what it emits

This spec doubles as the audit-harness **predicate baseline**: the roster of Evidence Bundle
predicate types the harness is aware of, split by whether the harness *emits* the row or merely
*recognizes* it as a sibling in the same bundle. The split matters because the `kernel-shadow-check`
CI lane flags any attempt to re-declare a kernel-owned contract — the harness must know these
predicates exist without owning their schemas.

| Predicate URI | Emitted by the harness? | Harness relationship |
|---|---|---|
| `https://evals.intentsolutions.io/audit-profile/v1.schema.json` | ✅ yes — `classify` verb | The value this spec defines. |
| `https://evals.intentsolutions.io/gate-result/v1` | ✅ yes — `conform` / `audit` / `scan` / `emit-evidence` verbs | Deterministic gate outcomes. Conventions this spec mirrors (§ 1). |
| `https://evals.intentsolutions.io/skill-refiner-pass/v1` | ❌ no — see § 6.1 | Recognized sibling; emitted by the **Skill Refiner**, not the harness. |

### 6.1 `skill-refiner-pass/v1` — recognized, not harness-emitted

The **Skill Refiner** (published as
[`@intentsolutions/refiner`](https://www.npmjs.com/package/@intentsolutions/refiner)) emits
`skill-refiner-pass/v1` rows when a `SkillVersion` clears its acceptance gate. These rows ride in the
**same** in-toto Statement v1 / DSSE Evidence Bundle envelope as the harness's `gate-result/v1` rows,
so a downstream consumer (the Rollout Gate GitHub Action) unions rows of all three predicate types out
of one bundle. audit-harness must **recognize** this predicate for baseline completeness but **never
emits it and never re-declares its schema** — the kernel schema
(`@intentsolutions/core/schemas/v1/skill-refiner-pass.schema.json`) is the authority, and the wire-shape
mapping lives in the sibling-predicate section of the envelope design notes
(`000-docs/001-DR-DESIGN-evidence-bundle-envelope-design-notes.md`).

**Predicate type.** `https://evals.intentsolutions.io/skill-refiner-pass/v1` — a **flat sibling** of
`gate-result/v1` and `audit-profile/v1` (no `/authoring/` URL segment; the authoring/runtime chamber
boundary lives below the wire, never in the URI grammar). Distinguished only by the type name
`skill-refiner-pass`. The predicate body attests a `SkillVersion` accept-decision from the Refiner —
`verdict` (`accept | reject`), the accepted `skill_version_id` + `parent_version_id` lineage, the
`source_snapshot_hash` tamper-evidence binding, the frozen `eval_set_ref`, and the `behavioral_delta` /
`named_dimension_deltas` accept determinants. A relying party reads `verdict === "accept"`, never
row-presence alone.

**Expected row count per refinement run.** One `skill-refiner-pass/v1` row per real Refiner **verdict**
— i.e. per `SkillVersion` that the Refiner evaluates against its acceptance gate in a run, whether the
verdict is `accept` or `reject`. Rows are **composable partial attestations**: each stands alone,
silence ≠ failure, and rows are unioned (not joined) with the harness's own `gate-result/v1` rows in the
bundle. Absence of a refiner-pass row for a skill means "no verdict emitted," never "that failed." A
harness run contributes **zero** refiner-pass rows — the harness's row count for this predicate is
always 0 (it only recognizes them arriving from the Refiner).

**Sigstore mode handling.** `skill-refiner-pass/v1` ships in `signing_mode = "sigstore_staging"`
(`rekor_log_index = null`) and becomes production-Rekor-signable only when all four DR-082 Q3 triggers
hold (AND-gated): the SPEC.md normative section lands, DNSSEC + CAA pre-flight is green on
`evals.intentsolutions.io`, the authoring chamber's **separate** signing trust root is provisioned-and-live
(a gating step `gate-result/v1` never had — DR-081 no-shared-root), and ≥1 real `SkillVersion` clears the
gate on a frozen signed eval-set. Its cosign keyless OIDC identity MUST resolve to the **authoring**
chamber's Fulcio identity, distinct from the runtime chamber's that signs `gate-result/v1`; a
refiner-pass row signed by a runtime-chamber keyid is INVALID. The harness does not sign these rows —
this baseline records the mode only so a bundle carrying mixed predicate types is understood.

**Cross-references.**

- Wire-shape / envelope mapping (audit-harness side): `000-docs/001-DR-DESIGN-evidence-bundle-envelope-design-notes.md` § "Sibling predicate: `skill-refiner-pass/v1` rows in the same envelope"
- Normative prose spec: `intent-eval-lab/000-docs/083-AT-SPEC-skill-refiner-pass-v1-normative-spec-2026-06-17.md`
- Canonical machine-readable schema (kernel; wins on disagreement): `@intentsolutions/core/schemas/v1/skill-refiner-pass.schema.json`
- Minting ADR (Q1–Q5 binding decisions): `intent-eval-lab/000-docs/082-AT-DECR-isedc-skill-refiner-pass-v1-predicate-uri-2026-06-17.md`
- Producer: [`@intentsolutions/refiner`](https://www.npmjs.com/package/@intentsolutions/refiner)

---

*Filed per Document Filing Standard v4.3. Canonical plan: PP-PLAN-040. Closes the schema deliverable of
the Phase 0 "data + safety spine" epic. § 6 predicate baseline closes bead aon3.2 (Skill Refiner —
audit-harness baseline update to include the refiner-pass predicate).*
