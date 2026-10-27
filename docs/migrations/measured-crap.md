# Measured CRAP and read-only deep audit

Status: proposed next-major behavior. Source merge is held until the matching
MAJOR version is approved and aligned with the other pending harness changes.
The published 1.5.1 artifact and existing consumer copies are unchanged by this
patch. Release preparation and security prerequisites remain separate work.

Previously a missing collector, unsupported TypeScript input, empty partition
or collector parse failure could collapse into an empty list and PASS. A deep
audit trusted exit zero, emitted an empty input hash and let the child create
`reports/crap` inside its subject. Python and Go could also generate coverage
or run tests when no coverage artifact existed.

The proposed behavior is:

| Scorer observation | Result and exit |
| --- | --- |
| Every requested partition has candidate files and usable method measurements for all those files; thresholds pass | PASS, 0 |
| A measured method or production average exceeds an unchanged threshold, including in partial scope | FAIL, 1 |
| Missing/failed/malformed collector, no scored methods or any candidate file without method evidence | ADVISORY, 2 |
| Requested partition contains no candidate source files | ADVISORY, 2, explicit `empty` partition status |

`--target src` can measure production independently when no tests exist; default
`both` cannot silently turn an empty test partition into a measured test PASS.
Source-only declarations and files with zero methods remain explicitly
unresolved rather than being counted as measured methods. The native collector
fixtures cover Python, Go, JavaScript, TypeScript-shaped report output and Rust;
these fixtures do not certify that a particular installed third-party tool can
parse all TypeScript or Rust syntax. Unsupported syntax remains unmeasured.

Python traverses Radon methods, closures and inner classes, deduplicates identical
function identities and compares the resulting name/line inventory to source AST
definitions. Class aggregate complexity cannot stand in for its methods. Go joins
coverage by normalized file, declaration line and function name, preserving a
low-coverage function when a later function in the same file is fully covered.
Python and JavaScript still use file-coverage proxies, not exact per-method
execution coverage; this patch does not certify those proxies as method coverage.
Rust traverses nested function spaces and excludes container aggregates, matching
Mozilla's [serialized FuncSpace source](https://github.com/mozilla/rust-code-analysis/blob/d388d91854a6d74d4719e0182689a21d0e7abf21/src/spaces.rs)
and [documented console JSON export](https://mozilla.github.io/rust-code-analysis/commands/metrics.html).
The fixture verifies this source-described hierarchy; no Rust toolchain was
installed or executed for these controls.

The scorer's JSON gains requested partitions, candidate-file/method counts,
partition status/reason and the conservative coverage policy. Missing joined
coverage still uses zero as a conservative bound; it is not reported as observed
execution coverage. Consumers must inspect the result and measurement metadata,
not just the presence of a report or threshold values. Update integrations that
assumed every zero-method run exits zero. No gate predicate URI or kernel schema
is redefined by these tool-specific metadata fields.

`audit --deep` now passes `--read-only --json` and a temporary output directory
outside the subject to the scorer. `--read-only` refuses an output path within
the subject and never invokes coverage generation or `go test`. Existing coverage
is consumed where available. Temporary reports are removed after their structured
result is read; their removed path is omitted from the audit row. The audit row
retains the child's input/policy hashes and measurement counts. Missing, malformed,
contradictory or timed-out child output yields ADVISORY indeterminate. Measured
threshold violations retain the existing advisory/blocking/strict handling.

Standalone `crap` keeps its explicit report-writing behavior. Use an external
`--out` and `--read-only` when inspecting a subject without generating coverage.
Existing complexity tools are still external programs; this is not a sandbox for
untrusted replacement executables. No network installation or provider call is
introduced.

Verification: `bash tests/crap-score/run-crap-score-tests.sh` exercises positive
native-output adapters, missing tools, zero/partial/empty measurement, malformed
collector/child output, measured failures and subject-content preservation.
`bash tests/audit/run-audit-tests.sh` retains the ordinary audit contracts.
The no-provider golden intentionally changes from PASS to ADVISORY; review its
diff as a breaking contract correction, not a test waiver.
