# Gate promotion — advisory → blocking

Every gate in the [dimension→gate registry](../schemas/audit-profile/registry.v1.json) ships `enforcement: advisory`. Advisory means: the gate runs, emits its `gate-result/v1` row, logs any finding — and **exits 0**. It never reddens a build. Blocking (`enforcement: blocking`, exit 1 on violation) is **earned**, not default.

This is deliberate. A gate that blocks before its false-positive rate is known erodes trust, and trust-erosion ends one way: someone appends `|| true` and the gate is dead. Advisory-first + earned-promotion keeps every blocking gate credible.

## The rule

A gate may be promoted to `blocking` for a repo when **all** hold:

1. **Measured FP-rate below the bar.** Run the [FP-rate harness](../scripts/fp-rate.py) over a labeled corpus and confirm the gate's false-positive rate is **≤ 5%** (the default bar). A false positive is a *clean* input the gate wrongly flags — the failure mode that destroys trust.

   ```bash
   audit-harness fp-rate                      # human-readable report
   audit-harness fp-rate --json               # machine-readable
   audit-harness fp-rate --max-fp-rate 0.05   # exit 1 if any gate exceeds the bar
   ```

   The labeled corpus is `tests/fixtures/conform/{valid,malformed}/` (extend it: a gate is only as trustworthy as the corpus it was measured on — `valid/` inputs must stay clean, `malformed/` inputs must get flagged).

2. **Engineer-pinned in the repo's policy.** Promotion is an engineer decision recorded in the target repo's hash-pinned `tests/TESTING.md` — never inferred by a tool, never proposed by an AI. The classifier reads the per-gate `enforcement` override from the engineer-owned `.audit-harness.yml` (`advisory:` / `disable_gates:` lists) and the policy in `tests/TESTING.md`; the registry default stays `advisory`.

3. **Re-pinned manifest.** After editing the policy, re-init the hash manifest so the change travels with the code and `escape-scan` won't REFUSE a later legitimate edit:

   ```bash
   audit-harness init                         # re-pin after an engineer-reviewed policy edit
   git add .harness-hash tests/TESTING.md     # commit policy + manifest together
   ```

4. **Producer coverage, when the rule is producer-sensitive.** A deny-list or
   pattern gate calibrated on one model, author, or generator is not proven for
   a new producer merely because the old corpus still meets the FP bar. Record
   the producer population, corpus hash, rule version, metrics, and human
   disposition, then run the new-producer vetting procedure in
   [`producer-calibration.md`](./producer-calibration.md). An unvetted
   population is `needs-recalibration`, not a green coverage claim.

## Why FP-rate, not FN-rate, is the promotion gate

A false **negative** (a real problem the gate misses) is a coverage gap — annoying, but advisory output still surfaces it elsewhere and the gate can tighten over time. A false **positive** on a blocking gate halts a correct build, and the human response is to route around the gate permanently. So promotion is gated on FP-rate; FN-rate is reported for visibility but does not block promotion.

## Demotion / kill-switch

Promotion is reversible without ceremony:

- Per-gate, per-repo: list the `gate_id` under `advisory:` or `disable_gates:` in `.audit-harness.yml`.
- Whole-repo break-glass: `AUDIT_HARNESS_DISABLE=1` (gates no-op; `classify` emits an all-disabled profile; `conform` emits `[]`).

A blocking gate that starts throwing false positives in the field should be demoted to advisory immediately, then re-measured before re-promotion.

## Provenance

Each emitted `gate-result/v1` row records the `policy_hash` (sha256 of the policy/schema the gate evaluated against), so any promotion decision is auditable back to the exact policy version that produced the measurement.
