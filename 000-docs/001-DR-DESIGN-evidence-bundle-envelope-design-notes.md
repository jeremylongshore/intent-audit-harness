<!-- BEGIN BD-SYNC:cross-ref:v1 -->

Beads: `bd_000-projects-aon3.3.1, bd_000-projects-pu35.4`
GitHub: `jeremylongshore/intent-audit-harness#148, jeremylongshore/intent-audit-harness#150`
Projection-SHA256: 9c5afc521b2e248ae4012e6887e7955b1795df838132a815f155f81d7a7c52a8

<!-- END BD-SYNC:cross-ref:v1 -->

# Design Notes: Evidence Bundle Gate-Result Envelope

> **Status: PHASE A DESIGN NOTES.** This document is the audit-harness side of the co-designed Evidence Bundle gate-result envelope schema. The canonical schema lives at `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/schema/gate-result.json` (per `IEL-4`); this document captures the design conversation and the audit-harness adoption plan.
>
> **Issue:** [`jeremylongshore/audit-harness#7`](https://github.com/jeremylongshore/audit-harness/issues/7) (`AH-4`)
> **Umbrella:** [`jeremylongshore/intent-eval-lab#5`](https://github.com/jeremylongshore/intent-eval-lab/issues/5) (`IEL-CONV-2`) → [`#4`](https://github.com/jeremylongshore/intent-eval-lab/issues/4) (`IEL-CONV-1`)
> **Master plan:** `~/.claude/plans/please-take-your-time-glimmering-stardust.md` § "audit-harness — what's needed" #3

| Beads  | `bd_000-projects-pu35.4`, `bd_000-projects-aon3` (`RC-IAH`) |
| ------ | ----------------------------------------------------------- |
| GitHub | `jeremylongshore/intent-audit-harness#150`                  |

## Goal

Define the JSON Schema 2020-12 envelope for a single Evidence Bundle gate-result row. The row is the unit that audit-harness emits via the Phase B `emit-evidence` subcommand (`AH-3`) and that downstream consumers (j-rig, Rollout Gate GHA) read.

## Design constraints

1. **Schema-versioned.** Every row carries a `schema_version` field so consumers can reject unknown major versions and warn on unknown minor versions.
2. **Forward-compatible.** A validator MUST accept unknown fields. New fields can be added in minor versions without breaking adopters.
3. **Hash-pinnable.** Fields like `policy_hash` and `input_hash` make tamper-evidence possible at the row level, independent of envelope signature.
4. **Idempotent emission.** Same input produces byte-identical row, modulo `timestamp`. This means generators MUST canonicalize JSON output (sorted keys, fixed numeric precision).
5. **No PII.** Rows MUST NOT carry user-identifying information. The `metadata` object is for machine-readable context (versions, hashes, durations), not human content.

## Field design

### Required fields

| Field            | Type              | Description                                                                                                                                                                       |
| ---------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gate_id`        | string            | Stable identifier for the gate. Conventionally `<framework>:<gate-name>` (e.g., `"audit-harness:escape-scan"`, `"audit-harness:crap"`, `"j-rig:eval-spec"`).                      |
| `result`         | enum              | One of: `"pass"`, `"fail"`, `"skip"`, `"error"`. `"skip"` indicates the gate was applicable but intentionally bypassed; `"error"` indicates the gate could not produce a verdict. |
| `timestamp`      | string (ISO 8601) | UTC timestamp of emission. RFC 3339 format.                                                                                                                                       |
| `schema_version` | string (SemVer)   | Version of THIS schema (envelope contract). Initial value: `"1.0"`.                                                                                                               |

### Optional fields

| Field          | Type    | Description                                                                                    |
| -------------- | ------- | ---------------------------------------------------------------------------------------------- |
| `metadata`     | object  | Implementation-specific context. Recommended sub-fields below.                                 |
| `policy_hash`  | string  | SHA-256 of the policy file the gate evaluated against (e.g., `tests/TESTING.md` content hash). |
| `input_hash`   | string  | SHA-256 of the input the gate evaluated (e.g., the diff content for escape-scan).              |
| `duration_ms`  | integer | Wall-clock duration of gate evaluation in milliseconds.                                        |
| `evidence_uri` | string  | URI to a more detailed evidence artifact (e.g., a JSON report file, a log dump).               |

### Recommended `metadata` sub-fields

- `framework_version` — version of the tool that produced the row (e.g., `"audit-harness@0.2.0"`)
- `harness_version` — version of the surrounding harness (e.g., `"@intentsolutions/audit-harness@0.2.0"`)
- `repo` — repo URL or path the gate ran against
- `commit_sha` — commit SHA the gate ran against
- `branch` — branch name (informational; not a primary key)
- `ci_run_url` — URL to the CI run that produced the row, if applicable

## Versioning rules

**`schema_version` SemVer:**

- **Major bump (1.0 → 2.0):** required field removed or renamed; `result` enum loses a value; semantic meaning of an existing field changes
- **Minor bump (1.0 → 1.1):** new optional field added; new value added to `result` enum; new recommended `metadata` sub-field documented
- **Patch bump (1.0 → 1.0.1):** documentation-only changes; no schema delta

**Compatibility:**

- A validator MUST accept unknown fields silently (forward-compat for minor bumps)
- A validator SHOULD warn on unknown major version (`schema_version: "2.x"` when validator only knows `1.x`)
- A validator MUST reject malformed JSON or missing required fields

## Open questions (Phase B)

1. **Signature embedding.** Should the row carry its own signature, or rely on the envelope signature? Trade-off: in-row signature enables row-level diff with audit; envelope signature is simpler. Lean: envelope-only for v1.0; revisit if row-level audit becomes a concrete requirement.
2. **Duration semantics.** Is `duration_ms` wall-clock from gate-start to gate-end, or just the policy-evaluation time? Lean: wall-clock from gate invocation to row emission. Document in spec.
3. **Failure annotations.** When `result: "fail"`, should there be a structured `failure_reasons` array in addition to `metadata.reasons` free-text? Lean: structured field in v0.2.0; v0.1.0 keeps it free-text in `metadata`.

## Example row (v1.0 schema)

```json
{
  "gate_id": "audit-harness:escape-scan",
  "result": "pass",
  "timestamp": "2026-05-10T18:30:00Z",
  "schema_version": "1.0",
  "metadata": {
    "framework_version": "audit-harness@0.2.0",
    "repo": "https://github.com/jeremylongshore/example-repo",
    "commit_sha": "abc123def456...",
    "ci_run_url": "https://github.com/jeremylongshore/example-repo/actions/runs/123"
  },
  "policy_hash": "sha256:fff111aaa222...",
  "input_hash": "sha256:bbb333ccc444...",
  "duration_ms": 142
}
```

## Sibling predicate: `skill-refiner-pass/v1` rows in the same envelope

> **Status: DESIGN NOTES — sibling-predicate envelope mapping.** This section
> documents how a `skill-refiner-pass/v1` evidence row sits in the **same**
> Evidence Bundle envelope as audit-harness's `gate-result/v1` rows. The
> normative authority for the `skill-refiner-pass/v1` predicate is
> `intent-eval-lab/000-docs/083-AT-SPEC-skill-refiner-pass-v1-normative-spec-2026-06-17.md`
> (prose) and `@intentsolutions/core/schemas/v1/skill-refiner-pass.schema.json`
> (machine-readable; **the kernel schema wins on disagreement**). audit-harness
> does **not** re-declare this schema — re-declaring a kernel-owned contract is
> exactly what the `kernel-shadow-check` CI lane flags. This section is the
> design-notes mapping only.

### Why it belongs here

The Evidence Bundle is the substrate every IEP validator emits into (Q3
unification thesis, DR-010). audit-harness emits `gate-result/v1` rows for
deterministic gates; the **Skill Refiner** (published as
[`@intentsolutions/refiner@0.1.0`](https://www.npmjs.com/package/@intentsolutions/refiner))
emits `skill-refiner-pass/v1` rows when a `SkillVersion` clears its acceptance
gate. Both row types ride in the **same** in-toto Statement v1 / DSSE envelope
documented above — a consumer (the Rollout Gate GitHub Action) unions rows of
**both** predicate types out of one bundle. So emitters and consumers agree on
the wire, the refiner-pass row's shape is captured here next to the
`gate-result/v1` shape it mirrors.

Per DR-082 Q4, `skill-refiner-pass/v1` **mirrors `gate-result/v1` exactly on the
wire**: same in-toto Statement v1 envelope, same DSSE wrapping, same body-only
schema validation, same row independence, same no-top-level-bundle-signature
rule. The divergences are below the wire (a separate signing trust root + an
independent `$schemaVersion` lane) and are NEVER expressed in the URL string or
the envelope shape.

### Predicate URI

```text
https://evals.intentsolutions.io/skill-refiner-pass/v1
```

A **flat sibling** of `gate-result/v1` (DR-082 Q1) — distinguished only by the
type name `skill-refiner-pass`. There is no `/authoring/` URL segment, ever; the
authoring/runtime chamber boundary lives below the wire (separate signing trust
root + schema lane), never in the URI grammar.

### Envelope placement (mirrors `gate-result/v1`)

A `skill-refiner-pass/v1` row is one entry in the Evidence Bundle, byte-shape
identical to the `gate-result/v1` rows above:

- **`_type`** — `https://in-toto.io/Statement/v1`
- **`subject[]`** — at least one entry whose `name` matches the
  `^[a-z0-9][a-z0-9-]*:(client|server|ci|sandbox|local):[a-zA-Z0-9][a-zA-Z0-9.-]*$`
  grammar; recommended idiom `skill-refiner:<side>:<skill-version-id>`. The
  `subject[].digest.sha256` MUST equal the predicate body's `source_snapshot_hash`
  **with the `sha256:` prefix removed** (the tamper-evidence binding, spec 083
  § 4 — the authoring-chamber analogue of `gate-result/v1`'s `input_hash` ===
  subject-digest binding).
- **`predicateType`** — the URI above.
- **`predicate`** — the body in the table below.
- **DSSE wrapping** — `payloadType` `application/vnd.in-toto+json`, row-level
  signature only, no top-level bundle signature. Row independence: each row is
  verifiable without any sibling row.

### Predicate body — the accept determinants (per spec 083 § 5.1)

The body carries exactly the fields a verifier needs to independently re-derive
the accept decision from immutable inputs. (Canonical machine-readable schema:
`@intentsolutions/core/schemas/v1/skill-refiner-pass.schema.json`,
`additionalProperties: false`.)

| Field                    | Type                                    | Role in the row                                                                                                                                                                                                                                                                      |
| ------------------------ | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `verdict`                | enum `accept \| reject`                 | Decision verdict (closed enum). A relying party reads `verdict === "accept"`, never row-presence alone.                                                                                                                                                                              |
| `reason`                 | array of strings, `minItems: 1`         | Structured reason **codes** (not free prose — avoids leaking skill content onto a public transparency log).                                                                                                                                                                          |
| `refiner_strategy_id`    | string, `minLength: 1`                  | The `RefinerStrategy` that produced the verdict — REQUIRED in the signed body (mechanism-swappable must not be mechanism-untraceable). Append-only-registered; a retired id is never reused.                                                                                         |
| `skill_version_id`       | UUIDv7                                  | The accepted `SkillVersion` (kernel's 14th entity). Referenced by the kernel's existing UUIDv7 primitive.                                                                                                                                                                            |
| `parent_version_id`      | UUIDv7                                  | The parent `SkillVersion` the accepted one was refined from — binds parent → child so an unrelated skill can't be laundered through a forged lineage.                                                                                                                                |
| `source_snapshot_hash`   | `sha256:`-prefixed                      | Content hash of the **post-edit** SkillVersion snapshot. The in-toto `subject[].digest.sha256` equals this value prefix-stripped (the § 4 binding above).                                                                                                                            |
| `eval_set_ref`           | object `{ hash, version, lineage_id }`  | Reference to the **FROZEN** eval-set the verdict was derived against — the epistemic basis. `hash` (`sha256:`-prefixed) pins exact content; `version` (string, `minLength: 1`) pins which published eval-set; `lineage_id` (UUIDv7) pins the lineage. `additionalProperties: false`. |
| `edit_proposal_hash`     | `sha256:`-prefixed                      | Hash of the `EditProposal` (the bounded edit-ops) that earned the pass — binds WHAT changed.                                                                                                                                                                                         |
| `behavioral_delta`       | number                                  | Observed delta on the behavioral dimension the accept gate requires significant Pareto-dominance on.                                                                                                                                                                                 |
| `named_dimension_deltas` | array of `{ id, delta, non_regressed }` | Per-named-dimension deltas — the non-regression surface. For an `accept`, every entry's `non_regressed` MUST be `true`. MAY be empty. Each item `additionalProperties: false`.                                                                                                       |
| `alpha`                  | number, `(0, 1)` exclusive              | The significance level the one-sided z-test ran at — the falsifiability anchor.                                                                                                                                                                                                      |
| `test_statistic_kind`    | const `one-sided-z`                     | Statistical-test family. CONST for v1; changing it mints `/v2`.                                                                                                                                                                                                                      |

**Optional, descriptive (NOT determinants — spec 083 § 5.2):**
`cost_record_ref` (UUIDv7 → `CostRecord.id`), `replay_fidelity_level`
(`RF-0..RF-4`), `signing_downgrade_reason` (string). A consumer MUST NOT treat
their absence as a verification failure.

### Producer / consumer relationship

- **Producer:** `@intentsolutions/refiner` (the Skill Refiner) — emits one
  `skill-refiner-pass/v1` row per real refiner verdict. audit-harness's own
  emitter (`scripts/emit-evidence.{sh,py}`) produces `gate-result/v1` rows;
  audit-harness does **not** produce refiner-pass rows.
- **Consumer:** the Rollout Gate (`intent-rollout-gate` GitHub Action) reads a
  bundle and unions rows of **both** predicate types against a
  `tests/TESTING.md` policy → ship / no-ship.
- **Composable partial attestation:** like every platform predicate, a
  refiner-pass row stands alone — silence ≠ failure. Absence of a row for a
  skill means "no PASS emitted," never "that failed." Rows are unioned, not
  joined.

### Signing posture (spec 083 § 6)

`skill-refiner-pass/v1` ships in `sigstore_staging` and becomes
production-Rekor-signable ONLY when **all four** DR-082 Q3 triggers hold
(AND-gated): (1) the SPEC.md normative section lands, (2) DNSSEC + CAA pre-flight
green on `evals.intentsolutions.io`, (3) the authoring chamber's **separate**
signing trust root is provisioned-and-live (the new gating step `gate-result/v1`
never had — DR-081 no-shared-root), (4) ≥1 real `SkillVersion` clears the gate on
a frozen, signed eval-set. Until then every row carries
`signing_mode = "sigstore_staging"` and `rekor_log_index = null`. The cosign
keyless OIDC identity MUST resolve to the **authoring** chamber's Fulcio identity,
distinct from the runtime chamber's — a refiner-pass row signed by a
runtime-chamber keyid is INVALID.

### Cross-references (this section)

- Normative prose spec: `intent-eval-lab/000-docs/083-AT-SPEC-skill-refiner-pass-v1-normative-spec-2026-06-17.md`
- Canonical machine-readable schema (kernel; the authority on disagreement): `@intentsolutions/core/schemas/v1/skill-refiner-pass.schema.json`
- The mirrored predecessor (`gate-result/v1` predicate body): `tests/fixtures/gate-result-v1.schema.json` + Blueprint B § 7
- Minting ADR (the 5 binding decisions Q1–Q5): `intent-eval-lab/000-docs/082-AT-DECR-isedc-skill-refiner-pass-v1-predicate-uri-2026-06-17.md`
- Producer: [`@intentsolutions/refiner`](https://www.npmjs.com/package/@intentsolutions/refiner)

## Adoption plan (audit-harness side)

**Phase A (now):** this design document. No implementation.

**Phase B:**

1. `AH-2` — add `--json` flag to all subcommands (uniform machine-readable output)
2. `AH-3` — add `emit-evidence` subcommand. New script `scripts/emit-evidence.{sh,py}`. Reads `tests/TESTING.md` policy + most-recent run results, emits a row.
3. `AH-5` — backward-compat regression suite confirms existing CLI surface unchanged
4. Schema lives in `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/schema/gate-result.json` (per `IEL-4`)

## Cross-references

- Spec home (canonical schema location): `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/`
- Audit-harness CLI dispatcher: `bin/audit-harness.js`
- Existing subcommand that emits JSON (precedent): `scripts/crap-budget.{sh,py}` — already emits JSON, useful reference for the row-emission shape
- Master plan: `~/.claude/plans/please-take-your-time-glimmering-stardust.md` § "audit-harness — what's needed"

## 9. D9 — Evidence bundle row lifecycle for `skill-refiner-pass/v1`

The D9 lifecycle makes the hand-off from a refiner decision to a rollout
decision explicit. A refiner emits a signed predicate row; audit-harness
places the row in the append-only bundle stream; and intent-rollout-gate
consumes the canonical bundle against the repository's testing policy. A
consumer evaluates the row's predicate and evidence rather than inferring a
failure from row absence.

```text
   refiner accept()              audit-harness                intent-rollout-gate
   ─────────────────              ─────────────                ───────────────────

   SkillVersion v_new   ──emit──▶  gate-result row
                                  ┌────────────────────────┐
                                  │ predicate:             │
                                  │   skill-refiner-pass/v1│
                                  │ subject:               │
                                  │   sha256:<v_new.hash>  │
                                  │ result: pass | fail    │
                                  │ score_deltas: {…}      │
                                  │ rejected_buffer: [...] │
                                  │ actor: <human|claude>  │
                                  │ provenance: sigstore   │
                                  │ spec_version: v1.0.0   │
                                  └───────────┬────────────┘
                                              │  bundle.jsonl
                                              ▼
                                  ┌────────────────────────┐
                                  │  Evidence Bundle       │
                                  │  (canonical, signed)   │
                                  └───────────┬────────────┘
                                              │
                                              ▼  consumed
                                  ┌────────────────────────┐
                                  │  intent-rollout-gate   │
                                  │  Action evaluates row  │
                                  │  against TESTING.md    │
                                  │  policy →              │
                                  │  ship / no-ship verdict│
                                  └────────────────────────┘
```

The diagram is a topology contract, not an implementation claim: the refiner
owns acceptance, audit-harness owns bundle assembly, and the rollout gate owns
the policy decision. The signed bundle remains the canonical hand-off between
those responsibilities.
