# Currency text migration for the next major release

This is an unreleased major change under [the CLI SemVer contract](../../SEMVER.md).
It must not be published as a 1.x minor or patch update. Release preparation,
version alignment and approval remain tracked separately in
`compile-then-govern-wwq`; this document does not authorize publication.

## What changes

Default `audit-harness currency` text can include observation and disposition
lines after a retained reference. Its stale-summary guidance also changes for
legacy references: observations do not justify automatically bumping a version
and checked date together. Exact-text parsers need migration even though the
existing freshness calculation, statuses and advisory exit behavior are preserved.
No stored data migration is required.

## Migrate text parsers to JSON

Use `audit-harness currency --json` and select the documented fields instead of
counting lines or matching the old summary sentence. For example:

```bash
audit-harness currency --json | python3 -c 'import json, sys; report = json.load(sys.stdin); print(report["stale_count"])'
```

The envelope remains `currency/v1`, with `advisory: true`, `stale_count`, `by_class`
and `pins`. Existing row fields retain their meanings: `pinned_version` is the
retained reference, `checked_at` is its retained recorded check date, and `status`
is its poll freshness. Optional `pin_kind`, `latest_observation` and
`review_disposition` fields describe evidence separately. Consumers must tolerate
absent optional fields and additional future fields.

A recent observation does not make a stale reference current. A pending or
indeterminate disposition is not compatibility approval. Currency remains
advisory; callers must not infer a readiness or deployment verdict from exit 0.

## Adoption and rollback

Keep an existing published 1.x version pinned until the major release and parser
migration have been reviewed. A source checkout or shell-vendored copy can expose
unreleased changes; inspect its owning commit rather than assuming the package
version establishes published behavior. The source change does not update such
consumers automatically.

Rollback means restoring the previously selected package or vendor commit through
normal dependency review. There is no runtime database or state migration to undo.
The separately held release candidate must be regenerated and revalidated against
the final merged source before any exact-head release approval is requested.
