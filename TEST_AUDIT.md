# TEST_AUDIT.md — @intentsolutions/audit-harness

> Diagnostic produced by `/audit-tests` (7-layer + gate sweep). Date: 2026-07-13.
> Scope: the deterministic test-enforcement toolkit itself — the scanners under
> `scripts/` (escape-scan, hash-pinning, CRAP, architecture, bias, gherkin-lint,
> classify/conform/audit/scan, cred-gate, currency, migration-notes), the Node CLI
> dispatcher (`bin/`), the Python (PyPI) + Rust (crates.io) port wrappers, and the
> CI-only `ci/signing-reconciler/` sub-package. **The scripts are the product** —
> so the load-bearing question is whether the harness tests its own scanners.

## Grade: B+ (87/100)

A genuinely strong, broadly-gated posture — **21 CI jobs** in `ci.yml` plus 5 more
workflows, hard-fail `shellcheck` + `ruff`, a per-scanner golden/fixture suite for
almost every gate, a live SemVer CLI-contract freeze, and self-dogfooding
(`self-check` + `rollout-gate-dogfood`). Everything that runs, passes: **all 11
offline suites + 9 static/self-checks verified green locally.** Held below A by a
real **P1 meta-gap** — the newest and most security-sensitive subsystem
(`ci/signing-reconciler`, the Rekor OUTBOX + SkillVersion signing state machine)
has a **23-test suite that no workflow runs** — and a cluster of P2s where two
*shipped* scanners (`arch-check.sh`, `bias-count.sh`) have no behavioral tests,
the port wrappers are untested, and the toolkit that advertises "coverage-gate"
and "mutation-testing" applies neither to itself. For an ordinary app these are
minor; for a *test-enforcement product* an untested shipped scanner is the
physician-heal-thyself finding, so it weighs heavier.

## Classification

**Polyglot CLI + test-enforcement tooling.** The product is the ~5,166 lines of
`scripts/*.{sh,py}` scanners, dispatched by a zero-runtime-dep Node CLI
(`bin/audit-harness.js`) and mirrored by thin Python (PyPI) and Rust (crates.io)
port wrappers that bundle byte-identical script copies. A separate CI-only,
non-published Node/TS sub-package (`ci/signing-reconciler/`) carries the Rekor
signing runtime. Deterministic, offline, read-only by design — so the natural
test shape is **golden-master + fixture** (input dir → expected JSON / stdout),
not classic mocked unit tests, and coverage is asserted by fixture breadth rather
than an instrumented percentage.

## 7-layer presence / config / enforcement

| Layer | State | Evidence |
|---|---|---|
| L1 — git hooks & CI | ✅ HARD | `lefthook.yml` local pre-commit (escape-scan `--staged`, ruff, shellcheck, eslint) + 21 CI jobs (`.github/workflows/ci.yml`) + 5 workflows (actionlint, codeql, doc-quality, rollout-gate-dogfood, typos) |
| L2 — static / lint / types | ✅ HARD | pinned `shellcheck v0.10.0` (hard-fail, all `scripts/*.sh`), pinned `ruff 0.15.4` (hard-fail), `py_compile`, `eslint` (recommended), `actionlint`, CodeQL, `typos`, Vale, markdownlint |
| L3 — unit / function | ✅ | golden/fixture suites per scanner: classify, conform, audit, scan, crap-score, currency, migration-notes, cred-gate, gherkin-lint (via golden); crap-score adds a Python join-regression + a standalone `test_crap_score_joins.py`. **Gap:** `arch-check.sh`, `bias-count.sh` have no behavioral suite |
| L4 — integration | ✅ HARD | `regression` suite pipes escape-scan → emit-evidence → in-toto Statement → kernel schema validation; `wrapper-sync` (bundled mirrors byte-identical to canonical); `version-canonical-check` (4 polyglot manifests aligned); `kernel-shadow-check` |
| L5 — system quality | ✅ | `self-check` matrix (node 18/20/22): `verify` / `list` / `harness-hash --verify` (hard-fail on tamper) / synthetic threshold-lowering escape-scan; `dns-preflight` live leg env-gated |
| L6 — E2E / acceptance | ✅ | `rollout-gate-dogfood` emits a live Evidence Bundle row → consumes bundle + policy → ship/no-ship decision (the harness gating itself end-to-end); `golden` suite pins raw scorer stdout as a downstream contract |
| L7 — acceptance / business | ✅ | `semver` suite pins the public CLI/output surface as live assertions — frozen subcommand roster, frozen exit codes, `--json` stream contract, frozen `gate-result/v1` predicate URI; a MAJOR-worthy change shipped as MINOR/PATCH fails |

## Deterministic gates (all verified locally 2026-07-13)

| Gate | Result |
|---|---|
| shellcheck `scripts/*.sh` (pinned, hard-fail) | PASS |
| ruff check (pinned, hard-fail) | PASS |
| py_compile (all `scripts/*.py`) | PASS |
| regression suite (escape-scan / emit-evidence / schema) | PASS |
| semver CLI-contract suite | PASS |
| golden-master stdout (gherkin-lint + crap-score) | PASS |
| classify / conform / audit / scan golden suites | PASS (4/4) |
| crap-score suite + `test_crap_score_joins.py` | PASS |
| currency / migration-notes / cred-gate suites | PASS (3/3) |
| dns-preflight (non-live) | PASS |
| harness-hash `--verify` (hash-pin idempotency) | OK |
| wrapper-sync (bundled mirror byte-identity) | PASS |
| kernel-shadow-check (advisory) | PASS (0 shadows) |
| gen-layer-applicability `--check` (projection drift) | PASS |
| `ci/signing-reconciler` `npm test` (23 tests) | PASS locally — **but run by NO workflow** |

## Gaps

**P0:** none. Every gate that ships is green; the core product scanners are tested.

**P1 — the reconciler suite is dead in CI:**

- `ci/signing-reconciler/tests/{cli,outbox,reconcile}.test.ts` = **23 `node --test`
  cases, all passing locally, invoked by zero workflows** (`ci.yml` and `release.yml`
  never `cd ci/signing-reconciler`). This is the newest and most security-sensitive
  subsystem — the append-only Rekor OUTBOX + bounded-retry reconciler for the kernel
  SkillVersion signing state machine (CISO P0-RATIFY-2, landed #124/#127), whose own
  tests assert fail-closed invariants ("kernel-invalid rows are NOT persisted"). A
  regression here ships undetected. **Fix:** add a `signing-reconciler` job to
  `ci.yml` — `cd ci/signing-reconciler && npm ci && npm test` on node ≥22.6.

**P2 — the meta-gap (an under-tested enforcement toolkit is a real finding):**

- **`arch-check.sh` (185 loc) and `bias-count.sh` (151 loc) have no behavioral
  tests.** They are shipped, advertised scanners ("architecture checks, bias
  detection") yet the only coverage is a source-grep portability guard in the
  regression suite (`arch-check` must use the cross-platform `SHA256_CMD` pattern) —
  a logic regression in either would pass CI. Add `tests/arch/` + `tests/bias/`
  golden fixtures (clean-repo pass + seeded-violation fail), matching the
  classify/scan pattern.
- **The Rust port (`rust/src/main.rs`) has 0 test functions; the Python port
  dispatcher (`cli.py` / `__main__.py`) has no `test_*.py`.** `wrapper-sync`
  byte-checks the bundled `crap-score.py` mirror, but the port dispatch logic (arg
  routing, script resolution, exit-code propagation) is untested — and both are
  *published* artifacts (crates.io + PyPI). Add a smoke test per port asserting
  subcommand dispatch + exit-code passthrough.
- **No coverage or mutation instrumentation on the scanners.** The golden/fixture
  strategy is legitimate for deterministic scanners, but there is no coverage % — so
  the exact fraction of the 5,166 script lines exercised is unknown, and the package
  advertises `coverage-gate` + `mutation-testing` as keywords while applying neither
  to itself (the self-application / dogfood gap). Advisory: add a `bashcov`/`coverage
  run` pass over the suites to quantify the meta-gap, then decide whether to gate.
- **`npm test` at the repo root is a no-op smoke** (`bash scripts/escape-scan.sh
  --staged || true`) — the real suites are the per-scanner runners wired individually
  into CI jobs. A contributor running `npm test` gets a misleading green. Cosmetic:
  point root `test` at an aggregate runner (or document that CI is the real gate).

## Handoff

**Recommended.** The P1 (reconciler suite unwired) is a one-job CI fix and should
land first. The P2 arch/bias behavioral suites are the highest-value follow-on —
they close the physician-heal-thyself hole for a product whose entire value
proposition is test enforcement. Route to `/implement-tests` for the `tests/arch/`
and `tests/bias/` fixtures plus the port smoke tests.
