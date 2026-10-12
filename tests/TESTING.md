# Testing Context — @intentsolutions/audit-harness

This document describes configured checks and measurement limits. Coverage,
mutation and CRAP thresholds are undeclared; no skill defaults become policy.
The complete file is protected by `.harness-hash`. After reviewing a deliberate
change, initialize pins with `node bin/audit-harness.js init` and verify them
with `node bin/audit-harness.js verify`.

## Installed gates (observational)

- **L0:** This repository is the canonical harness source; run
  `node bin/audit-harness.js --version`. It does not depend on its own package.
- **L1:** Lefthook, Beads hooks, staged escape scanning and disposable-worktree
  pre-push checks are configured. The 2026-10-12 audit observed 18 branch-required
  contexts. The maintainer merge guard also checks observed non-advisory jobs;
  this does not require an absent job to appear. Promotion remains a separate
  policy decision.
- **L2:** ShellCheck, Ruff, Python compilation, ESLint, actionlint, markdownlint,
  offline links, typos and CodeQL are wired. Vale is advisory. CI TypeScript has
  no dedicated typecheck.
- **L3:** Bash fixtures, Python `unittest` and Node `node:test` exercise behavior.
  The advisory Python measurement lane described below adds observations, with
  no threshold verdict. Mutation remains unmeasured.
- **L4–L6:** Offline installation, wrapper dispatch, evidence/report contracts,
  injected signing transport, scanner adapters, OSV and CLI smoke have checks.
  Offline fakes do not establish live DNSSEC/Rekor behavior. Browser checks are
  outside the default CLI profile.
- **L7:** SemVer contracts exist; formal requirement traceability is undeclared.

## Frameworks and contributor commands

Run from the repository root. `npm ci` installs locked development dependencies.
Use Python 3.12 with the hash-locked CI requirements for the Python checks.

```bash
npm run check
python3 tests/measurement/test_measurement_baseline.py
python3 tests/measurement/test_measurement_runner.py
bash tests/report-lineage/run-report-lineage-tests.sh
bash tests/emit-evidence/run-emit-evidence-tests.sh
bash scripts/escape-scan.sh --staged
```

`check` runs the supply-chain policy, ESLint, aggregate behavioral suites,
generated applicability check and manifest verification. `npm test` alone runs
the aggregate, including golden/SemVer and the measurement regressions. The two
supplemental shell suites above are also collected by the measurement runner.
Runner tests always exercise unavailable providers and failure propagation;
their real-provider cases run when coverage.py and Radon are installed.

## Advisory Python self-measurement

Use an isolated provider environment without activating it or adding its `bin`
directory to `PATH`; the legacy golden deliberately runs without a Radon
executable. Both requirements files contain exact versions and payload hashes.

```bash
python3 -m venv build/measurement-venv
build/measurement-venv/bin/python -m pip install --require-hashes --only-binary=:all: -r ci/requirements.txt
build/measurement-venv/bin/python -m pip install --require-hashes --only-binary=:all: -r ci/measurement-requirements.txt
python3 ci/run_measurement.py --output-dir build/python-measurement \
  --coverage-python build/measurement-venv/bin/python \
  --complexity-python build/measurement-venv/bin/python
```

Choose a fresh output directory for each run. Artifacts include raw coverage
and complexity, source hashes, provider versions, command logs, `provenance.json`
and `summary.json`/`summary.md`. Behavioral command failures remain failures;
missing metrics produce explicit unavailable diagnostics. CI uploads these
artifacts under `python-self-measurement` and publishes a step summary.

The denominator is canonical `scripts/*.py` plus `tests/**/*.py`, excluding
`tests/fixtures/**`, with production and test observations separated. Eligible
unexecuted files remain in the denominator. Coverage follows Python subprocesses
that inherit startup instrumentation; isolated interpreters, replaced
environments and temporary source copies can remain unobserved. Source identity
and eligible/scored/matched counts must be checked before interpreting results.

Shell, Node, Rust, Python wrappers, CI tooling and packaged mirrors are outside
this baseline. It is not whole-repository coverage. CRAP uses file line coverage
as a function proxy, not measured per-function coverage. Empty results, missing
providers and measured zero coverage are distinct. No pass grade, blocking
threshold, mutation score or required-check promotion is inferred.

## Last audit and traceability (observational)

The diagnostic [TEST_AUDIT.md](../TEST_AUDIT.md) records the 2026-10-12 audit
(`bd_000-projects-b3u6`), before this installation. Its overlapping suite counters
are historical observations, not a current unique-test total or coverage claim.
Formal RTM/persona/journey artifacts are optional for this CLI and undeclared;
their coverage percentages are unavailable. No requirements, personas or
journeys are invented by this installation. Remaining implementation and policy
work is tracked under `bd_000-projects-0wvb`.
