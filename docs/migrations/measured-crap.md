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
| A measured method or a complete production-partition average exceeds an unchanged threshold, including when another partition is unmeasured | FAIL, 1 |
| Missing/failed/malformed collector, no scored methods or any candidate file without method evidence | ADVISORY, 2 |
| Requested partition contains no candidate source files | ADVISORY, 2, explicit `empty` partition status |

`--target src` can measure production independently when no tests exist; default
`both` cannot silently turn an empty test partition into a measured test PASS.
The deep-audit adapter always requests both partitions: a repository without
test candidates receives ADVISORY, never PASS, even with fully measured production.
Exit 2 now means unsupported language or indeterminate measurement; integrations
that previously interpreted it only as unsupported language must inspect metadata.
Source-only declarations and files with zero methods remain explicitly
unresolved rather than being counted as measured methods. Hand-authored fixtures
exercise the Python, Go and JavaScript collector output formats, TypeScript-shaped
reports, and the Rust hierarchy derived from upstream source. These are adapter
controls, not captured toolchain runs or certification of installed third-party
parsers. One additional Go receiver-method fixture uses actual Go 1.27.3
`go tool cover -func` stdout captured offline; its complexity rows remain
synthetic. Bare coverage names join two same-named receiver methods by their
distinct declaration lines. Other Go versions are not certified by that capture.
Unsupported syntax remains unmeasured.
Collection uses the same candidate-file partition as discovery, including tests
beside production files. Each file is validated independently, so an unavailable
or malformed different file cannot erase a known method-threshold violation.

Discovery now walks the entire subject for the selected language extensions,
excluding dot-directories and the scorer's explicit build/cache/vendor exclusions,
rather than selecting only conventional source/test roots. Files under `tests/`,
`test/`, `spec/`, `specs/` or `__tests__/`, names beginning `test_`, names ending
`_test.py` or `_test.go`, and names containing `.test.` or `.spec.` are tests.
Every other candidate is production, including root-level `setup.py`,
`conftest.py`, `noxfile.py` and files under `scripts/`. A single unparseable
candidate makes its partition unmeasured; individual known failures still fail.

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
Maximum scores with no scored methods and averages without a complete production
partition are `null`, not measured zeroes. A partial subset's average cannot
prove the complete project's average exceeds its floor; known individual-method
violations still fail. A complete production average remains enforceable when
the test partition is empty or unmeasured.

`audit --deep` now passes `--read-only --json` and a temporary output directory
outside the subject to the scorer. `--read-only` refuses an output path within
the subject and never invokes coverage generation or `go test`. Existing coverage
is consumed where available. Temporary reports are removed after their structured
result is read; their removed path is omitted from the audit row. The audit row
retains the child's input/policy hashes and measurement counts. Missing, malformed,
contradictory or timed-out child output yields ADVISORY indeterminate. Measured
threshold violations retain the existing advisory/blocking/strict handling.

The changed `scripts/audit.py` adapter is dispatched by the Node package only.
The current Python and Rust command tables do not expose `audit` or bundle
`audit.py`; their six bundled gate scripts include the synchronized scorer.
This patch does not add a deep-audit command to those wrappers. The existing
scorer `--json` option (separate from report-file `--format json`) prints the
structured stdout envelope consumed by the adapter.

Standalone `crap` keeps its explicit report-writing behavior. Use an external
`--out` and `--read-only` when inspecting a subject without generating coverage.
Existing complexity tools are still external programs; this is not a sandbox for
untrusted replacement executables. No network installation or provider call is
introduced.

Verification: `bash tests/crap-score/run-crap-score-tests.sh` exercises positive
collector-format adapters, missing tools, zero/partial/empty measurement, malformed
collector/child output, measured failures and subject-content preservation.
`bash tests/audit/run-audit-tests.sh` retains the ordinary audit contracts.
The no-provider golden intentionally changes from PASS to ADVISORY; review its
diff as a breaking contract correction, not a test waiver.
