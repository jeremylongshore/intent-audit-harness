## Summary

<!-- Describe your changes in 1-3 bullet points -->

-
-
-

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation (updates to docs, comments, or README)
- [ ] Refactor (code change that neither fixes a bug nor adds a feature)
- [ ] CI/CD (changes to build process, workflows, or tooling)

## Checklist

- [ ] Tests pass locally (`npm test` or equivalent)
- [ ] `node bin/audit-harness.js list` still exits 0
- [ ] No secrets or credentials committed
- [ ] Commits follow conventional commit format
- [ ] Documentation updated (if applicable)
- [ ] Self-reviewed the diff before requesting review

## Consumer-repo impact

<!--
audit-harness is consumed by many Intent Solutions repos via npm / PyPI / crates / install.sh vendoring.
If this PR changes the CLI surface, policy-file expectations, or output format, state explicitly:
  - Does it require consumer repos to re-run `audit-harness init` to refresh `.harness-hash`?
  - Does it break backward compatibility of any subcommand?
  - Does it change the schema of any emitted JSON?

If unsure, mark `Breaking change` above and discuss in the PR.
-->

- [ ] Backward-compatible: consumer repos can upgrade without changes
- [ ] Requires consumer repo action — describe below:

## Testing

<!-- Describe the tests you ran and how to reproduce them -->

## Related Issues

<!-- Link related issues below. Use "Closes #123" to auto-close on merge -->

Closes #
