# Dependency vulnerability gate

`audit-harness scan` uses OSV-Scanner v2 as the universal dependency engine. It
detects supported lockfiles and manifests before invoking the scanner, so every
run has an explicit outcome:

- no supported dependency input and no declared dependencies: `NOT_APPLICABLE`;
- declared dependencies without a supported lockfile/manifest: unmeasured, and
  `FAIL` in `--fail-closed` mode;
- measured and clean: `PASS`;
- measured findings below policy or proven development-only findings: `ADVISORY`;
- production or unknown-exposure findings at/above the threshold: `FAIL` in
  `--fail-closed` mode;
- missing scanner, crash, malformed JSON, or “no packages” despite a detected
  input: `FAIL` in `--fail-closed` mode.

The default threshold is `HIGH`. Change it explicitly with
`--osv-severity-threshold LOW|MEDIUM|HIGH|CRITICAL`. A finding with unknown
severity or an ecosystem whose production/development group cannot be proven is
treated conservatively as release-blocking in fail-closed mode. `--strict`
retains its older, stronger meaning: every finding fails, including
development-only findings.

## CI installation and execution

The shipped installer pins OSV-Scanner 2.5.1 and verifies the upstream binary's
SHA-256 before placing it in an explicit directory:

```bash
OSV_BIN="$RUNNER_TEMP/osv-bin"
bash node_modules/@intentsolutions/audit-harness/scripts/install-osv-scanner.sh "$OSV_BIN"
export PATH="$OSV_BIN:$PATH"
pnpm exec audit-harness scan --fail-closed --osv-severity-threshold HIGH . \
  > dependency-gate-results.json
```

Run this lane on pull requests, release tags, and a schedule. Preserve the JSON
as a CI artifact or pipe individual rows into `audit-harness emit-evidence`.
`metadata` records the scanner version, exact command, discovered input paths,
policy config paths, finding counts, exposure classifications, and bounded
finding details. `input_hash` covers the sorted dependency input paths and
bytes; `policy_hash` includes the threshold contract and any
`osv-scanner.toml` files.

OSV `dependency_groups` are authoritative when the ecosystem supports them.
Known `dev`, `test`, and `build-requires` groups are reported as development
exposure. Lack of group support is recorded as `unknown`, never guessed into a
pass.

## Policy exceptions

Use a colocated `osv-scanner.toml` for a reviewed, reasoned, and preferably
expiring vulnerability exception. OSV applies configuration by lockfile
directory; the harness includes every discovered config in the policy digest.
Do not append `|| true` to the scan lane. If emergency break-glass is required,
use the existing explicit kill-switch and record the exception in project
governance.

`npm audit` may run as a second npm-specific signal, but it does not replace OSV
and must not manufacture a pass for non-npm repositories.
