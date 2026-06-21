# Changelog

All notable changes to a fixture package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> This buffer must be skipped by the generator — it is not a pinnable boundary.

### Added

- An unreleased thing that must never appear in migration notes.

## [2.0.0] - 2026-07-01

A major release that removes a subcommand and changes an exit code.

> **Why major:** The `legacy-scan` subcommand was removed and `crap`'s exit code
> for unsupported languages changed from 2 to 3.

### Removed

- **`legacy-scan` subcommand removed.** Replace any `legacy-scan` call with `scan`.

### Changed

- **`crap` unsupported-language exit code changed 2 → 3.** Update CI that branches
  on the old exit 2.

### Added

- A new additive flag that requires no migration.

## [1.1.0] - 2026-06-15

A minor release: purely additive.

> **Why minor:** A new opt-in flag. No command renamed or removed.

### Added

- **`--json` flag on every gate.** Opt-in; existing text-mode output is unchanged.

## [1.0.1] - 2026-06-01

A patch release: a bug fix only.

### Fixed

- **Off-by-one in the line counter.** No CLI surface change.

## [1.0.0] - 2026-05-19

Initial stable release.

### Added

- The first stable CLI surface.
