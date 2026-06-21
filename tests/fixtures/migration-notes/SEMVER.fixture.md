# SemVer commitment — fixture

> Fixture mirror of SEMVER.md for the migration-notes generator suite. Only the two
> sections the generator reads (the major-classification TL;DR table + the
> "what we will never do" list) need to be well-formed.

## TL;DR

| Change | Semver impact |
|---|---|
| Add a new subcommand | **minor** — additive |
| Add a new flag | **minor** — additive |
| Remove or rename a subcommand or flag | **major** |
| Change existing exit code for the same input | **major** |
| Change existing default text output | **major** |

## What we will never do

- Silently change an exit code for the same input.
- Re-use a removed subcommand name for a different gate.
- Skip a CHANGELOG entry for a CLI-surface change.

## Footer

Not parsed by the generator.
