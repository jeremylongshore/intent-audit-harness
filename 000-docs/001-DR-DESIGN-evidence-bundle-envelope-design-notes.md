# Design Notes: Evidence Bundle Gate-Result Envelope

> **Status: PHASE A DESIGN NOTES.** This document is the audit-harness side of the co-designed Evidence Bundle gate-result envelope schema. The canonical schema lives at `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/schema/gate-result.json` (per `IEL-4`); this document captures the design conversation and the audit-harness adoption plan.
>
> **Issue:** [`jeremylongshore/audit-harness#7`](https://github.com/jeremylongshore/audit-harness/issues/7) (`AH-4`)
> **Umbrella:** [`jeremylongshore/intent-eval-lab#5`](https://github.com/jeremylongshore/intent-eval-lab/issues/5) (`IEL-CONV-2`) → [`#4`](https://github.com/jeremylongshore/intent-eval-lab/issues/4) (`IEL-CONV-1`)
> **Master plan:** `~/.claude/plans/please-take-your-time-glimmering-stardust.md` § "audit-harness — what's needed" #3

## Goal

Define the JSON Schema 2020-12 envelope for a single Evidence Bundle gate-result row. The row is the unit that audit-harness emits via the Phase B `emit-evidence` subcommand (`AH-3`) and that downstream consumers (j-rig, Rollout Gate GHA) read.

## Design constraints

1. **Schema-versioned.** Every row carries a `schema_version` field so consumers can reject unknown major versions and warn on unknown minor versions.
2. **Forward-compatible.** Validators MUST accept unknown fields. New fields can be added in minor versions without breaking adopters.
3. **Hash-pinnable.** Fields like `policy_hash` and `input_hash` make tamper-evidence possible at the row level, independent of envelope signature.
4. **Idempotent emission.** Same input produces byte-identical row, modulo `timestamp`. This means generators MUST canonicalize JSON output (sorted keys, fixed numeric precision).
5. **No PII.** Rows MUST NOT carry user-identifying information. The `metadata` object is for machine-readable context (versions, hashes, durations), not human content.

## Field design

### Required fields

| Field | Type | Description |
|---|---|---|
| `gate_id` | string | Stable identifier for the gate. Conventionally `<framework>:<gate-name>` (e.g., `"audit-harness:escape-scan"`, `"audit-harness:crap"`, `"j-rig:eval-spec"`). |
| `result` | enum | One of: `"pass"`, `"fail"`, `"skip"`, `"error"`. `"skip"` indicates the gate was applicable but intentionally bypassed; `"error"` indicates the gate could not produce a verdict. |
| `timestamp` | string (ISO 8601) | UTC timestamp of emission. RFC 3339 format. |
| `schema_version` | string (semver) | Version of THIS schema (envelope contract). Initial value: `"1.0"`. |

### Optional fields

| Field | Type | Description |
|---|---|---|
| `metadata` | object | Implementation-specific context. Recommended sub-fields below. |
| `policy_hash` | string | SHA-256 of the policy file the gate evaluated against (e.g., `tests/TESTING.md` content hash). |
| `input_hash` | string | SHA-256 of the input the gate evaluated (e.g., the diff content for escape-scan). |
| `duration_ms` | integer | Wall-clock duration of gate evaluation in milliseconds. |
| `evidence_uri` | string | URI to a more detailed evidence artifact (e.g., a JSON report file, a log dump). |

### Recommended `metadata` sub-fields

- `framework_version` — version of the tool that produced the row (e.g., `"audit-harness@0.2.0"`)
- `harness_version` — version of the surrounding harness (e.g., `"@intentsolutions/audit-harness@0.2.0"`)
- `repo` — repo URL or path the gate ran against
- `commit_sha` — commit SHA the gate ran against
- `branch` — branch name (informational; not a primary key)
- `ci_run_url` — URL to the CI run that produced the row, if applicable

## Versioning rules

**`schema_version` semver:**

- **Major bump (1.0 → 2.0):** required field removed or renamed; `result` enum loses a value; semantic meaning of an existing field changes
- **Minor bump (1.0 → 1.1):** new optional field added; new value added to `result` enum; new recommended `metadata` sub-field documented
- **Patch bump (1.0 → 1.0.1):** documentation-only changes; no schema delta

**Compatibility:**

- Validators MUST accept unknown fields silently (forward-compat for minor bumps)
- Validators SHOULD warn on unknown major version (`schema_version: "2.x"` when validator only knows `1.x`)
- Validators MUST reject malformed JSON or missing required fields

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
