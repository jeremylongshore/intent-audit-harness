# Canonical Dashboard Evidence

The `iah` channel publishes the harness's own release evidence through
`.github/workflows/release.yml`. Its private `ci/package.json` pins
`@intentsolutions/core@0.10.0`, matching the dashboard verifier; the published
harness remains a zero-runtime-dependency CLI.

## Payload and Signed Metadata

`ci/emit-evidence.ts` runs the existing harness-hash self-gate. Each gate result
becomes one kernel-validated in-toto statement inside an `EvidenceBundlePayload`
array. The bundle's `storage_key` hashes that entire canonical array, with object
keys sorted recursively and array order preserved. Its subject set, predicate
types and row count derive from the same payload.

The manifest carries `evidencePayload` alongside the compatible `gateResults`
projection. `ci/assemble-manifest.ts` rejects missing or invalid payloads, signed
metadata mismatches and divergent projections. Canonical rows cannot silently
downgrade to the older body-digest contract. Assembly checks binding consistency;
the existing Cosign verification step and dashboard ingest verify signatures.

## Development Checks

Use Node 22.6 or newer for the CI-only TypeScript emitter:

```bash
npm ci --ignore-scripts --prefix ci
npm test --prefix ci
node --experimental-strip-types ci/emit-evidence.ts --self-check
```

The contract suite exercises canonical byte equality against the shared unsigned
marketplace/dashboard vector, pass/fail/error fixtures, metadata and payload
mutations, compatibility-body drift and missing signature files. These fixtures
are synthetic; they do not establish live measurements or signature verification.
The required `Canonical dashboard evidence contracts` PR job and the release
emitter both run the suite. CI emitter sources, contracts and fixture bytes are
included in `.harness-hash`.

## Publication and Transition

Signing identity and tag-only release triggers are unchanged. A reviewed source
merge does not publish a canonical `iah` manifest: the approved release workflow
must run first. After publication, verify the live manifest's source SHA, payload
digest, metadata and signature, then dashboard ingest and rendered evidence.
Record those receipts under `bd_000-projects-0s2a` before claiming this channel's
transition. The dashboard's legacy compatibility remains until every producer
and retained cache has a verified transition disposition.
