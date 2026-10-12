# CI dependency integrity

All workflow `uses:` references carry full commit SHAs and readable version or
snapshot comments. Dependabot retains GitHub Actions coverage and also watches
the CI-only npm and Python manifests under `ci/`. Review its proposed source and
lockfile changes together; changing a comment does not update executable bytes.

`ci/downloads.json` pins the Linux x86_64 Actionlint and ShellCheck archives.
`ci/install-tool.py` checks the complete download's SHA256 before reading one
named regular-file member. It never extracts archive paths, and a corrupt
archive or symlink member leaves an existing executable intact. Actionlint's
initial pin was cross-checked against its upstream checksum list; ShellCheck's
pin records the reviewed official release asset. OSV retains its existing
platform-specific checksum-verifying installer.

Python CI tools use `ci/requirements.txt`: exact versions and wheel hashes for
CPython 3.12 on Linux x86_64, including transitive dependencies. The evidence
emitter uses `npm ci --ignore-scripts --prefix ci` against the committed kernel
validator lockfile. Published runtime dependencies remain empty. Regression
tests use the committed, hash-pinned predicate schema and fail if it is missing;
they no longer download a substitute from upstream `main`.

To validate a change:

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r ci/requirements.txt
python3 ci/check-supply-chain.py
python3 tests/supply-chain/test_policy.py
node bin/audit-harness.js init
npm run check
```

The policy checks repository-declared actions, direct download commands, and
package installation boundaries. Third-party action internals and package-manager
transport verification remain delegated to their reviewed implementations.
Notification POSTs remain allowed. The policy and installer have regression
tests for mutable references, unlocked installs, malformed workflows, corrupt
archives, symlink members and archive path traversal.

For archive upgrades, verify the new release through its upstream publication,
record the expected SHA256 and member in `ci/downloads.json`, run the installer
and tests, and regenerate the reviewed harness hash. Never accept a new digest
automatically after a download mismatch. No dependency update publishes a release.
