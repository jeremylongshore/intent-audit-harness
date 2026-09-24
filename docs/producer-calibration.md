# Producer-aware calibration for pattern gates

Pattern and deny-list gates are only as fail-closed as the population used to
calibrate them. A rule tuned on producer A can miss a new failure fingerprint
from producer B while continuing to emit green results. The gate has not
failed loudly; its coverage has silently become unknown.

This applies to voice-lint lists, slop/bias lists, escape-scan patterns, and
other rules whose signal is learned from observed output. It does not mean that
every structural rule is producer-sensitive. It means the gate owner must make
that decision explicitly.

## What audit-harness knows

`audit-harness fp-rate` measures false positives and false negatives over a
labeled `valid/` + `malformed/` corpus. It is read-only and deterministic. The
report is evidence for the existing promotion rule in
[`gate-promotion.md`](./gate-promotion.md), but the command does not know who
produced a fixture and does not infer population coverage.

Producer identity and calibration scope therefore remain engineer-owned
provenance. A downstream gate may keep this record beside its rule definition,
in its test manifest, or in its evidence bundle. The fields below are the
recommended minimum; they are guidance, not a new CLI input format.

```yaml
calibration_id: voice-lint-v1-2026-08-02
gate_id: content:ci:voice-lint
rule_id: banned-phrase-catalog
rule_kind: deny-list
producer_population:
  id: producer-a-v3
  description: synthetic staging outputs from the primary producer family
  scope: first-party editorial fixtures, not production customer content
sample:
  count: 120
  window: 2026-07-01/2026-08-01
  corpus_sha256: sha256:<hash-of-canonical-labeled-corpus>
method:
  fp_fn_measurement: audit-harness-fp-rate
  new_producer_vetting: not-run
  gate_version: ruleset-17
metrics:
  false_positive_rate: 0.0083
  false_negative_rate: 0.0417
review:
  reviewer: human-owner
  reviewed_at: 2026-08-02T00:00:00Z
  status: advisory
```

The `producer_population.id` must be stable and versioned without embedding a
secret or personal data. `scope`, `count`, `window`, `corpus_sha256`, and
`gate_version` make a later result reproducible. Keep the labeled corpus
canonical before hashing it; a hash of an undocumented moving directory is not
useful provenance.

## New-producer vetting

Run this procedure before treating an existing blocking pattern gate as
coverage for a new producer or materially different author population:

1. Declare the new producer/population and freeze the current rule version.
   Do not silently expand the rule list while collecting the baseline.
2. Select a representative first `N` artifacts, with `N` chosen before
   sampling. Use at least 30 when the population permits, or all available
   artifacts when fewer exist. Record the exact count and sampling window.
3. Run the unchanged gate and independently label the artifacts. Preserve both
   the gate verdict and the human label; a green result is not evidence that a
   new failure mode is absent.
4. Hand-diff missed failures and new false positives against the existing
   producer corpus. Turn each confirmed new fingerprint into a regression
   fixture before changing the rule.
5. Re-run `audit-harness fp-rate --json` over the old and new strata together,
   and review the per-producer counts. A blocking promotion still needs the
   existing FP bar (normally `--max-fp-rate 0.05`) plus a recorded human review.
6. Write the provenance record with the corpus hash, gate version, metrics,
   reviewer, and status. Until this exists, mark the new population
   `needs-recalibration`; do not report the blocking gate as proven coverage
   for it. The downstream release/promotion owner must fail closed or keep the
   known-good producer path when that status is missing.

The vetting step may discover that a rule is not portable across producers. In
that case, split the rule or maintain producer-scoped rule records. Do not
solve a coverage gap by weakening the shared deny-list.

## Evidence and privacy boundaries

- Keep real customer, partner, and private-brain material out of calibration
  fixtures and provenance records. Synthetic or explicitly authorized data is
  the default.
- Record hashes and counts, not raw artifacts or credential values.
- A missing producer record is an uncertainty signal, not a PASS.
- `audit-harness` remains vendor-neutral: it provides deterministic measurement
  and hash-pinned policy surfaces; the downstream producer identity and human
  disposition are supplied by the gate owner.

This guidance addresses the producer-fallback failure mode tracked in
[intent-audit-harness#129](https://github.com/jeremylongshore/intent-audit-harness/issues/129).
