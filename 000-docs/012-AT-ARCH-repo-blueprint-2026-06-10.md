---
title: Repo Blueprint — intent-audit-harness
date: 2026-06-10
authors:
  - Jeremy Longshore (Intent Solutions)
status: NORMATIVE
binding_authority: iah-E01
inherits_from:
  - intent-eval-lab/000-docs/011-AT-ARCH-ecosystem-master-blueprint.md (Blueprint A)
  - intent-eval-lab/000-docs/012-AT-ARCH-platform-runtime-blueprint.md (Blueprint B)
  - intent-eval-lab/000-docs/013-AT-SPEC-repo-blueprint-template.md (Blueprint C — this template)
related_drs:
  - 004-AT-DECR (S1Q5 — provider PASS/FAIL gates; N/A here, no provider surface)
  - 010-AT-DECR (S4 — unification thesis BINDING; every validator emits Evidence Bundle)
  - 018-AT-DECR (S5 — kernel-canonical gate-result/v1 schema; @j-rig/* v2.0.0)
related_glossary:
  - intent-eval-lab/000-docs/014-DR-GLOS-canonical-glossary.md
filing_standard: Document Filing Standard v4.3
---

# Repo Blueprint — intent-audit-harness

**Beads:** `bd_000-projects-8x5`

## § 1 — Repo identity

| Field              | Value                                                                                          |
| ------------------ | ---------------------------------------------------------------------------------------------- |
| **Repo name**      | `intent-audit-harness` (matches `gh repo view`; local working-dir name is `audit-harness`)     |
| **Type**           | `runtime` (deterministic-gates runner; polyglot CLI + scripts)                                 |
| **Owner**          | `@jeremylongshore` per `CODEOWNERS`                                                            |
| **Maturity**       | `v1.x production` (published `@intentsolutions/audit-harness@1.1.7`; npm + PyPI + crates)       |
| **Ecosystem role** | Emits `gate-result/v1` Evidence Bundle rows from deterministic, content-addressed gates.        |
| **Bead prefix**    | `iah-` (per Blueprint A § 2.1 taxonomy)                                                         |
| **Plane module**   | IAH project / Intent Eval Platform module                                                       |

### 1.1 Dependencies (peer repos consumed)

| Peer repo            | Consumed at | Pinned range            | Cited blueprint                                                        |
| -------------------- | ----------- | ----------------------- | --------------------------------------------------------------------- |
| `intent-eval-core`   | CI-only     | `@intentsolutions/core@0.2.0` (installed `npm i --no-save`) | `intent-eval-core` kernel schemas `schemas/v1/gate-result.schema.json` |

The runtime tarball stays zero-dependency. The kernel is consumed **CI-only** by the signed-evidence emitter in `ci/` (excluded from `package.json#files`); `dependencies` + `devDependencies` stay empty.

### 1.2 Non-goals (inherited + repo-specific)

This repo inherits every anti-goal locked in Blueprint A § 3 (NOT a generalized autonomous agent platform; NOT a workflow automation competitor; NOT a distributed compute platform; NOT a no-code builder; NOT infinite orchestration; NOT trying to be the union of every adjacent category; AISE 5-domain stack is internal scope-map, NOT separate-brand surface). In addition, this repo specifically does NOT:

- Execute the target repo's test suite (running arbitrary untrusted suites is the target repo's own CI's job; the harness reports *presence* and emits gate rows, never the execution verdict).
- Provision test infrastructure (`apply` is `/implement-tests`'s job — the harness stays read-only).
- Make behavioral judgments (LLM-as-judge verdicts come from `j-rig`; the harness only `consume`s a j-rig verdict, never produces one).

Scope-creep into any item above triggers ISEDC re-convene per Blueprint A § 2.3 governance routing.

---

## § 2 — Problem statement

An engineer cannot ship a Skill, plugin, or code change with a *reproducible* quality verdict unless the gates that produced it are themselves content-addressed, hash-pinned, and emitted as signed evidence. Hand-rolled, per-repo gate scripts drift silently; their thresholds get lowered under deadline pressure; and their output cannot be re-verified by an auditor without the original tooling.

`intent-audit-harness` is the **deterministic-gates layer** of the platform (Blueprint A § 2.1). It runs a fixed set of policy-driven gates (escape-scan, CRAP, architecture, harness-hash, bias-count, gherkin-lint, plus the read-only `classify`/`conform`/`audit`/`scan`/`currency` verbs) and emits each result as a `gate-result/v1` in-toto Statement row. The boundary: it produces deterministic gate rows; it hands off behavioral judgment to `j-rig` and ship/no-ship decisions to `intent-rollout-gate`.

---

## § 3 — Scope boundaries

### 3.1 In scope

What this repo ships, end-to-end:

- The polyglot gate toolkit: `scripts/*.sh` + `scripts/*.py`, dispatched by the thin Node CLI `bin/audit-harness.js`.
- Hash-pinning discipline (`harness-hash.sh` + `.harness-hash` + `.harness-hash-extra-patterns`) that gates byte-changes to the policy surface.
- The read-only audit brain: `classify` (audit-profile/v1) + `conform` / `audit` / `scan` / `currency` gate-runners.
- `emit-evidence` → a `gate-result/v1` predicate over an in-toto Statement v1, and the CI-only signed-evidence emitter (`ci/emit-evidence.ts` + `ci/assemble-manifest.ts`).
- The vendored-install path (`install.sh`) for non-Node repos.

### 3.2 Out of scope (permanent, no FUTURE flag)

- Test-suite execution — running the target repo's tests. The harness reports coverage *presence*; the repo's own CI produces the execution verdict.
- Behavioral / LLM-as-judge evaluation — that is `j-rig`'s domain; the harness only consumes a j-rig verdict.
- Infrastructure provisioning / `apply` — that is `/implement-tests`'s domain.

### 3.3 Deferred (FUTURE flag required)

| Deferred item                         | Earliest milestone | FUTURE.md reference                  |
| ------------------------------------- | ------------------ | ------------------------------------ |
| `kernel-shadow-check` subcommand      | `iah-E04`          | blocked on `iah-E02` architecture Q  |
| `--json` flag across all subcommands  | Phase B            | master plan § build journey M2       |

### 3.4 Anti-goals (binding-scope-control)

- **Inherited from Blueprint A § 3**: NOT a generalized autonomous agent platform; NOT a workflow automation competitor; NOT a distributed compute platform.
- **Repo-specific — no test execution**: the harness must never run a target repo's arbitrary test suite. The failure mode prevented is supply-chain code-execution through a quality gate.
- **Repo-specific — no behavioral judgment**: the harness must never emit an LLM-as-judge verdict. The failure mode prevented is non-determinism leaking into a row whose entire value is that it is reproducible.

---

## § 4 — Architecture

### 4.1 Module layout

```text
intent-audit-harness/
├── bin/            — Node CLI dispatcher (audit-harness.js); thin per design rule 1
├── scripts/        — the gates (the policy): *.sh + *.py; source of truth
├── ci/             — CI-only signed-evidence emitter (emit-evidence.ts, assemble-manifest.ts); NOT in the tarball
├── schemas/        — bundled schemas: audit-profile/, conform/v1/, currency/
├── tests/          — golden suites per verb (audit/, classify/, conform/, currency/, scan/, regression/)
├── python/         — PyPI packaging (intent-audit-harness)
├── rust/           — crates packaging (intent-audit-harness)
├── docs/           — gate-promotion + usage references
├── 000-docs/       — numbered design + AAR docs (this blueprint)
└── install.sh      — vendored-install path for non-Node repos
```

### 4.2 Data flow

A gate is invoked through the dispatcher, which resolves the command to a script in `scripts/` and execs it (`bash` or `python3`). Each gate reads policy from the target repo's `tests/TESTING.md` (never a hardcoded number), evaluates, and prints either a human summary (text mode) or a partial `gate-result/v1` envelope (`--json`). `emit-evidence.sh` augments the partial envelope (timestamp, runner, commit_sha) into an in-toto Statement v1. In CI, `ci/emit-evidence.ts` runs the real self-gate, shapes a kernel `gate-result/v1`, cosign-signs the canonical bytes (Fulcio OIDC + Rekor), and `ci/assemble-manifest.ts` assembles the `report-manifest.json` the dashboard re-verifies at ingest.

### 4.3 Runtime boundaries

| Concern                          | Specification                                                                      |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| **Process model**                | single-process CLI; each gate is a short-lived subprocess (bash or python3)         |
| **IPC**                          | stdin-stdout JSON (gate `--json` output → `emit-evidence` augmentation pipeline)    |
| **External services consumed**   | CI-only: Fulcio (OIDC keyless signing) + Rekor (transparency log). None at runtime. |
| **Process isolation guarantees** | gates run in the invoking shell; no credential broker boundary (no provider surface) |

### 4.4 Storage needs

| Storage class | Backing store | Retention | Reference |
| ------------- | ------------- | --------- | --------- |
| (none)        | N/A           | N/A       | The harness persists nothing; it emits rows consumers persist. |

### 4.5 External dependencies (cite by version)

| Dependency                  | Range                                   | Purpose                         | Notes                                              |
| --------------------------- | --------------------------------------- | ------------------------------- | -------------------------------------------------- |
| Node                        | `>=18`                                  | CLI dispatcher runtime          | zero npm runtime deps per design rule 2            |
| `python3` (+ `radon`/`gocyclo`) | system                              | `crap` scorer + read-only verbs | optional; absent → ADVISORY indeterminate, never FAIL |
| `@intentsolutions/core`     | `0.2.0` (CI-only, `npm i --no-save`)    | kernel `gate-result/v1` schema  | excluded from the published tarball                |

### 4.6 Failure boundaries

- **Crash boundary**: a gate subprocess failure is local to that gate; the dispatcher reports the exit code and does not corrupt other gates.
- **Retry boundary**: gates are deterministic and idempotent — re-running a gate on identical input yields identical output; no retry policy is needed.
- **Isolation guarantees**: a missing optional tool (radon, semgrep, gitleaks) yields an ADVISORY indeterminate row, never a false FAIL — downstream consumers are protected from a tool-absence flake.
- **Emitted FailureTaxonomy categories**: N/A — this repo does not emit `FailureTaxonomy` rows.

---

## § 5 — Canonical entities used

| Entity           | Direction | Blueprint B Ref     | Attributes implemented                                                                  | Glossary ref                              |
| ---------------- | --------- | ------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------- |
| `EvidenceBundle` | produces  | `Blueprint B § 2.4` | `gate-result/v1` predicate rows (in-toto Statement v1; subject content-addressed; no top-level bundle signature) | `014-DR-GLOS-canonical-glossary.md` § 2.4 |

**Entities NOT touched by this repo:** EvalSpec, EvalRun, MatcherMap, JudgeDecision, RuntimeReceipt, RegressionPack, RolloutGate, SkillSnapshot, SessionTrace, ToolInvocation, CostRecord, FailureTaxonomy. The harness only produces `gate-result/v1` rows that compose into an EvidenceBundle; it does not read or persist any other canonical entity.

---

## § 6 — Interfaces

### 6.1 CLI

```text
audit-harness <subcommand> [flags] [args]
```

| Subcommand              | Purpose                                         | Exit codes                                                        |
| ----------------------- | ----------------------------------------------- | ----------------------------------------------------------------- |
| `verify` / `init` / `list` | hash-pin manifest verify / init / enumerate | `0` OK / `2` HARNESS_TAMPERED / `3` no-manifest                   |
| `escape-scan <source>`  | scan a diff for threshold-lowering escape attempts | `0` clean / `2` REFUSE                                          |
| `arch` / `bias` / `gherkin-lint` | architecture / bias / Gherkin advisory checks | `0` pass / non-zero on violation                          |
| `crap [args]`           | CRAP complexity×coverage scorer (requires python3) | `0` under floor / non-zero over floor                          |
| `emit-evidence`         | augment a partial gate envelope → in-toto Statement v1 | `0` valid / `1` malformed input                            |
| `classify [repo]`       | emit an `audit-profile/v1` value (read-only)    | `0` always (emits JSON to stdout)                                 |
| `conform` / `audit` / `scan` / `currency` | read-only gate-runners → `gate-result/v1` rows | `0` advisory / non-zero under `--strict`        |

### 6.2 HTTP / gRPC APIs

N/A — no network server.

### 6.3 Config files

| File                        | Schema                                              | Canonical example          |
| --------------------------- | --------------------------------------------------- | -------------------------- |
| `tests/TESTING.md` (target) | policy thresholds (coverage floor, CRAP, kill rate) | the consuming repo's copy  |
| `.harness-hash`             | sha256 manifest of pinned files                     | this repo's `.harness-hash` |
| `schemas/audit-profile/registry.v1.json` | gate-set registry (classify)           | bundled in-repo            |

### 6.4 Output formats

| Output              | Shape                                                                | Reference         |
| ------------------- | -------------------------------------------------------------------- | ----------------- |
| Evidence Bundle row | in-toto Statement v1; predicate body `gate-result/v1` per Blueprint B § 7.4 | `Blueprint B § 7` |
| Plain-text fallback | `escape-scan: REFUSE=N CHALLENGE=N FLAG=N` summary line              | n/a               |

### 6.5 Event schemas

N/A — this repo does not emit OpenTelemetry events. Forward-reference `iel-E12` if/when emit-evidence gains span emission.

### 6.6 Public-API stability promise

- **CLI command names** — once shipped, commands are not renamed or repurposed; new ones are added, removals get a 2-minor-version deprecation window (design rule 3).
- **Exit-code grammar** — `0` success / `2` blocking violation / `3` no-manifest is stable across minor bumps.
- **`gate-result/v1` predicate shape** — owned by the kernel; the harness conforms to it, never redefines it.

Breaking changes to any of the above require a MAJOR bump (Blueprint A § 4.2) AND a Class-2 pair Decision Record before merge.

---

## § 7 — Testing strategy

### 7.1 L0 — git hooks (pre-commit)

- **In-scope checks**: escape-scan on the staged diff, hash-pin verify, partner-name grep guard.
- **Enforcement**: `node bin/audit-harness.js escape-scan --staged` (this repo dogfoods its own dispatcher). Vendored consumers use `scripts/audit-harness escape-scan --staged`. NEVER `~/.claude/` paths.

### 7.2 L1–L2 — static analysis (lint + typecheck + escape-scan)

- **Lint**: shellcheck (pinned `v0.10.0`) on `scripts/*.sh`; ruff (pinned `0.15.4`) on Python.
- **Typecheck**: N/A — the runtime is shell + stdlib-Python; `ci/*.ts` is CI-only and typechecked by its own toolchain.
- **Escape-scan**: `node bin/audit-harness.js escape-scan --staged`.

### 7.3 L3 — unit tests

| Concern                | Target                                                            |
| ---------------------- | ---------------------------------------------------------------- |
| **Framework**          | bash golden suites (`tests/*/run-*-tests.sh`) + Python `py_compile` |
| **Coverage floor**     | N/A — golden-suite coverage of every verb's stdout/exit grammar  |
| **Mutation kill rate** | N/A — mutation testing is layer-inapplicable to the gate scripts |
| **CI gate**            | the per-verb golden jobs in `.github/workflows/ci.yml`           |

### 7.4 L4 — integration tests

- The regression suite (`tests/regression/run-regression.sh`) exercises escape-scan → emit-evidence → schema validation end-to-end inside the repo.
- Each read-only verb has a golden suite that runs the script against checked-in fixtures and diffs stdout / exit code.

### 7.5 L5 — system tests

- CI-only signed-evidence emit (`ci/emit-evidence.ts`) touches Fulcio + Rekor on tag push (sigstore).
- **Provider PASS/FAIL gates**: N/A — see § 8.3.

### 7.6 L6 — acceptance tests

| Concern           | Specification                                                      |
| ----------------- | ----------------------------------------------------------------- |
| **Gherkin scope** | N/A — the harness LINTS `.feature` files; it ships none of its own |
| **Lint**          | `node bin/audit-harness.js gherkin-lint`                          |
| **RTM**           | N/A                                                               |

### 7.7 L7 — chaos / property / fuzz

- **Applicability**: N/A — deterministic gate scripts with fixed-input golden suites; no property surface that warrants fuzz harnessing yet.

### 7.8 CI gates

```text
node bin/audit-harness.js verify
node bin/audit-harness.js list
bash scripts/harness-hash.sh --verify
shellcheck scripts/*.sh        # pinned v0.10.0
ruff check                     # pinned 0.15.4
bash tests/<verb>/run-<verb>-tests.sh   # per-verb golden suites
bash tests/regression/run-regression.sh
```

**Hash-pin discipline**: after any byte change to a pinned file (`scripts/*.sh`, `scripts/*.py`, `bin/audit-harness.js`, `.harness-hash-extra-patterns`), re-run `bash scripts/harness-hash.sh --init` and commit the regenerated `.harness-hash` in the same commit. The `harness-hash --verify` CI step refuses an unsigned policy edit (exit 2). `.github/workflows/ci.yml` is NOT in the pin scope.

### 7.9 Fixtures

| Concern                       | Specification                                                              |
| ----------------------------- | ------------------------------------------------------------------------- |
| **Location**                  | `tests/fixtures/` + per-verb fixture dirs (`tests/<verb>/`)               |
| **Naming convention**         | descriptive per fixture (`clean.diff`, `refuse.diff`, `has-tests/`, etc.) |
| **Vendor-generic discipline** | scrubbed per DR-004 S1Q2; the partner-name guard runs in CI               |

### 7.10 Golden files

Golden stdout/exit suites per verb. Regenerations are reviewed line-by-line in PR; no mass-regenerate path exists.

---

## § 8 — Security / isolation

### 8.1 Secrets management

| Secret class | Storage | Broker | Repo-specific |
| ------------ | ------- | ------ | ------------- |
| (none at runtime) | N/A | N/A | The harness handles no secrets; CI signing uses keyless Fulcio OIDC (no long-lived key). |

### 8.2 Sandbox model

No sandbox required — no user-code execution path. The harness reads files and diffs and emits rows; it never executes the target repo's code.

### 8.3 Provider PASS/FAIL gates

N/A — this repo does not touch LLM providers. Section present per Class-1 ISEDC requirement that the gate-restatement be visible even when not exercised.

### 8.4 Audit logging

| Concern            | Specification                                                              |
| ------------------ | ------------------------------------------------------------------------- |
| **What is logged** | gate verdict emissions; CI signing events (cosign → Rekor inclusion proof) |
| **Append-only**    | yes — Rekor transparency-log entries are immutable                        |
| **Signing**        | Evidence Bundle rows cosign-signed in CI per Blueprint B § 7.5            |
| **Retention**      | Rekor entries are permanent; manifest is published as a Release asset     |

### 8.5 Threat model

An adversary with write access to the npm/PyPI/crates registry could publish a poisoned harness version; defended by sigstore provenance on publish, pinned-version vendored installs, and the hash-pin manifest that detects byte-tampering of the policy scripts. An adversary editing a gate script to weaken a threshold is caught by `harness-hash --verify` (the edit fails CI until the manifest is re-`init`'d and committed, which is a reviewable diff). An adversary supplying a malicious `.feature` or source fixture cannot achieve code execution — the gates parse, they do not execute the target.

---

## § 9 — Observability

### 9.1 OpenTelemetry events

N/A — no runtime, no emitted OTel events. Forward-reference `iel-E12` if emit-evidence later emits `agent.evidence_bundle.*` spans.

### 9.2 Trace propagation

N/A — single-shot CLI; no inbound trace context.

### 9.3 Lineage capture

- **EvidenceBundle**: each `gate-result/v1` row this repo emits is content-addressed to the subject it attests over; lineage is carried by `input_hash` + `commit_sha` + `runner` in the predicate.

### 9.4 Log levels

The gates use plain stdout/stderr with `✓` / `⛔` markers rather than a structured log-level taxonomy; ERROR-equivalent conditions exit non-zero with a stderr message.

### 9.5 Failure taxonomy

N/A — this repo does not emit `FailureTaxonomy` rows.

---

## § 10 — Cost governance

N/A — no paid surface touched at runtime. CI signing (Fulcio + Rekor) is free sigstore public infrastructure.

---

## § 11 — Release strategy

### 11.1 Versioning

**Strict SemVer** per Blueprint A § 4.2.

| Bump  | When                                                              |
| ----- | ----------------------------------------------------------------- |
| MAJOR | breaking change to the § 6.6 stability promise (CLI rename, exit-code grammar change) |
| MINOR | new subcommand; new optional flag; new gate                       |
| PATCH | bug fix; doc polish; internal refactor with no public-API change  |

### 11.2 Changelog

`CHANGELOG.md` per Keep a Changelog format. Every PR updates `## [Unreleased]`; the release commit promotes it to the new version + date.

### 11.3 Migration notes

N/A for PATCH/MINOR; a MAJOR bump ships migration notes in the release notes.

### 11.4 Compatibility guarantees

- CLI command names + exit-code grammar are stable across minor bumps.
- The four polyglot manifests (npm `package.json`, `version.txt`, `python/pyproject.toml`, `rust/Cargo.toml`) stay version + license aligned, enforced by the `version-canonical-check` CI job.

### 11.5 Evidence retention discipline

| Predicate URI                               | Status   | SPEC.md ref          | Signing mode         |
| ------------------------------------------- | -------- | -------------------- | -------------------- |
| `evals.intentsolutions.io/gate-result/v1`   | approved | Blueprint B § 7.4    | `rekor_production` (gated on DNSSEC + CAA pre-flight per `iah-E06`) |

Per DR-010 § 7 Q5: production-Rekor signing for `gate-result/v1` is unlocked by Blueprint B § 7 landing; the DNSSEC + CAA pre-flight on the predicate subdomain is tracked at `iah-E06`.

### 11.6 License audit

Apache-2.0 (relicensed from MIT in v1.0.0). Zero runtime dependencies, so the dependency-license surface is trivial. The `version-canonical-check` CI job asserts `Apache-2.0` across all four polyglot manifests.

---

## § 12 — Beads / work breakdown

| Concern               | Value                                                       |
| --------------------- | ----------------------------------------------------------- |
| **Bead prefix**       | `iah-` (per Blueprint A § 2.1)                              |
| **bd workspace**      | umbrella `~/000-projects/.beads/`                          |
| **Epic naming**       | `iah-E<NN>` (e.g., `iah-E01` = this blueprint)             |
| **Plane project**     | IAH                                                         |
| **Plane module**      | Intent Eval Platform                                        |
| **GH ↔ Plane mirror** | via `bd-sync` per global CLAUDE.md three-layer discipline   |

### 12.1 Cross-repo bead dependencies

- `iec-E12` (kernel v0.2.0 `EvidenceBundlePayload` + cross-field invariants) — the kernel schema this repo's emit conforms to.

### 12.2 In-repo epic inventory

| Epic       | Status      | Purpose                                            |
| ---------- | ----------- | -------------------------------------------------- |
| `iah-E01`  | in-progress | This per-repo blueprint (Blueprint C application)  |
| `iah-E02`  | open        | kernel-shadow-check architecture question          |
| `iah-E04`  | open        | second-emitter sketch                              |
| `iah-E06`  | open        | DNSSEC + CAA pre-flight for `gate-result/v1` prod-Rekor |

---

## § 13 — Definition of Done

This repo is "complete enough to release" when **every** check below passes:

- [ ] All golden suites pass (per-verb + regression) in CI.
- [ ] Provider PASS/FAIL gates — N/A (no LLM provider surface).
- [ ] The one canonical entity produced (§ 5 EvidenceBundle / `gate-result/v1`) is pinned to the kernel's known-good schema range.
- [ ] License audit clean — Apache-2.0, zero runtime deps, four manifests aligned.
- [ ] Partner-name vendor-generic grep returns 0 against all public-facing directories (current pattern in `~/000-projects/CLAUDE.md`).
- [ ] Evidence Bundle round-trip verified — emit → augment → schema-validate succeeds (regression Section 3/4).
- [ ] `CHANGELOG.md` entry written under `## [Unreleased]`.
- [ ] This per-repo blueprint matches reality — `/validate-consistency` clean against `000-docs/`, `README.md`, `CHANGELOG.md`.
- [ ] Acting head of board sign-off (or designated approver per `CODEOWNERS`).
