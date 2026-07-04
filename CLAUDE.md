# CLAUDE.md

Guidance for Claude Code when working on `@intentsolutions/audit-harness`.

## What this repo is

The canonical implementation of the test-enforcement scripts used by the `audit-tests` and `implement-tests` Claude Code skills. Published to npm as `@intentsolutions/audit-harness` so any repo can depend on it instead of assuming the skill is installed globally.

## Core design rules

1. **Scripts are the source of truth.** The Node CLI (`bin/audit-harness.js`) is a thin dispatcher. All logic lives in `scripts/*.sh` and `scripts/*.py`. Don't port to TypeScript unless there's a concrete reason (cross-platform Windows bug, etc.).
2. **Zero runtime deps.** Node ≥18, bash, python3 (used by 9 script verbs: crap-score, classify, conform, audit, scan, currency, fp-rate, migration-notes, gen-layer-applicability). Adding any npm dependency requires strong justification in the PR.
3. **Backward compatibility on CLI surface.** Once shipped, commands don't get renamed or repurposed. Add new ones; deprecate before removing (2 minor versions warning minimum).
4. **Policy-driven, never hardcoded.** Thresholds (coverage floor, CRAP limits, mutation kill rate) read from the target repo's `tests/TESTING.md`. Never hardcode a number in a script.
5. **The harness tests itself.** Run `bash scripts/escape-scan.sh --staged` on any proposed diff before committing.

## Read-only brain: `classify` + `conform` (PP-PLAN-040)

The "comprehensive audit, on any repo" build (master plan: `intent-eval-lab/000-docs/040-PP-PLAN-audit-trio-comprehensive-2026-06-04.md`) adds two **read-only** verbs that determine and check a repo's audit profile without Claude. Both are stdlib-Python, emit JSON to stdout, and **never write to the repo**:

- **`classify [repo]`** (`scripts/classify.py`) → an `audit-profile/v1` value. Detects the UNION of repo-type + Claude-artifact classifications, resolves the gate set against the canonical `schemas/audit-profile/registry.v1.json` datum, records `registry_hash`. `unresolved[]` is the only surface a Claude inspector may later refine.
- **`conform [repo]`** (`scripts/conform.py`) → `gate-result/v1` rows. For each `dimension: conformance` gate, validates the artifact against a content-addressed schema **bundled** in `schemas/conform/v1/` (never live-fetched) and records that schema's sha256 in `policy_hash`. Bundled JSON-Schemas are checked by an **embedded subset validator** (not ajv) on purpose: reproducibility of signed evidence beats per-box ajv availability. Genuinely-external formats shell out (OpenAPI→spectral, Action→yamllint); missing tool → ADVISORY indeterminate, never a false FAIL. Advisory-first; `--strict` turns violations into FAIL.

Design boundaries that travel with these verbs: the harness stays **read-only** (no `apply` — provisioning is `/implement-tests`'s job); conform's bundled schemas are the deterministic **structural floor**, distinct from the IS rubric / SAK authoring kernel (judgment, stays in `/validate-*`); new gates ship `enforcement: advisory` until an engineer promotes them in `tests/TESTING.md`. `scripts/classify.py` + `scripts/conform.py` are hash-pinned in `.harness-hash` — edits REFUSE at escape-scan until re-pinned via `audit-harness init`.

## Three-repo convergence (Phase A complete 2026-05-10)

This repo is the **deterministic-gates layer** of the three-repo convergence vision (`intent-eval-lab` + `audit-harness` + `j-rig-binary-eval`). The convergence sits on a shared **Evidence Bundle** schema authored upstream in `intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/`. This repo emits gate-result rows into that bundle; downstream tools (j-rig, Rollout Gate GHA) consume them.

**Master plan (local-only):** `~/.claude/plans/please-take-your-time-glimmering-stardust.md`
**ID mapping artifact:** `~/.claude/plans/please-take-your-time-glimmering-stardust-id-map.md`
**Convergence umbrella:** [`jeremylongshore/intent-eval-lab#4`](https://github.com/jeremylongshore/intent-eval-lab/issues/4) (`IEL-CONV-1`)

### Phase A landed (this repo)

- **8 work beads + GH issues** filed via bd-sync three-layer mirror (#1–#8 in this repo, LAB-14..21 in Plane LAB project)
- **5 Phase A.0 chores closed:** `AH-1a` (`bd init`), `AH-1b` (issue templates), `AH-1d` (Plane sub-stream + label), and parts of the structural setup
- **First CI workflow ever in this repo:** `.github/workflows/ci.yml` — 3-Node-version matrix, audit-harness self-check, shellcheck, Python compile-check (per `AH-1c`)
- **Issue templates:** `.github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.md` — author-side templates that require repro command + version info upfront
- **Evidence Bundle envelope design notes** at `000-docs/001-DR-DESIGN-evidence-bundle-envelope-design-notes.md` — Phase A deliverable for `AH-4`. Field-by-field design (required + optional + recommended `metadata` sub-fields), versioning rules, open questions for Phase B. The canonical schema lives upstream in `intent-eval-lab`; this doc is the audit-harness side of the design conversation.

### Phase B work (bandwidth-gated, not customer-signal-gated)

Per DR-010 § 13.5 (acting-head-of-board override), the customer-signal gate is **REMOVED** — Phase B is sequenced by available bandwidth, not by a first-paying-customer signal. This work has since landed (the `--json` surface, `emit-evidence`, and the read-only `classify`/`conform`/`audit`/`scan` verbs all ship in the current CLI):

- **[landed]** `AH-2` — adopt `--json` flag across all subcommands (uniform machine-readable output)
- **[landed]** `AH-3` — add `emit-evidence` subcommand emitting Evidence Bundle gate-result rows
- **[landed]** `AH-4` Phase B — adopt the schema in audit-harness via `AH-3`
- **[landed]** `AH-5` — backward-compat regression suite for new `--json` flag

The ~1,140 npm downloads of this package (verified 2026-05-11 from the npm registry — the previously-stated 45,000+ figure belonged to the separate `claude-code-plugins` package; correction logged in ISEDC Session 3 by the Research Expert seat) represent real production consumers — the polyglot trifecta (npm + PyPI + crates) and existing CLI surface stay; `--json` is purely additive.

## Canonical specs (cross-reference, do not restate)

The 7-layer testing taxonomy and the static↔behavioral tier composition are now
**central, versioned, NORMATIVE specs in `intent-eval-lab`** — this repo points to
them rather than restating them, so there is one referent and no N-way drift:

- **7-layer testing taxonomy** → `intent-eval-lab/specs/taxonomy/v0.1.0-draft/SPEC.md`.
  The authoritative layer set (git-hooks → static → unit → integration → system → E2E →
  acceptance), per-layer concerns, and the walls inside layers. audit-harness's gates are
  the deterministic checks *inside* these layers (escape-scan/crap/arch/bias/gherkin/harness-hash
  live in the static + acceptance walls). Where this repo's prose and the taxonomy spec disagree
  about what a layer means, **the spec wins.**
- **Tier-bridge (static ↔ behavioral composition)** → `intent-eval-lab/specs/tier-bridge/v0.1.0-draft/SPEC.md`.
  How a skill's static tiers (validator grading + the static production gate) compose with the
  behavioral `j-rig` tier into one promotion decision — ordering, fail-fast boundary, verdict
  algebra, and the Evidence Bundle each tier emits. audit-harness sits on the static side of this
  bridge; for the composition rules, **the spec wins.**

## Relationship to the skills

- `~/.claude/skills/audit-tests/` — the *diagnostic* skill; its SKILL.md Step 1/4/6 invoke commands in this package. It maps a repo against the canonical taxonomy spec above.
- `~/.claude/skills/implement-tests/` — the *installer* skill; its L1 + L3 playbooks add this as a dev dep. It installs missing layers from that same taxonomy spec.
- The skills stay updated via their own version bumps. This package versions independently.

When updating this package, also check:

- `~/.claude/skills/audit-tests/scripts/` — contains mirror copies; sync if signature-breaking changes land here
- `~/.claude/skills/audit-tests/SKILL.md` — references specific commands; update if CLI surface changes
- `~/.claude/skills/implement-tests/references/install-playbook-*.md` — reference `pnpm exec audit-harness ...`; update accordingly

## Release flow

```bash
# bump the CANONICAL version (package.json) per SemVer, then mirror to the
# polyglot manifests so version-canonical-check passes:
npm version patch   # or minor, or major  → updates package.json
# mirror the new number into version.txt, python/pyproject.toml + __init__.py,
# rust/Cargo.toml + Cargo.lock (CI version-canonical-check enforces parity)

# DO NOT `pnpm publish` by hand — publishing is CI-only for Sigstore provenance.
git push --follow-tags        # tag push triggers .github/workflows/release.yml
# → CI runs `npm publish --provenance --access public` (keyless Sigstore OIDC)
```

## Testing the harness

- `audit-harness verify` / `init` / `list` — self-evident; try on a throwaway repo
- `audit-harness escape-scan --staged` — requires a staged diff; test by staging a threshold-lowering change and confirming REFUSE
- `audit-harness crap` — requires `radon` (Python) or `gocyclo` (Go) installed; test on a small repo
- `audit-harness cred-gate --secret-env NAME --input file.json` — provider-cred leak gate (exit 1 on leak); `arch` / `bias` / `gherkin-lint` — the static-wall gates; `audit` / `scan` — read-only testing-depth + security/hygiene gate-runners (emit `gate-result/v1`); `emit-evidence` — writes Evidence Bundle rows.
- Safety levers: `AUDIT_HARNESS_DISABLE=1` (kill-switch, gates no-op), `AUDIT_HARNESS_TIMEOUT=N` (per-command watchdog, exit 124), `.audit-harness.yml` (per-repo override: classify_pins / advisory / disable_gates).

## Version management

- Current version: see `package.json`
- Changelog: `CHANGELOG.md` (Keep a Changelog format)
- Breaking CLI changes → major bump
- New commands → minor bump
- Bug fixes / doc updates → patch bump

## AI code review (Greptile + Gemini)

Two AI reviewers run on PRs here, **both advisory** — neither is a branch-protection
required check. The deterministic merge gate is this repo's own CI (`ci.yml`: self-check on Node 18/20/22, shellcheck, ruff, `python -m py_compile`, version-canonical-check, wrapper-byte-sync, gen-layer-applicability check, fp-rate) plus the separate `codeql.yml`, `actionlint.yml`, `doc-quality.yml`, `typos.yml`, and `rollout-gate-dogfood.yml` workflows.

- **Gemini Code Assist** (`.gemini/config.yaml` + `.gemini/styleguide.md`) is the
  **active** reviewer. Re-instated 2026-06-24 as the fallback after the Greptile
  review quota was exhausted. Workhorse for design / logic / correctness /
  cross-artifact consistency; CodeQL owns security.
- **Greptile** (`.greptile/config.json` + `rules.md` + `files.json`) is configured to
  the platform-unified schema (`strictness: 3`, `commentTypes: ["logic","syntax"]`,
  `statusCheck: false`, a universal `no-gate-weakening` rule, plus this repo's scoped
  invariant rules). It stays in place and resumes when the Greptile quota resets.

Read either review when present; the required gate is CI. Re-installing/uninstalling
the GitHub Apps is an admin (UI) action — the in-repo config here does not install them.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:

   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```

5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
