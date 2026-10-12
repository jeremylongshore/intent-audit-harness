# Security scanner contracts

`audit-harness scan` distinguishes policy findings from an unmeasured gate.
The profile selects applicable tools; the harness does not choose or download
new scanner rules. `--fail-closed` requires security gates whose applicability is
`required` or whose enforcement is `blocking`. Missing executables, execution
errors, unsupported adapters, invalid reports and incomplete analysis produce `FAIL` with
`metadata.indeterminate: true` in that mode. Optional gates remain advisory.
An explicitly waived gate returns `NOT_APPLICABLE` without running its tool.

| Tool | Measured result | Operational failure |
|---|---|---|
| Gitleaks | JSON array; exit 0 with no findings, reserved exit 10 with findings | Any other exit, malformed rows, or exit/report disagreement |
| Semgrep | JSON `results` and `errors` arrays; exit 0 clean, exit 1 with findings | Other exits, malformed rows, or any reported analysis errors |
| Syft | Syft JSON with artifacts, source, descriptor and schema metadata | Nonzero exit, malformed SBOM, or a required artifact that cannot be preserved |

Findings stay `ADVISORY` by default. `--strict`, profile `blocking` enforcement,
or a required gate under `--fail-closed` makes them `FAIL`. Operational failure
stays distinct: an unavailable scanner is not proof of either clean code or a
vulnerability. Existing OSV severity/exposure rules remain documented in
[dependency scanning](dependency-scanning.md).

The Gitleaks adapter sets `--exit-code 10` because its default exit 1 also
represents errors. It requests a redacted JSON report. Semgrep runs with JSON,
`--error`, metrics disabled and version checking disabled. Evidence rows retain
the command, bounded version identifier, exit code and finding count; they never
copy scanner stderr, secrets, matched source lines or rule messages. Reports
larger than 16 MiB are refused. The execution deadline is 300 seconds. A local
tool build without version metadata reports `unknown`; the adapter does not
substitute compiler or SBOM schema versions.

## Preserve a Syft SBOM

Create an output directory outside the audited repository, then pass its path:

```bash
mkdir -p /tmp/harness-evidence
audit-harness scan --fail-closed --sbom-output /tmp/harness-evidence/sbom.json .
```

The profile must include the `syft` gate; this flag does not add one. A valid
report is saved atomically, with a `file:` URI and exact-byte `sha256:` digest in
the row. Archive that file with the gate-result JSON in CI. Invalid reports,
symlinked output files, and targets inside the audited repository are refused;
existing artifacts survive a failed scan. Parent directories must already exist.
A required Syft gate needs this output path. In ordinary advisory mode, an
omitted path preserves only the digest and package count in the row.

The synthetic CLI fixtures run with `bash tests/scan/run-scan-tests.sh`, also
included in `npm run check`. They cover clean results, findings, missing tools,
crashes, incomplete/malformed reports, sensitive-output suppression, and SBOM
preservation/refusal.

Contract references: [Gitleaks exit codes](https://github.com/gitleaks/gitleaks#exit-codes),
[Semgrep CLI reference](https://docs.semgrep.dev/cli-reference), and
[Syft output formats](https://oss.anchore.com/docs/guides/sbom/getting-started/).
