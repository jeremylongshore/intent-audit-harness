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
