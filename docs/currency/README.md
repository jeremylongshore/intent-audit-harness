# Upstream observations and retained references

`audit-harness currency` is an offline advisory report. Its `current` status
means only that `checked_at` is within the configured poll window. It does not
mean latest, compatible, adopted, released or deployed.

The existing `currency-pins/v1` relation and `currency/v1` report support three
optional fields:

- `pin_kind` describes whether the retained value is a snapshot baseline,
  historical release reference, compatibility reference or unverified reference.
- `latest_observation` records an observation timestamp, outcome, extracted value
  and a repository-relative evidence path plus its identity lookup key.
- `review_disposition` gives a status and reason. `retained` means preserve the
  reference for the stated scope; `pending` leaves a semantic/adoption decision
  unresolved; `indeterminate` means the observation cannot establish its intended
  signal. None of these statuses changes freshness or approves adoption.

These fields are descriptive evidence, not an authenticated attestation. Legacy
rows without them keep their existing report shape. The CLI does not fetch,
write, initialize references or promote policy. Existing SLA resolution, status
values and advisory exit behavior remain unchanged. Invalid input files still
produce an input error.

When present, observation and disposition records must be objects. Observations
require nonempty `observed_at`, `outcome`, `value` and `evidence` strings;
`observed_at` is an ISO date or timestamp and `outcome` is `observed` or
`indeterminate`. Evidence is a repository-relative path, optionally followed by
an identity fragment; optional `evidence_identity` must be a nonempty string.
Dispositions require a documented `status` and nonempty `reason`. Reference kinds
must be one of the four kinds listed above. Both output modes reject malformed
metadata with input-error exit 2 before printing any report; stale, valid data
still exits 0. Evidence paths are descriptive and are never opened by the report.

Advance `checked_at` only after supported reverification of that specific
reference and scope. Change `pinned_version` only after a deliberate baseline or
contract update. A successful HTTP response alone is an observation. A newer
release, unchanged feed ID or matching Lab digest cannot certify other surfaces.

## 2026-10-26 evidence

[The evidence record](reverification-2026-10-26.json) covers all 18 identities
reported stale on that date, using 20 successful primary-source fetches. Each
source records URL, final URL, timestamp, response status, byte length, full
body SHA-256 and its extracted signal. Exact raw responses were inspected in
private local artifacts; they are not redistributed here. The record preserves
bounded extracted values and hashes for comparison, without claiming that a
future fetch of a mutable URL reproduces those bytes. It is not a signed receipt.

The 16 Lab surface comparison attempts use the named extractor contract at fixed commit
`dd42d4598b4ef1eadef143b31ef5eab1e2de6d13`. Raw-body digests and extractor-output
digests are recorded separately and coincide for raw-byte extractors. Eleven
computed projections differ from that Lab baseline; four byte-match. Engineering
is indeterminate because the relative article-link
sentinel is absent. This is byte comparison, not semantic compatibility. In
particular, the current MCP schema matches the Lab snapshot but differs from the
older prefix retained by this harness.
The two internal-contract identities have no Lab comparison.

All 19 original `pinned_version`, `checked_at`, class and poll-window values are
preserved. All 18 previously stale identities still report stale. Their
observations and retained, pending or indeterminate dispositions are now visible;
this work does not clear stale flags by changing dates. A retained disposition
with an old date deliberately remains stale until its precise scope is
reverified and recorded. Pending semantic comparisons remain tracked by
`compile-then-govern-8pg`.

The bundled MCP config schema checks launch/config structure, not wire protocol
revision. The SKILL frontmatter floor checks a required name/description pair and
known optional field types; the enterprise rubric and pinned marketplace kernel
remain distinct. No third-party schema, snapshot, runtime dependency or consumer
version is adopted by these observations.

[The bounded SKILL comparison](skill-floor-comparison-2026-10-26.json) binds the
retained Lab baseline, captured current standard and bundled structural schema.
All three require the same name/description pair. This establishes required-set
equality only. Five actual validator probes demonstrate that the bundled floor
accepts uppercase names, consecutive hyphens, overlong names/descriptions and an
array of allowed tools, where the open standard documents stricter constraints.
The floor also lacks parent-directory context. The historical baseline already
documented those constraints: these are existing scope limits, not evidence of
new upstream regressions. All original pin values and freshness dates remain
unchanged; the comparison does not complete the remaining semantic reviews.

## Release classification

The changed default text is a **major** CLI change under [SEMVER.md](../../SEMVER.md).
It must ship in the next major release, with the [adopter migration notes](MIGRATION-2.md).
This source change does not publish a release or update consumer installations.
