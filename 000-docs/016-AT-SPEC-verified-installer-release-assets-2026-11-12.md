# Verified installer release assets

Status: implementation candidate, not a published or signed release.
Bead: `bd_000-projects-k5e22`.

## Release identity and assets

The tag-only release workflow builds `install.sh`, `audit-harness.tar.gz` and
`release.json` from the exact commit named by the triggering event. The tag must
resolve to that full commit and its package version must match the tag. The
builder reads Git objects rather than dirty or untracked worktree files, and
discards inherited `GIT_*` settings that could redirect repository selection.
All object reads also disable local replacement refs, so an unchanged reported
commit cannot refer to substituted installer or archive content.
The archive uses a deterministic gzip header. Existing output is never replaced.

`SHA256SUMS` binds exactly those three payloads, including the repository, tag,
version and commit in `release.json`. The existing pinned Cosign installer
provides Cosign 2.5.2. The release workflow signs the checksum manifest and verifies
the bundle against its exact workflow/ref certificate identity and GitHub OIDC
issuer before npm publication. It uploads only the verified private snapshot,
plus `SHA256SUMS.sigstore.json`, after creating the GitHub release. Uploads do not
overwrite existing release assets.

This does not make publication across npm and GitHub atomic. A later upload
failure can leave npm published without installer assets; the failed workflow
must remain failed, and recovery must inspect existing artifacts rather than
overwrite signed evidence or silently republish a version. No tag or release is
created by the builder or verifier.

The signing mechanism follows [Sigstore's CI verification guidance](https://docs.sigstore.dev/quickstart/quickstart-ci/)
and [blob-signing bundle format](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/).
Retain the bundle: it contains the signature, certificate and transparency-log
inclusion proof. Checksums alone do not authenticate an installer.

## Consumer verification before execution

Use an independently trusted checkout or installation of this verifier, a trusted
Cosign 2.5.2 binary and Python 3 on POSIX. Fetching the verifier beside an untrusted
installer and immediately executing it does not establish bootstrap trust.
Obtain the expected tag and full commit from a reviewed release record, not from
the downloaded, unverified `release.json`.

After a release actually contains these assets, run from the intended consumer
repository with `TRUSTED_HARNESS`, `HARNESS_RELEASE_TAG` and
`HARNESS_RELEASE_COMMIT` set to those independently trusted values:

```bash
(
set -euo pipefail
: "${TRUSTED_HARNESS:?trusted harness checkout required}"
: "${HARNESS_RELEASE_TAG:?reviewed release tag required}"
: "${HARNESS_RELEASE_COMMIT:?reviewed full commit SHA required}"
downloads="$(mktemp -d)"
gh release download "$HARNESS_RELEASE_TAG" \
  --repo jeremylongshore/intent-audit-harness --dir "$downloads" \
  --pattern install.sh --pattern audit-harness.tar.gz --pattern release.json \
  --pattern SHA256SUMS --pattern SHA256SUMS.sigstore.json
python3 "$TRUSTED_HARNESS/scripts/verify-release-assets.py" \
  --source "$downloads" --output "$downloads/verified" \
  --tag "$HARNESS_RELEASE_TAG" --expected-commit "$HARNESS_RELEASE_COMMIT"
verified_archive_uri="$(python3 -c \
  'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().as_uri())' \
  "$downloads/verified/audit-harness.tar.gz")"
AUDIT_HARNESS_TARBALL_URL="$verified_archive_uri" \
  bash "$downloads/verified/install.sh" --version "$HARNESS_RELEASE_TAG"
)
```

The subshell stops before installation if download or verification fails. Keep
the verified directory as the installation's release evidence. The old
`curl | bash` path is not authenticated retroactively by these changes.

The verifier copies bounded regular files into a fresh private directory before
verification. It rejects symlink inputs, malformed or extra checksum entries,
unexpected paths, payload digest mismatches, signature refusal and release
identity mismatches. It checks the signature before trusting metadata and never
executes downloaded code. Download changes after the snapshot cannot replace
the verified bytes. This is not isolation from another process running as the
same user or from a compromised host. Cosign may obtain trust-root material over
the network; no air-gapped verification claim is made.

## Validation and delivery limits

The offline unit suite uses temporary Git repositories and a mocked Cosign
process. It verifies reproducibility, commit selection, inherited Git-environment
refusal, manifest/path/identity checks, signature-failure handling and private
snapshot behavior. Mock success is not cryptographic signature qualification.
The actual tag workflow must sign and verify the real release bytes; a published
release must also be downloaded and verified independently before claiming
end-to-end delivery.

The installer rollback fix and the remaining validator packaging work are
separate requirements of k5e22. This candidate does not add missing hook or
marketplace schemas, promote an internal kernel contract, sign a release locally,
or close that bead. Rollback uses a normal reviewed source revert before the next
release. Already signed assets and receipts retain their original identities.
