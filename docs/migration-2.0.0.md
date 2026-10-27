# Migrating from 1.5.1 to 2.0.0

This major release includes all 11 source commits after v1.5.1 through
1d54a2be31b0fa023ff5622349d371c5a82a9d7a. Follow SEMVER.md rather than treating
changed existing failure outcomes or text contracts as an invisible patch.

## Before updating CI

Review `scan --fail-closed` callers: required/blocked security measurements must
finish with valid machine evidence. Missing tools, crashes, invalid output and
incomplete analysis now refuse an apparently clean result. Configure the intended
scanner tools and inputs; do not suppress the failure or reduce required gates.
Default advisory scanning remains advisory. Syft artifact persistence is explicit
through `--sbom-output`; required SBOM gates refuse missing/unwritable outputs.

Python module invocations preserve failed-gate exit codes. Architecture failures
with no matching violation lines still produce valid JSON. Existing callers that
accidentally treated a swallowed failure as success need to handle the failure.

## Timeout and cancellation supervision

With a positive AUDIT_HARNESS_TIMEOUT, the Node CLI supervises a POSIX process
group through TERM and bounded KILL cleanup even if the immediate shell exits.
Repeated cancellation escalates. Windows uses bounded taskkill /T /F and reports
cleanup failure. Normal timeout success retains exit 124 and its prior diagnostic.
This does not contain a command that deliberately detaches into another session.
The separate generated shell wrapper does not gain Node watchdog supervision.

## Vendored consumers

Re-run the selected release installer in an isolated candidate, compare copied
payloads/provenance, retain owned protection manifests and rerun owning quality
gates. The installer replaces its vendor directory, so regenerate/review local
BBB supplements separately. Never equate an updated tool version with adoption
of upstream estate policy, semantic authoring rules or Brain governance receipts.
No consumer is upgraded or activated by this release-candidate document.

## Other boundaries

The npm package remains zero-runtime-dependency. Evidence core0.10 and authoring
core0.11 projections retain their distinct purposes. The release incorporates
private CI dependency/security locks, canonical signed dashboard evidence fixes,
verified CI tool/action pins and tests described in CHANGELOG. No Brain database
migration or live service deployment is part of upgrading this development tool.
