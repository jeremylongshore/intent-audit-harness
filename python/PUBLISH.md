# PyPI publish — automated, pending token

**Wired in `.github/workflows/release.yml`** (`publish-pypi` job): on every `v*.*.*`
tag push, the workflow builds the sdist + wheel, runs `twine check`, and uploads to
PyPI. The job is **guarded** — it no-ops with an explanatory log when the `PYPI_TOKEN`
repo secret is absent. It **activates automatically once `PYPI_TOKEN` is set** as a
repository secret; no further code change is needed. It never runs on a PR (tag-only).

**Status:** distribution artifacts built and validated, but **not yet uploaded** to PyPI.

`twine check` passed on both the sdist and wheel. What's missing is a PyPI API token — no `~/.pypirc`, no `pass` entry under `pypi/`, no `TWINE_PASSWORD` / `TWINE_USERNAME` in the environment.

## To publish

1. Create an API token at <https://pypi.org/manage/account/token/> (scope: entire account
   for the first upload of a new project, then narrow to `project:intent-audit-harness`).

2. Store it. Pick one of the options below.

   **Option A (preferred) — pass:**

   ```bash
   pass insert pypi/api-token
   # paste: pypi-REDACTED-PLACEHOLDER-PUT-YOUR-OWN-TOKEN-HERE...
   ```

   **Option B — `~/.pypirc`:**

   ```ini
   [pypi]
     username = __token__
     password = pypi-REDACTED-PLACEHOLDER-PUT-YOUR-OWN-TOKEN-HERE...
   ```

   Then `chmod 600 ~/.pypirc`.

3. Upload:

   ```bash
   cd ~/000-projects/audit-harness/python

   # If you used pass:
   export TWINE_USERNAME=__token__
   export TWINE_PASSWORD="$(pass pypi/api-token)"

   .venv/bin/twine upload dist/*
   ```

4. Verify:

   ```bash
   pip install --upgrade intent-audit-harness
   audit-harness --version    # → 0.1.0
   ```

## What's in `dist/`

- `intent_audit_harness-0.1.0-py3-none-any.whl`
- `intent_audit_harness-0.1.0.tar.gz`

Both passed `twine check`. Rebuild with `.venv/bin/python -m build` if the scripts change.

## Why not yet

No PyPI token material was discoverable (`ls ~/.pypirc`, `pass ls pypi/`, and
`env | grep -i pypi` all came up empty). Uploading blind would fail with a 401
and burn the project-name slot on a half-published record. Safer to wait for
the token.

Jeremy made me do it
-claude
