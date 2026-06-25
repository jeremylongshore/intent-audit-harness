# Greptile reviewer orientation — `@intentsolutions/audit-harness`

You are reviewing this repo as a principal engineer who already understands the platform it
belongs to. This file briefs you on that context so your review catches the things that matter
here, not generic lint. The seven machine-checkable invariants live in `.greptile/config.json`;
this file is the prose that makes them make sense, plus the judgment calls a rule string can't
encode. The authoritative docs are `.greptile/files.json` — read `CLAUDE.md`, `SEMVER.md`, and
`000-docs/001-DR-DESIGN-...` before judging whether a change respects the repo's design rules.

---

## 1. Platform context — what this repo is and where it sits

This repo is **one of six** in the **Intent Eval Platform (IEP)** — Intent Solutions' agent-native
evaluation platform. The six repos converge on a single shared **Evidence Bundle** schema: each
emits gate verdicts as rows into a common, signed, schema-versioned envelope, and downstream
consumers union those rows into a ship / no-ship decision. The repos:

- **`@intentsolutions/core`** — the canonical **contracts kernel**. TS types + JSON Schemas + Zod
  validators + state machines for the platform's domain entities. This is the **single source of
  truth** for what a valid Evidence Bundle / `gate-result/v1` row looks like. It owns the schemas.
- **`audit-harness` (THIS repo)** — the **deterministic-gates + emit-evidence layer**. The L1 /
  static enforcement that travels with every Intent Solutions repo. It **emits** `gate-result/v1`
  rows and **consumes** the kernel's schemas. Polyglot: published to npm, PyPI, and crates.io.
- **`intent-eval-lab`** — methodology, specs, blueprints, decision records, glossary.
- **`j-rig-skill-binary-eval`** — behavioral eval + rollout-gate decision logic.
- **`intent-rollout-gate`** — the thin GitHub Action that consumes a bundle + policy → decision.
- (plus the dashboard / reports-hub surface.)

**The one sentence that governs every review here:** this repo is the deterministic-gates layer —
it **emits** the `gate-result/v1` predicate and **consumes** the kernel's schemas; it must NOT
re-declare them. That is the kernel-shadow binding. Everything below is a corollary.

What the harness actually does: a tiny Node CLI dispatcher (`bin/audit-harness.js`) fans out to
~17 deterministic commands implemented as shell + stdlib-Python scripts under `scripts/` — the
familiar gate names are `escape-scan`, `crap` (CRAP × coverage), `arch` (architecture rules),
`harness-hash` (`verify`/`init`/`list`), `bias-count`, `gherkin-lint`, plus the read-only brain
(`classify` / `conform` / `audit` / `scan`), `cred-gate`, and `emit-evidence`. It installs into a
target repo as a dev dependency (or vendored), and its hooks + CI gate every commit there. The full
roster + the three install flavors are in `README.md`.

---

## 2. The design rules, in prose

These are the repo's bedrock. A change that violates one is wrong even if it "works."

- **Scripts are the source of truth.** All gate logic lives in `scripts/*.sh` and `scripts/*.py`.
  `bin/audit-harness.js` is a *thin dispatcher* — it routes a subcommand to a script and forwards
  the exit code. Don't push logic up into the dispatcher, and don't port a script to TypeScript
  without a concrete reason (e.g. a real cross-platform Windows bug). A PR that moves a gate's
  decision logic into the JS dispatcher is moving it the wrong direction.

- **Zero runtime dependencies.** The CLI runs on Node ≥18, bash, and python3 (python3 only for the
  `crap` command). Adding any npm / PyPI / crates **runtime** dependency needs explicit strong
  justification in the PR description. devDependencies for linters/tooling are fine. Flag any new
  entry under `dependencies` in `package.json`, or a new third-party import added to a `scripts/`
  gate. The whole value proposition is "drop it in any repo and it just runs" — a runtime dep
  erodes that.

- **Policy-driven, never hardcoded.** Thresholds (coverage floor, CRAP limits, mutation kill-rate)
  are read from the **target repo's** `tests/TESTING.md`, and gate configs are hash-pinned via
  `.harness-hash`. A literal threshold number baked into a `scripts/` gate is a defect — the gate
  must read it from policy. Edits to hash-pinned scripts/configs REFUSE at escape-scan until
  re-pinned via `audit-harness init`; that re-pin is part of a legitimate policy change, not a way
  around the gate.

- **Enforcement travels with the code.** This is the most important operational rule and a frequent
  miss. Hooks, CI workflows, installer lines, and docs MUST reference the **in-repo** harness —
  `scripts/audit-harness`, `pnpm exec audit-harness`, or a vendored `.audit-harness/` copy. They
  MUST NEVER reference a `~/.claude/` path or otherwise assume the `audit-tests` / `implement-tests`
  skill is installed globally. A fresh clone on a CI runner has no `~/.claude/` — a gate wired that
  way silently no-ops. Flag any `~/.claude/` (or other user-home skill path) in a hook, workflow,
  doc, or install script on sight.

---

## 3. SemVer discipline — the surface is a contract

The harness CLI is consumed by pre-commit hooks, CI pipelines, and the `audit-tests` /
`implement-tests` skills across **many** Intent Solutions repos. Breaking the surface breaks adopter
CI silently. `SEMVER.md` is the authoritative contract; internalize three frozen pieces of it:

- **The frozen exit-code table.** Each command's exit codes (e.g. escape-scan 0=clean / 1=CHALLENGE
  / 2=REFUSE; verify 0/2/3; emit-evidence 0/1/2/3/4) are stable-since-version contracts. Changing an
  **existing** exit code for the **same input** is a MAJOR change.

- **The output-stream contract.** With `--json`, exactly one JSON object goes to **stdout** and the
  human-readable text stays on **stderr**; without `--json`, the text summary is on stdout. There is
  no third mode. Moving output between stdout and stderr for the same flag combination is MAJOR —
  adopters parse these streams.

- **The frozen predicate URI.** `emit-evidence` stamps `predicateType =
  https://evals.intentsolutions.io/gate-result/v1`. This URI is **frozen** once any signed Statement
  referencing it lands on a public transparency log (Rekor). A breaking change to the predicate body
  must mint a **new** URI (`gate-result/v2`) — never silently mutate the body under the same URI.
  The `evals.intentsolutions.io` namespace is reserved exclusively for these predicate URIs.

The bump matrix: additive (new command / flag / optional JSON field / new exit-code value for a new
failure class) = **minor**; surface-breaking (rename/remove a command or flag, change an existing
exit code, change existing default text, move a stream, tighten an input regex/enum, change the
predicate URI) = **major**; **anything ambiguous = major**. Any breaking change MUST ship: the
correct version bump, a `CHANGELOG.md` entry, and adopter-facing **migration notes** (a MAJOR bump
ships migration notes — the repo even has a `migration-notes` command for this). A surface change
that lands without the matching bump + CHANGELOG + (for major) migration notes is a defect to flag.

---

## 4. Determinism — a deterministic gate must actually be deterministic

These gates emit signed evidence. Reproducibility is the whole point: the same input must produce a
byte-identical verdict (modulo timestamp). So a gate that claims determinism MUST have **no network
dependence, no live schema fetches, no LLM/model calls, and no clock dependence** in its verdict
path. Concretely:

- Bundled JSON Schemas (e.g. `schemas/conform/v1/`) are validated against **content-addressed local
  copies** and their sha256 recorded as `policy_hash` — never live-fetched via `$ref`. `conform`
  deliberately uses an embedded subset validator rather than ajv so reproducibility of signed
  evidence beats per-box tool availability.
- A missing external tool yields an honest **ADVISORY indeterminate** — never a false FAIL and never
  a silent network fallback.
- Flag any new `curl` / `fetch` / `requests` / `http` / `urllib`, live `$ref` fetch, or model
  invocation introduced into a deterministic gate script. Flag any reliance on wall-clock time, RNG,
  filesystem-iteration order, or environment that would make the same input produce a different row.

This is *not* about the production DNSSEC/CAA pre-flight or the Rekor push in `emit-evidence` — those
are deliberate, fail-closed network steps in the **signing** path, governed by their own SEMVER.md
section. The rule targets the **verdict** path of the gates themselves.

---

## 5. What a high-quality review on this repo catches

If you find one of these, it is almost certainly worth a comment — these are the repo's signature
failure modes, in rough priority order:

1. **A `~/.claude/` (or user-home skill) path** in any hook, CI workflow, installer line, or doc —
   enforcement that won't reproduce on a fresh clone. (§2)
2. **A local re-declaration of a kernel-owned schema or type** — a new `$id`, JSON Schema file, or
   `GateResultV1` / `EvidenceBundle` / `skill-refiner-pass` TS/Python type that shadows
   `@intentsolutions/core` instead of referencing it. Design notes may *describe* a kernel schema;
   they must not *re-declare* it. (§1, kernel-shadow)
3. **A CLI / exit-code / output-stream / predicate-URI change without the matching SemVer bump +
   CHANGELOG entry + (for major) migration notes.** (§3)
4. **Network / LLM / clock dependence creeping into a deterministic gate's verdict path** — a new
   HTTP call, a live `$ref` fetch, a model call, or non-determinism that breaks byte-identical
   reproduction. (§4)
5. **A polyglot manifest drifting version or license.** `package.json` (npm) is the single source of
   truth for version + license; `version.txt`, `python/pyproject.toml`,
   `python/src/intent_audit_harness/__init__.py`, `rust/Cargo.toml`, and `rust/Cargo.lock` must all
   carry the exact same version string and the `Apache-2.0` license. A bump in one manifest not
   mirrored across all of them fails the version-canonical-check CI lane — flag it.
6. **A new runtime dependency** (a `dependencies` entry in `package.json`, or a third-party import in
   a `scripts/` gate) without strong justification. (§2)
7. **A hardcoded threshold** baked into a gate instead of read from the target repo's policy, or a
   gate shipped `enforcement: blocking` before its false-positive rate has been measured ≤ 5% (gates
   ship advisory-first; blocking is earned — see `docs/gate-promotion.md`).
8. **Logic migrating into the `bin/audit-harness.js` dispatcher** instead of staying in `scripts/`,
   or a gratuitous TypeScript port of a working shell/Python gate. (§2)

Be info-dense and specific: cite the file + line, name the invariant, and say what the correct shape
is. Skip nits that don't touch these axes — a wrong call on one of the eight above is worth far more
than a style comment.


## Review priorities — what to weight, what to skip

Greptile is **advisory** here. The deterministic merge gate is this repo's own
required CI (typecheck, lint, tests, coverage/mutation where applicable, the
audit-harness self-check, and CodeQL). Greptile's job is the semantic layer those
gates structurally cannot see — weight findings accordingly.

**Prioritize** (worth a comment): correctness and logic errors; security and
supply-chain / credential exposure; data-integrity and signed-evidence invariants;
concurrency and ordering hazards; input validation; auth / authorization
boundaries; secret handling; and regressions against the scoped invariants in
`config.json`.

**Deprioritize** (do not spend a comment here): style and naming; formatting;
churn in generated or build artifacts; and anything the L1 linters or CodeQL
already report. Never restate a deterministic gate — state the problem, the
`file:line`, and the concrete fix.
