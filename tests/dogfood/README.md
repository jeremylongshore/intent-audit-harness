# Rollout Gate Dogfood fixtures

These fixtures back `.github/workflows/rollout-gate-dogfood.yml`, the M6
first-downstream-adopter demonstration in which **audit-harness self-adopts the
`intent-rollout-gate` GitHub Action**.

| File | What it is |
| --- | --- |
| `bundle.json` | A representative Evidence Bundle in the kernel `gate-result/v1` wire shape (plain in-toto Statement v1 array). Three audit-harness gates (`escape-scan`, `crap-score`, `arch-check`), all `gate_decision: "pass"`. |
| `policy.json` | A rollout policy requiring all three gates to be present and PASS, forbidding `fail`/`error` decisions. |

## Why a committed fixture instead of a live bundle

The dogfood workflow also runs the harness's **live** `escape-scan --json |
emit-evidence` to prove audit-harness emits real Evidence Bundle rows. But the
`intent-rollout-gate@v0.1.0` Action consumes the **kernel `gate-result/v1`
predicate shape** (`gate_decision` / `gate_name` / `coverage` / `policy_ref`…),
which differs from the harness's native row shape. Committing a schema-valid
fixture guarantees the consume → decide step is deterministic and green in CI
regardless of the live row's shape, while still demonstrating the full
produce → consume → decide → surface loop.

## Advisory-only

The workflow is bootstrap-protected: it runs on push/PR to demonstrate adoption
but **never blocks** audit-harness CI (job-level `continue-on-error: true` plus
the Action's `fail-on-block: 'false'`). It is intentionally not a
branch-protection required check.

## Gate IDs are synthetic-but-self-referential

The `audit-harness:ci:*` gate IDs name real harness gates so the fixture reads
as audit-harness self-adopting, but the hashes/timestamps are placeholder
constants — no partner-engagement gate IDs appear here.
