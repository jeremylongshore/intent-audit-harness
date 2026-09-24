# PyPI distribution — frozen

The `intent-audit-harness` package on PyPI is frozen at `1.4.0`. Starting with
audit-harness `1.5.0`, tag releases do not build, sign, or upload Python
distributions. The automated PyPI publisher has been removed from
`.github/workflows/release.yml`.

Do not create a PyPI token or manually upload a newer package. Python
repositories that need current harness behavior should use the canonical npm
package or vendor the released scripts with `install.sh`.

## Security closure

Retiring publication does not retire the package namespace. Revoke every
historical upload token at <https://pypi.org/manage/account/token/> and remove
the repository's `PYPI_TOKEN` secret. A token found in Git history must be
treated as compromised even when the current branch is redacted.

The wrapper source remains in `python/` for compatibility testing and to make
the historical distribution reproducible. Restoring PyPI publishing requires a
new, reviewed release decision; adding a token alone must never reactivate it.
