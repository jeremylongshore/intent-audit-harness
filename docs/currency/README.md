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

The 16 Lab surface comparisons use the named extractor contract at fixed commit
`dd42d4598b4ef1eadef143b31ef5eab1e2de6d13`. Raw-body digests and extractor-output
digests are distinct. Eleven computed projections differ from that Lab baseline;
four match. Engineering is indeterminate because the relative article-link
sentinel is absent. This is byte comparison, not semantic compatibility. In
particular, the current MCP schema matches the Lab snapshot but differs from the
older prefix retained by this harness.

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
