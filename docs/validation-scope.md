# Validation scope

## Audit profiles

Classification and gate resolution use repository contents, the pinned registry,
engineer overrides and classifier version. The emitted profile additionally
records its emission timestamp. Repeated runs do not promise identical full
profile bytes; compare the relevant classifications and gate resolution with
those inputs held constant.

## Marketplace conformance

`conform --tier marketplace` checks the encoded JSON-Schema structural rules in
the pinned authoring projection. It does not execute every semantic requirement
of the broader authoring contract. For example, parent-directory/name matching
and consecutive-hyphen restrictions are prose-only in the snapshot. The
`requires_env`/`fallback_for_env` exclusion is assigned to a separate Zod runtime
by the snapshot, which this command does not run. Passing this gate does not
establish those omitted checks, host behavior or behavioral quality.

The pinned core0.11.0 authoring snapshot's upstream-base comment says the IS
overlay narrows `allowed-tools` to an array. Its actual overlay accepts a string
or an array. The encoded overlay governs this command; the array-only comment
is stale. Preserve the upstream snapshot and its per-file pins byte-for-byte
rather than silently rewriting the third-party contract.

The core0.10.0 EvidenceBundle snapshot serves evidence emission; core0.11.0
authoring schemas serve structural conformance. They are separate surfaces, not
a claim that every kernel contract uses one version.

## Vendored documentation

The installer copies `docs/` when present in the selected release archive so
README's relative documentation links resolve in a consumer. It does not fetch
missing documents from another version. Previously published releases that omit
docs remain unchanged.
