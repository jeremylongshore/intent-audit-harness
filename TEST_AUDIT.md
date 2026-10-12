# Test Audit — @intentsolutions/audit-harness

Date: 2026-10-12. Bead: `bd_000-projects-b3u6`.
Audited source: `735134f3a0bf8a644c5078b70a8b8d87031e2f86` (version 1.5.1).
Scope: canonical scripts, Node dispatcher, bundled Python/Rust wrappers, and
CI-only evidence/signing packages. This is a diagnostic snapshot.

**Result: behavioral suites pass; measurement and enforcement gaps remain.**
Grade: **unavailable**. No deterministic repository grading rubric or measured
coverage denominator was found. The July B+/87 was a historical assessment,
not a current tool result; it is not carried forward or replaced with a
self-assigned score. The [previous report](https://github.com/jeremylongshore/intent-audit-harness/blob/735134f3a0bf8a644c5078b70a8b8d87031e2f86/TEST_AUDIT.md)
retains the July assessment and subsequent bounded remediation.

## Classification and freshness

`node bin/audit-harness.js classify .` detects **CLI**, with no unresolved
classification. Its registry hash is
`sha256:e9e4fbd18fd88bae9bed9a76398497af82369d88f0805bcc2f35435d8f77efc1`.
All eight resolved gates are advisory; required *applicability* does not make
them blocking. No engineer-authored testing policy or waivers were present.
Browser/accessibility and declared-persona/journey audits are outside this
CLI's default requirements; this is not a newly enacted waiver.

Source version and the npm latest-version probe both returned 1.5.1.
`node bin/audit-harness.js verify` passed. `currency --json` reports 18 stale
local records among 19 pins, based on their recorded dates. It does not verify
live upstream compatibility. The initial `currency .` invocation was rejected
(exit 2); the corrected command completed with exit 0 and an advisory report.

## Seven-layer assessment

| Layer | Presence and configuration | Enforcement and limits |
| --- | --- | --- |
| L1 — hooks/CI | Active Beads hooks chain Lefthook; staged escape and disposable pre-push checks exist | 18 GitHub required contexts; some newer jobs are absent from that list |
| L2 — static analysis | ShellCheck, Ruff, Python syntax, ESLint, actionlint, markdownlint, offline links, typos, CodeQL | Several checks required; Vale advisory; no scoped signing TypeScript typecheck |
| L3 — unit/function | Shell fixtures, Python unittest, Node tests | Behavior tested; source coverage, mutation and self-CRAP unmeasured |
| L4 — integration/regression | Offline installation, wrapper dispatch, canonical evidence, signing state transitions | Real local contracts exercised; injected signing transport is not live Rekor delivery |
| L5 — system quality | Hash/escape checks, security adapters, live CI OSV, CodeQL | Local OSV unavailable; one known history secret finding persists |
| L6 — CLI smoke/E2E | SemVer and port-dispatch smoke; rollout dogfood workflow | Smoke exists despite naming heuristic; dogfood consumes a committed fixture, not its emitted live row |
| L7 — acceptance | Public SemVer and signing acceptance assertions | Formal requirement/persona/journey registers undeclared; no external UAT claim |

Sources: [CI](.github/workflows/ci.yml), [hooks](lefthook.yml),
[aggregate](tests/run-core-tests.sh), [SemVer contract](SEMVER.md), and
[dogfood workflow](.github/workflows/rollout-gate-dogfood.yml).

GitHub protection and active rules were read on 2026-10-12 at 16:23Z. The
shipped architecture/bias/port, signing, canonical-payload, supply-chain and
report-lineage jobs run but are not named in the 18-context protection floor.
The maintainer's configured merge guard additionally rejects observed
non-advisory failures; that does not guarantee a missing job will be required.
The prior report's unconditional description of the new jobs as "required"
was too broad. No protection or merge-policy settings changed in this audit.

## Executed evidence

Tests ran in a disposable archive of the exact source commit: all 269 tracked
files were verified byte-identical before execution. This keeps fixture writes
and build products outside the target worktree. Locked CI package dependencies
were installed there with `npm ci --ignore-scripts --no-audit --no-fund`.

| Command or measurement | Observed result |
| --- | --- |
| `npm test` | Exit 0; 17 shell entrypoints and two direct Python entrypoints completed |
| Aggregate counters | 319 reported shell checks and 37 Python tests passed; overlapping counters, not a unique-test total |
| `npm --prefix ci test` | 12 canonical-payload tests passed |
| `npm --prefix ci/signing-reconciler test` | 23 signing tests passed |
| `bash tests/report-lineage/run-report-lineage-tests.sh` | 25 checks passed |
| `bash tests/emit-evidence/run-emit-evidence-tests.sh` | 33 checks passed |
| `conform .` | Exit 0, zero applicable conformance rows; not a substantive conformance pass |
| `audit . --deep` | Two raw PASS rows and one smoke advisory; unit is presence-only and self-CRAP scored zero methods |
| CRAP, JS and Python providers | **Not measured**: missing complexity providers; raw zero-method PASS is not quality evidence |
| Architecture / Gherkin | Exit 2: no architecture configuration / no feature directory; not measured |
| Coverage / mutation | No instrumented repository baseline or declared floor |
| Bias | 25 regex matches / 42 detected functions; fixture/wording false positives make the raw rate unsuitable as a quality grade |
| `scan .` | Two PASS, three ADVISORY; OSV and markdownlint unavailable locally; Gitleaks found one historical item |

The aggregate does not include every independent CI suite; the four supplemental
runs above close that local execution gap for this audit. Live DNS, Rekor,
release publishing, and installed-package distribution tests were not run.
Passing behavioral suites do not establish source coverage percentages.

A redacted full-history Gitleaks run returned exit 10 and the existing finding
at `python/PUBLISH.md:24`, commit `9b97217ab639219bdd81ed6ac11bad5c1485ba62`.
It matches [the open credential incident](https://github.com/jeremylongshore/intent-audit-harness/issues/166),
Bead `bd_000-projects-wcze.4`. This audit does not establish provider revocation,
authorize an allowlist, or clear that release hold.

## Traceability

No formal REQ/MoSCoW register, tagged requirement commits, declared personas,
or declared journeys were found. The 28 inventoried test-source files have no
formal REQ links; several explicitly reference documented contracts instead.
Formal traceability is optional for CLI. Requirement, persona and journey
coverage percentages are **unavailable**, not 100%; no uncovered MUST count
can be inferred from an absent register.

| Documented contract | Related test evidence |
| --- | --- |
| `SEMVER.md` public CLI/output guarantees | `tests/semver/run-semver-tests.sh` |
| Audit-profile union and schema contract | `tests/classify/run-classify-tests.sh` |
| `docs/cred-gate.md` redaction/refusal behavior | `tests/cred-gate/run-cred-gate-tests.sh` |
| `docs/security-scanners.md` operational failures | `tests/scan/test_security_adapters.py` |
| `docs/ci-supply-chain.md` download integrity | `tests/supply-chain/test_policy.py` |
| Signing README transition/outbox contracts | `ci/signing-reconciler/tests/` |

These are bounded source-to-test observations, not a complete requirement
matrix or new policy. `tests/TESTING.md` is absent. An observational draft is
included in the implementation handoff; its creation requires deliberate
manifest initialization because the verifier protects the entire file.

## Findings and implementation handoff

No newly demonstrated P0 from this testing audit; the existing credential
incident remains open. Two P1 work groups go to `bd_000-projects-0wvb`:

1. **Enforcement documentation and intent:** reconcile the missing required
   contexts with the intended merge floor. Preserve all existing checks and
   distinguish configured jobs, observed-failure rejection and required presence.
2. **Measurement validity:** collect an advisory baseline for actual product
   scripts/tests and ensure unavailable providers or zero scored methods cannot
   support a measured-pass claim. Coverage, mutation and blocking thresholds
   remain engineer-owned; copying skill defaults is not a policy decision.
   The legacy zero-method output is golden-tested; preserve its existing
   CLI contract while introducing explicit measurement-status reporting.

P2 recommendations: a scoped signing typecheck; mutation baseline; a pinned
live CI secret scanner after incident disposition; a connected producer-to-
consumer dogfood path; a clearly documented aggregate boundary; upstream-pin
review; and bias false-positive triage. Optional formal traceability remains
an advisory observation. These do not authorize gate promotion or publishing.

The mandatory `implement-tests` handoff uses the existing implementation bead,
not a duplicate task. Order: establish policy/measurement boundaries, address
L1 intent and L3 measurement validity, then consider applicable P2 additions.
The harness is this repository's source product; do not install a second copy
of itself as a runtime dependency. Credential response stays in `wcze.4`.

## Audit change verification

The initial addition of observational `tests/TESTING.md` caused hash verification
to refuse the expanded protected-file set (exit 2); all 97 existing pins still
matched. The draft was removed from this diagnostic diff and retained in the
implementation handoff. No manifest was regenerated and no threshold enacted.

The corrected report-only diff passed hash verification (97 existing pins) and
escape scan (exit 0; zero REFUSE, CHALLENGE or FLAG findings). Markdown lint and
offline local-link checks passed. Source, tests, thresholds, CI, protection,
and contributor guides are unchanged.
