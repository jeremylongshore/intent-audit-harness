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

*Filed per Document Filing Standard v4.3. Canonical plan: PP-PLAN-040. Closes the schema deliverable of
the Phase 0 "data + safety spine" epic.*
