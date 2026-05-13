# CLAUDE.md

Guidance for Claude Code when working on `@intentsolutions/audit-harness`.

## What this repo is

The canonical implementation of the test-enforcement scripts used by the `audit-tests` and `implement-tests` Claude Code skills. Published to npm as `@intentsolutions/audit-harness` so any repo can depend on it instead of assuming the skill is installed globally.

## Core design rules

1. **Scripts are the source of truth.** The Node CLI (`bin/audit-harness.js`) is a thin dispatcher. All logic lives in `scripts/*.sh` and `scripts/*.py`. Don't port to TypeScript unless there's a concrete reason (cross-platform Windows bug, etc.).
2. **Zero runtime deps.** Node ≥18, bash, python3 for the `crap` command. Adding any npm dependency requires strong justification in the PR.
3. **Backward compatibility on CLI surface.** Once shipped, commands don't get renamed or repurposed. Add new ones; deprecate before removing (2 minor versions warning minimum).
4. **Policy-driven, never hardcoded.** Thresholds (coverage floor, CRAP limits, mutation kill rate) read from the target repo's `tests/TESTING.md`. Never hardcode a number in a script.
5. **The harness tests itself.** Run `bash scripts/escape-scan.sh --staged` on any proposed diff before committing.

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

### Phase B work (gated on first paying-customer signal)

- `AH-2` — adopt `--json` flag across all subcommands (uniform machine-readable output)
- `AH-3` — add `emit-evidence` subcommand emitting Evidence Bundle gate-result rows
- `AH-4` Phase B — adopt the schema in audit-harness via `AH-3`
- `AH-5` — backward-compat regression suite for new `--json` flag

**No feature code commits until Phase B kickoff** per master plan § Risks. The ~1,140 npm downloads of this package (verified 2026-05-11 from the npm registry — the previously-stated 45,000+ figure belonged to the separate `claude-code-plugins` package; correction logged in ISEDC Session 3 by the Research Expert seat) still represent real production consumers — the polyglot trifecta (npm + PyPI + crates) and existing CLI surface stay; `--json` is purely additive.

## Relationship to the skills

- `~/.claude/skills/audit-tests/` — the *diagnostic* skill; its SKILL.md Step 1/4/6 invoke commands in this package
- `~/.claude/skills/implement-tests/` — the *installer* skill; its L1 + L3 playbooks add this as a dev dep
- The skills stay updated via their own version bumps. This package versions independently.

When updating this package, also check:
- `~/.claude/skills/audit-tests/scripts/` — contains mirror copies; sync if signature-breaking changes land here
- `~/.claude/skills/audit-tests/SKILL.md` — references specific commands; update if CLI surface changes
- `~/.claude/skills/implement-tests/references/install-playbook-*.md` — reference `pnpm exec audit-harness ...`; update accordingly

## Release flow

```bash
# bump version per SemVer
npm version patch   # or minor, or major

# publish to npm (requires ~/.npmrc with org-scope token)
pnpm publish

# push tag to GitHub
git push --follow-tags
```

## Testing the harness

- `audit-harness verify` / `init` / `list` — self-evident; try on a throwaway repo
- `audit-harness escape-scan --staged` — requires a staged diff; test by staging a threshold-lowering change and confirming REFUSE
- `audit-harness crap` — requires `radon` (Python) or `gocyclo` (Go) installed; test on a small repo

## Version management

- Current version: see `package.json`
- Changelog: `CHANGELOG.md` (Keep a Changelog format)
- Breaking CLI changes → major bump
- New commands → minor bump
- Bug fixes / doc updates → patch bump


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
