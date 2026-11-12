# @intentsolutions/audit-harness

<!-- intent-select-partner:start -->
[![Intent Solutions: Claude Partner Network Select Services Partner](https://raw.githubusercontent.com/intent-solutions-io/.github/b82af5d3e7951d85e39ea9e65cc24ee8278722a7/assets/brand/claude-select-partner.svg)](https://intentsolutions.io/)

Intent Solutions is a Claude Partner Network Select Services Partner.
<!-- intent-select-partner:end -->

[![npm](https://img.shields.io/npm/v/@intentsolutions/audit-harness?color=cb3837&logo=npm)](https://www.npmjs.com/package/@intentsolutions/audit-harness)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Provenance](https://img.shields.io/badge/sigstore-provenance-066da5)](https://www.npmjs.com/package/@intentsolutions/audit-harness)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/U5S225PTME)

Part of the **[Intent Eval Platform](https://github.com/intent-solutions-io/intent-eval-platform)** — the umbrella grouping the platform's six repos: five converge via a shared Evidence Bundle schema (`intent-eval-core`, `intent-eval-lab`, `audit-harness`, `j-rig-skill-binary-eval`, `intent-rollout-gate`), plus `intent-eval-dashboard` as a satellite consumer (not part of the convergence taxonomy).

Deterministic test-enforcement toolkit. Companion to the `audit-tests` and `implement-tests` Claude Code skills — but usable standalone in any repo that wants hash-pinned, escape-scanned, AI-resistant quality gates.

**On "AI-resistant", precisely:** the hash-pin is a *complete* guarantee for the files you pin — they cannot change without an explicit, committed re-pin. The escape-scan is a *heuristic net* over the staged diff: it catches the common escapes (deleted tests, lowered coverage floors, new skip markers, architecture-rule bypasses), not every conceivable dodge. Deliberately not claiming bulletproof.

## What it is

A small CLI dispatching deterministic commands (shell + stdlib-Python scripts), including read-only evidence and report verification:

| Command | Purpose |
|---|---|
| `audit-harness verify` | Verify hash-pinned artifacts haven't changed since `--init` |
| `audit-harness init` | Pin the current state of engineer-owned policy files |
| `audit-harness list` | Show pinned files |
| `audit-harness escape-scan --staged` | Detect AI attempts to lower test thresholds, delete tests, bypass architecture rules |
| `audit-harness cred-gate` | Provider-credential PASS/FAIL gate — FAIL if a declared secret, provider-key shape, or serialized env leaks into the artifact about to be signed |
| `audit-harness arch` | Run language-appropriate architecture-rule checker (dependency-cruiser / import-linter / ArchUnit / deptrac / arch-go) |
| `audit-harness bias` | Count common test-bias patterns |
| `audit-harness gherkin-lint` | Advisory Gherkin quality check |
| `audit-harness crap` | CRAP (Complexity × Coverage) scorer — Python, Go, JS/TS, Rust |
| `audit-harness emit-evidence` | Wrap a gate-result JSON envelope in an in-toto Statement v1 (predicate `gate-result/v1`); `--output FILE` writes one row, `--append-to BUNDLE` appends it to the JSON-array bundle `intent-rollout-gate` consumes |
| `audit-harness classify` | Read-only repo classifier → an `audit-profile/v1` value (never writes) |
| `audit-harness conform` | Read-only conformance gate-runner → `gate-result/v1` rows against bundled content-addressed schemas; `--tier marketplace` checks skills, agents, plugin manifests and marketplace catalogs against their encoded pinned kernel `authoring/v1` contracts (default `--tier floor`: name + description) |
| `audit-harness audit` | Read-only testing-depth gate-runner → coverage presence per pyramid layer + crap-score |
| `audit-harness scan` | Security/hygiene/skill-quality gates; `--fail-closed` requires OSV and profile-required security scanners; optional SBOM export stays outside the audited repo |
| `audit-harness fp-rate` | Measure each gate's false-positive / false-negative rate over a labeled corpus |
| `audit-harness currency` | Advisory poll-freshness report over the per-upstream pin relation |
| `audit-harness migration-notes` | Generate deterministic adopter-facing migration notes from the changelog and SemVer policy |
| `audit-harness report-lineage` | Verify generic Run/Grade/report lineage, arithmetic, and per-cell sample-slot uniqueness; optionally cross-check a J-Rig suite audit manifest; emit promotion metadata for downstream binding |
| `audit-harness gen-layer-applicability` | Project the canonical audit-profile registry into `layer-applicability.md` |
| `audit-harness worktree-run` | Run pre-push gates against an exact ref in a disposable worktree |

## Install

The npm package is the canonical, actively released distribution. The Rust
wrapper remains an optional crates.io distribution.

The command table above describes the npm CLI. `classify` and `conform`, including
their bundled registry and schemas, are supported through npm and `install.sh`.
The Rust and frozen Python wrappers expose only `verify`, `init`, `list`,
`escape-scan`, `arch`, `bias`, `gherkin-lint`, and `crap`; they do not provide
`classify` or `conform`. See the [distribution contract](000-docs/015-AT-DECR-classify-conform-distribution-contract-2026-11-12.md).

**Node / JS / TS** (from npm):

```bash
pnpm add -D @intentsolutions/audit-harness
# or: npm install --save-dev @intentsolutions/audit-harness
# or: yarn add --dev @intentsolutions/audit-harness
```

**Python:** the PyPI package is frozen at `1.4.0` and does not receive releases
starting with `1.5.0`. Do not use it for new estate rollouts; install the npm
package above or use the vendored-script path below.

**Rust** (from crates.io):

```bash
cargo install intent-audit-harness
```

For classification and conformance in Rust or Python projects, use the npm package
or the vendored installer below. The language of the audited project does not
require the same-language wrapper.

**Any other language** (Go, Ruby, PHP, Java, .NET, shell, etc.) — vendor the scripts:

```bash
curl -sSL https://raw.githubusercontent.com/jeremylongshore/intent-audit-harness/main/install.sh | bash
```

The installer prepares a replacement before changing the existing harness or
wrapper. Failed downloads, invalid archives and catchable publication failures
leave the prior installation usable. Archive links/special files and symlink
installation destinations are refused. Explicit versions and offline tarball
URLs remain supported; this validation is not release-signature verification.

A repository-local `.audit-harness-install.lock` serializes installations. On
SIGKILL or power loss, traps cannot restore state: the lock and private
`.audit-harness-install.*` directory remain for inspection. Do not simply delete
them and retry. With no installer running, inspect `previous-tree` and
`previous-wrapper` backups, restore the prior pair if publication was incomplete,
and retain recovery evidence before removing the stale lock. Two destination
renames are recoverable on ordinary failure, not a single atomic filesystem
transaction or a guarantee against concurrent external edits.

**Verified release assets (unreleased):** the next release workflow prepares a
commit-bound installer/archive checksum manifest and Sigstore verification
bundle. Use an independently trusted verifier and expected release commit before
executing either payload. The current `curl | bash` example does not perform that
verification. See the [verified installer contract](000-docs/016-AT-SPEC-verified-installer-release-assets-2026-11-12.md)
for the download, verification and installation sequence; existing releases are
not claimed to contain these assets.

## Quick usage

### Strict CRAP measurement (unreleased)

The opt-in `crap --strict-measurement` mode rejects incomplete measurement
instead of accepting an empty score set. It supports Python functions using Radon
and coverage.py JSON, or TypeScript functions using a caller-installed TypeScript
compiler and Istanbul `coverage-final.json`. Mixed-language scopes are refused.

```bash
audit-harness crap --strict-measurement --lang python --target both \
  --source-glob 'packages/*/src/*.py' --test-glob 'tests/test_*.py' \
  --coverage-json coverage.json --out reports/crap-strict --json
```

Install Radon separately and collect coverage for both requested scopes before
running the command. Repeat the glob options to declare additional files.
Recursive scope discovery rejects symlink directories beneath the resolved
prefix before the first `**`; unrelated package dependency symlinks outside
a requested `src` tree do not expand its scope.
The report distinguishes requested patterns, discovered files/functions and
scored files/functions. Missing providers, unmatched patterns, omitted function
measurements, malformed results, and missing coverage produce incomplete
measurement, not a pass. Exit codes are 0 for complete measurement within the
limits, 1 for measured threshold violations, and 2 for incomplete measurement
or invalid arguments. Existing non-strict commands keep their previous behavior.

Python CRAP uses each file's line coverage as a **function coverage proxy**. It does
not claim function-level coverage or attest that caller-supplied coverage was
executed against the current source. Source and coverage hashes and the Radon launcher hash
bind the inputs observed by this invocation; the launcher hash does not attest
the installed Radon package or its dependencies, and execution provenance remains the
caller's responsibility. Existing threshold options apply; no consumer policy
is automatically promoted by installing this mode.

### Strict TypeScript measurement (unreleased)

```bash
audit-harness crap --strict-measurement --lang typescript --target src \
  --source-glob 'packages/*/src/**/*.ts' \
  --coverage-json coverage/coverage-final.json --out reports/crap-typescript --json
```

The target root must contain `node_modules/typescript/lib/typescript.js` and
Node must be on PATH. The harness adds no npm runtime dependency. Declare scopes
that classify source and tests without overlap; a broad source glob above also
includes colocated tests, which require their own coverage if included. Repeat
explicit globs or paths to match the intended inventory.

The provider inventories body-bearing functions, arrows, methods, constructors
and accessors. Its `typescript-function-decisions/v1` complexity starts at one
and adds conditional/loop/catch/non-default-case decisions, logical operators
and assignments, and optional accesses/calls. Nested functions score separately;
module and class initializer expressions are not claimed as functions.

TypeScript CRAP uses **file statement coverage as a function coverage proxy**.
It does not match remapped Istanbul function spans to AST functions or claim
per-function coverage. Runtime files require coverage, including files without
functions; narrowly proven type-only files are explicitly classified and exempt
from runtime coverage. A requested source/test kind with zero scored functions
cannot pass. Missing/malformed files, counters, source locations or provider
results make measurement incomplete.

Evidence binds source, coverage, helper, Node and compiler-file hashes plus the
compiler version. This identifies observed inputs, not coverage execution
provenance or every installed dependency. Ordinary Vitest coverage excludes its
test files even when configured exclusions are empty: requesting tests requires
a collector that actually covers them. J-Rig adoption remains incomplete until
that evidence exists; this command does not waive it or upgrade consumers.

### Pre-commit hook (`.husky/pre-commit`)

```bash
#!/usr/bin/env sh
pnpm exec audit-harness escape-scan --staged
pnpm exec audit-harness verify
```

### CI workflow (`.github/workflows/ci.yml`)

```yaml
  containment:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: pnpm/action-setup@v5
      - uses: actions/setup-node@v6
        with: { node-version: '20', cache: 'pnpm' }
      - run: pnpm install --frozen-lockfile
      - run: pnpm exec audit-harness verify
      - run: pnpm exec audit-harness escape-scan --range origin/main..HEAD
```

### Dependency security in CI

Install the repository-pinned, checksum-verified OSV binary and run the
dependency gate in fail-closed mode:

```bash
OSV_BIN="$RUNNER_TEMP/osv-bin"
bash node_modules/@intentsolutions/audit-harness/scripts/install-osv-scanner.sh "$OSV_BIN"
export PATH="$OSV_BIN:$PATH"
pnpm exec audit-harness scan --fail-closed --osv-severity-threshold HIGH . \
  > dependency-gate-results.json
```

A supported lockfile requires a measured scan. Missing/crashed scanners and
unparseable results fail. No supported dependency input emits `NOT_APPLICABLE`
only when the repository also declares no dependencies; an unlocked declared
graph fails closed. Production or unknown-exposure findings at HIGH or above
block, while proven development-only findings remain visible for triage. See
[Dependency vulnerability gate](docs/dependency-scanning.md) for the exact
contract, evidence fields, and policy exceptions.

### Engineer workflow — change a policy threshold

```bash
# 1. Edit tests/TESTING.md to change coverage.line from 80 to 75
# 2. Re-init to accept the change
pnpm exec audit-harness init
# 3. Commit the updated manifest alongside the policy change
git add tests/TESTING.md .harness-hash
git commit -m "chore(test): lower coverage floor to 75"
```

## The containment model

The harness enforces this rule: **policy changes must be conscious, not silent.**

Engineer-owned files (`tests/TESTING.md`, package test scripts, CI workflows,
coverage and mutation configs, acceptance features, and architecture rules) are
hashed into a manifest. Any diff that changes their content without a fresh
`audit-harness init` is caught by pre-commit / CI and **REFUSED**. Ordinary
application source is deliberately outside this denominator.

AI agents remain useful (they can read policy, they can implement within constraints). What they can't do is silently weaken the constraints. That's the entire design.

The same walls can close the loop **before a push leaves the machine**:
`audit-harness worktree-run --pre-push` checks the exact ref being pushed in a
disposable `git worktree` — `verify` + `escape-scan` on the push range stay
fail-closed, `conform` + `audit` contribute advisory gate-result/v1 rows — then
removes the worktree. It has no push authority, no LLM stage, and never writes
to the repo. Wire it as a lefthook `pre-push` job (this repo's `lefthook.yml`
is the reference) so CI becomes confirmation instead of discovery.

See `audit-tests/references/philosophy.md` in the companion skill for the full rationale.

## The 7-layer testing taxonomy

This harness sits inside a larger framework:

```text
L7  Acceptance / RTM / Personas / Journeys     ← WHAT are we proving?
L6  E2E / BDD / Visual regression              ← User-level guarantees
L5  Perf / Security (SAST/DAST) / A11y / Chaos ← Non-functional
L4  Integration / Contract / Migration         ← Infrastructure wiring
L3  Unit + Coverage + Mutation + Arch + CRAP   ← Code-level correctness  ← audit-harness lives here
L2  Static analysis / Lint / Types / Secrets   ← Read-only scanning
L1  Git hooks / CI enforcement                 ← The cheapest gate       ← audit-harness enables this
```

The harness commands serve L1 (escape-scan in pre-commit + CI) and L3 (CRAP, architecture, bias, hash-pin).

## Exit codes

Important for CI scripting:

| Exit | Command | Meaning |
|---|---|---|
| 0 | any | Clean |
| 1 | escape-scan | CHALLENGE — requires engineer-approved comment |
| 2 | verify | `HARNESS_TAMPERED` — pinned file changed |
| 2 | escape-scan | REFUSE — pipeline halted |
| 3 | verify | No manifest (fresh repo, not an error) |
| 1 | scan `--fail-closed` | Required measurement failed or a required security/OSV gate has blocking findings |

See [security scanner contracts](docs/security-scanners.md) for Gitleaks and
Semgrep exit/report validation, applicability, and Syft evidence export.
See [CI dependency integrity](docs/ci-supply-chain.md) for action pins, verified
tool downloads, and the CI-only Python and kernel validator lockfiles.

## Language support

Most scripts are language-agnostic (shell + regex). CRAP has per-language backends:

| Language | CRAP | Arch | Notes |
|---|---|---|---|
| Python | radon + coverage.py | import-linter | full support |
| JS/TS | complexity-report + c8 | dependency-cruiser | full support |
| Go | gocyclo + go test -cover | arch-go | full support |
| Rust | rust-code-analysis + tarpaulin | (custom) | coverage integration pending |
| Java/Kotlin | — | ArchUnit | via language-native tooling |
| .NET | — | ArchUnitNET | via language-native tooling |
| PHP | — | deptrac | via language-native tooling |

## License

Apache 2.0 — see [LICENSE](./LICENSE) and [NOTICE](./NOTICE).

**Note:** versions `0.x` shipped under the MIT license. Starting with `v1.0.0`, the project is licensed under Apache 2.0. Existing `0.x` releases on npm remain available under their original MIT terms; new releases (`>= 1.0.0`) are Apache 2.0.

## Related

- [`audit-tests` Claude Code skill](https://github.com/jeremylongshore/intent-audit-harness#related) — diagnostic pipeline that uses this harness
- [`implement-tests` Claude Code skill](https://github.com/jeremylongshore/intent-audit-harness#related) — filesystem-mutating installer that installs this harness as part of L1/L3 setup

## Versioning

SemVer. Breaking changes to the CLI surface bump major; new commands bump minor; bug fixes bump patch.

## Contributing

This is infrastructure code. Changes need to be conservative. Before opening a PR:

1. Read `audit-tests/references/philosophy.md` (in the companion skill) to understand the escape-grammar design
2. Run `bash scripts/escape-scan.sh --staged` on your own diff — yes, the harness tests itself
3. Add test cases if you're adding a new pattern to escape-scan or a new command to the CLI

### Validation and vendored documentation scope

See [validation scope](docs/validation-scope.md) for timestamp/classifier inputs,
structural conformance limits and the pinned snapshot’s allowed-tools prose
discrepancy. The installer copies available `docs/` alongside README so its
relative documentation links remain usable. Older archives without docs remain
installable; this does not add files to previously published releases.

### Published authoring conformance

`audit-harness conform . --tier marketplace` checks discovered skill and agent
frontmatter, plugin manifests and marketplace catalogs against the unmodified
published `@intentsolutions/core@0.11.0` authoring/v1 compositions and shared
folds. Invalid artifacts produce advisory findings by default; `--strict` turns
measured violations into failures. Existing default floors for skills, agents,
plugins and MCP are unchanged; default catalog conformance and hook conformance
in either tier remain unmeasured. Agent and plugin inputs retain their existing
whole-object shapes and discovery paths; this does not broaden locator coverage
or add MCP or hook envelope projections.

The pin identifies the package archive and every bundled schema byte. Its hash
binds the selected policy in each result. Expanding this shared manifest also
changes the policy hashes of previously supported marketplace-tier rows,
although their schema bytes and rules are unchanged. Missing or changed schema bytes,
unresolved/recursive references, and unsupported reachable assertion keywords
produce an explicit indeterminate advisory instead of a passing verdict. This
is the encoded published v1 structural contract, not the internal v2 contract,
source-directory existence checks, license ratification, or the skills' rubric.
The 120 upstream catalog, agent and plugin fixtures are retained with their exact
tag, commit and hashes and checked against a reference JSON Schema validator in the existing
conformance suite. This proves parity on that corpus, not arbitrary-schema
equivalence. The reference explicitly enables URI format assertions with the hash-locked
CI-only RFC validator and verifies that it rejects a known invalid URI. The
existing embedded URI/URL check remains lexical and does not establish complete
URI validity. The published skill schema explicitly reserves its
`x-mutually-exclusive-fields` annotation for generated Zod; that existing
cross-field carve-out remains outside structural conformance. Other unknown
keywords are not implicitly admitted. No production JSON Schema dependency or
network fetch is added.
