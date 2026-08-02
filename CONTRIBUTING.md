# Contributing to audit-harness

Thank you for your interest in contributing to **audit-harness** — the deterministic test-enforcement toolkit (`@intentsolutions/audit-harness` on npm, `intent-audit-harness` on PyPI + crates).

## Getting Started

### Prerequisites

- Node 18+ (the dispatcher `bin/audit-harness.js` is plain Node, no build step)
- Git
- GitHub account
- For polyglot script testing: Python 3.10+ (for `crap-score.py`), bash 5+

### Development Setup

```bash
git clone https://github.com/jeremylongshore/intent-audit-harness.git
cd audit-harness
npm install        # only dev-deps; the package itself has no runtime deps
```

### Quick self-check

```bash
node bin/audit-harness.js list          # show pinned scripts
node bin/audit-harness.js verify        # verify against pinned hashes
```

## How to Contribute

### Reporting Bugs

1. Search [existing issues](https://github.com/jeremylongshore/intent-audit-harness/issues) first
2. Open a [bug report](https://github.com/jeremylongshore/intent-audit-harness/issues/new?template=bug_report.md)
3. Include the harness version (`audit-harness --version`), Node version, OS, reproduction steps, and the failing manifest/script output

### Suggesting Enhancements

1. Check [existing feature requests](https://github.com/jeremylongshore/intent-audit-harness/issues?q=label%3Aenhancement)
2. Open a [feature request](https://github.com/jeremylongshore/intent-audit-harness/issues/new?template=feature_request.md)
3. For new subcommands, explain (a) the gate it enforces, (b) why deterministic shell/python is sufficient (no LLM-in-the-loop), (c) how it integrates with `--init` hash-pinning

### Pull Requests

1. Fork the repository
2. Create a feature branch from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

3. Make your changes — keep additive when possible (the harness has a stable CLI surface across 5+ language ecosystems)
4. Write or update tests in `test/` if behavior changes
5. Verify locally: `npm test` (when test suite exists) + `node bin/audit-harness.js list` should still exit 0
6. Commit with [conventional commit messages](#commit-messages)
7. Push and open a pull request

## Development Process

### Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code; npm-publish source |
| `feature/*` | New features |
| `fix/*` | Bug fixes |
| `docs/*` | Documentation changes |
| `chore/*` | Tooling, CI, dependency bumps |

### Stability promise

audit-harness is consumed by many other Intent Solutions repos (via npm / PyPI / crates / `install.sh` vendoring). **Backward-compatible additions only on minor releases.** Breaking changes wait for a major version bump and are documented in CHANGELOG.md with a migration recipe.

### Testing

```bash
# When a test suite lands, this will run it:
npm test

# Polyglot script smoke checks:
bash scripts/escape-scan.sh --help
python3 scripts/crap-score.py --help
```

### Code Review

- All PRs require at least 1 maintainer approval
- CI must pass (currently: self-check across Node 18/20/22)
- Keep PRs focused — one feature or fix per PR
- Document any policy-file changes — if the change requires consumer repos to re-run `audit-harness init` to refresh their `.harness-hash` manifest, **state that explicitly in the PR description**

### Producer-sensitive pattern rules

If a contribution adds or changes a deny-list, slop list, bias pattern, or
other rule learned from observed output, include the producer population and
calibration scope in the PR. Add labeled fixtures for the new failure mode and
follow [`docs/producer-calibration.md`](docs/producer-calibration.md) before
claiming coverage for another producer. The harness cannot infer producer
identity from an artifact; the provenance record and human disposition are part
of the gate owner's contract. Never place private or credential-bearing samples
in the repository just to improve calibration.

## Style Guides

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <subject>

[optional body]
[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

**Examples:**

- `feat(crap): support .NET via dotnet-coverage`
- `fix(escape-scan): handle whitespace in renamed files`
- `docs(readme): clarify install.sh polyglot vendor flow`

### Code Style

- Follow the project's existing conventions
- Bash scripts use `shellcheck`-clean style (the CI runs shellcheck)
- Python scripts use 4-space indent + type hints where it helps readability
- Node files use 2-space indent (per `.editorconfig`)
- No new runtime dependencies in the npm package without explicit discussion — keep the dispatcher dependency-free

### License-aware contributions

The package is MIT-licensed. By contributing, you agree to license your contributions under the same MIT terms. Don't introduce dependencies under copyleft licenses (GPL/AGPL) without prior discussion.

## Community

- **Questions**: [GitHub Discussions](https://github.com/jeremylongshore/intent-audit-harness/discussions)
- **Bugs**: [Issue Tracker](https://github.com/jeremylongshore/intent-audit-harness/issues)
- **Email**: <jeremy@intentsolutions.io>

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).

---

*Thank you for helping improve audit-harness!*
