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
