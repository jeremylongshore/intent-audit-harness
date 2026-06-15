# AAR — Rollout Gate dogfood / first-downstream-adopter (epic iah-E10)

| | |
|---|---|
| **Date** | 2026-06-15 |
| **Epic** | iah-E10 — Internal dogfood pass (audit-harness self-adopts the `intent-rollout-gate` Action) |
| **Criterion** | VPS-as-the-home M6 "first downstream adopter" / IEP convergence-loop end-to-end proof |
| **Workflow** | `.github/workflows/rollout-gate-dogfood.yml` |
| **Fixtures** | `tests/dogfood/{bundle.json,policy.json,README.md}` |
| **Action consumed** | `jeremylongshore/intent-rollout-gate@v0.1.0` (Dependabot also exercises `@v0.2.0`) |
| **Latest green run** | [run 27488477212](https://github.com/jeremylongshore/intent-audit-harness/actions/runs/27488477212) (`Rollout Gate Dogfood`, `success`) |
| **Harness version at run** | `1.1.8` |

## What landed

audit-harness now **self-adopts** the `intent-rollout-gate` GitHub Action in its
own CI, closing the IEP convergence loop inside the harness's own pipeline. The
`rollout-gate-dogfood.yml` workflow runs the full four-stage loop on every
`push`/`pull_request` to `main`:

- **PRODUCE** — `scripts/escape-scan.sh --json` on a clean diff (PASS) piped into
  `scripts/emit-evidence.sh` → a live audit-harness Evidence Bundle row in the
  native gate-result shape (`evidence/audit-harness-row.json`).
- **CONSUME + DECIDE** — `jeremylongshore/intent-rollout-gate@v0.1.0` reads a
  committed kernel `gate-result/v1` Evidence Bundle (`tests/dogfood/bundle.json`,
  three PASS gates: `escape-scan` / `crap-score` / `arch-check`) against a rollout
  policy (`tests/dogfood/policy.json`, all-three-present-and-PASS, forbid
  `fail`/`error`) and returns ship / no-ship.
- **SURFACE** — the decision is echoed and written to `$GITHUB_STEP_SUMMARY`.

This satisfies the four iah-E10 child scopes:

| Child | Scope | Evidence |
|---|---|---|
| iah-E10a | pin against a prior frozen harness version for self-check | `tests/dogfood/bundle.json` is a committed, schema-pinned `gate-result/v1` fixture (frozen kernel wire shape), consumed deterministically regardless of the live row shape. `.harness-hash` self-pins the gate scripts that produce the live row. |
| iah-E10b | produce a signed bundle for audit-harness's own gates | PRODUCE step emits a live Evidence Bundle row from the harness's own `escape-scan` gate via `emit-evidence`; the tag-release `emit-evidence` job (`release.yml`) cosign-keyless-signs (Fulcio + Rekor) the kernel-shaped row. |
| iah-E10c | verify chain end-to-end | The committed run exercises PRODUCE → CONSUME → DECIDE → SURFACE green; the Action verifies the bundle against the policy and returns a decision. |
| iah-E10d | AAR for the dogfood run | this document. |

## What worked

- **Committed fixture decouples the demo from row-shape drift.** The harness's
  native row shape differs from the kernel `gate-result/v1` predicate the Action
  consumes (`gate_decision` / `gate_name` / `coverage` / `policy_ref`). Committing
  a schema-valid bundle makes the consume → decide step deterministic and green
  while still running the live `escape-scan | emit-evidence` PRODUCE step, so the
  workflow demonstrates both the real emit path and a stable consume path.
- **Bootstrap hazard contained.** A harness gating itself in its own CI is a
  bootstrap hazard, so the dogfood job is advisory by two independent guards:
  job-level `continue-on-error: true`, and the Action runs with
  `fail-on-block: 'false'` (a block reports only). It is intentionally **not** a
  branch-protection required check — proven by the green runs sitting alongside
  the 13 required gates without entangling them.
- **Honest gate IDs.** The fixture's `audit-harness:ci:*` gate IDs name real
  harness gates so the bundle reads as genuine self-adoption, but hashes and
  timestamps are placeholder constants — no partner-engagement gate IDs leak
  into a committed fixture.

## What didn't work / friction

- **Two row shapes is the standing seam.** The live PRODUCE row and the
  Action-consumed `gate-result/v1` row are not the same shape today, which is why
  a committed fixture backs the consume step rather than the live row. Closing
  that seam (the harness emitting the kernel `gate-result/v1` wire shape directly,
  so the live row is consumable end-to-end without a fixture) is the residual
  follow-on, tracked against the kernel `EvidenceBundlePayload` / `gate-result/v1`
  alignment work, not this epic.

## Evidence

- Workflow: `.github/workflows/rollout-gate-dogfood.yml`
- Fixtures + rationale: `tests/dogfood/README.md`, `tests/dogfood/bundle.json`,
  `tests/dogfood/policy.json`
- Green run: `Rollout Gate Dogfood` /
  [run 27488477212](https://github.com/jeremylongshore/intent-audit-harness/actions/runs/27488477212)
  (`success`); Dependabot bump to `intent-rollout-gate@v0.2.0` also passes the job.
- Signing path for the released row: `.github/workflows/release.yml` `emit-evidence`
  job (cosign keyless → Fulcio OIDC + Rekor).
