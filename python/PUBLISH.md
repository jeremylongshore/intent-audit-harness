# PyPI publish — live (automated on tag)

**Wired in `.github/workflows/release.yml`** (`publish-pypi` job): on every `v*.*.*`
tag push, the workflow builds the sdist + wheel, runs `twine check`, **keyless-signs
the wheel + sdist with sigstore-python** (Fulcio OIDC cert + Rekor inclusion proof —
the `.sigstore` bundles are attached onto the GitHub Release), and uploads to PyPI. The
job is **guarded** — it no-ops with an explanatory log when the `PYPI_TOKEN` repo secret
is absent. It **activates automatically once `PYPI_TOKEN` is set** as a repository secret;
no further code change is needed. It never runs on a PR (tag-only).

## Signing (bead kyk1 — `iah-py-sigstore`)

Per DR-010 Q2 hybrid-language allowance, the Python signing surface uses
**sigstore-python** (the PyPI-ecosystem-native signer) rather than cosign — mirroring
how the npm leg uses `npm --provenance` and the emit-evidence job uses cosign. The
`sigstore/gh-action-sigstore-python` step signs `python/dist/*.whl` and
`python/dist/*.tar.gz` keyless via the workflow's OIDC identity, producing a
`<artifact>.sigstore` Sigstore bundle per artifact. Those bundles are uploaded onto the
tag's GitHub Release; a consumer verifies a downloaded wheel with:

```bash
python -m sigstore verify identity intent_audit_harness-X.Y.Z-py3-none-any.whl \
  --bundle intent_audit_harness-X.Y.Z-py3-none-any.whl.sigstore \
  --cert-identity 'https://github.com/jeremylongshore/intent-audit-harness/.github/workflows/release.yml@refs/tags/vX.Y.Z' \
  --cert-oidc-issuer 'https://token.actions.githubusercontent.com'
```

Signing is gated on the same `PYPI_TOKEN` guard as the publish: a signature only has
meaning alongside the bytes that actually ship, so the workflow signs exactly when (and
only when) it publishes.

**Status:** PUBLISHED — `intent-audit-harness` is live on PyPI (currently 1.2.x), uploaded automatically by the `publish-pypi` job once `PYPI_TOKEN` was set. The remainder of this doc is the original token-bootstrap runbook, retained for the history and for re-bootstrapping in a fork.

`twine check` passed on both the sdist and wheel. The blocker at the time of writing was a missing PyPI API token — no `~/.pypirc`, no `pass` entry under `pypi/`, no `TWINE_PASSWORD` / `TWINE_USERNAME` in the environment; that has since been provisioned.

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
