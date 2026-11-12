#!/usr/bin/env python3
"""Verify signed assets into a new private directory; never execute the installer.

Run this verifier from an independently trusted checkout/installation. A verifier
downloaded beside an unverified installer cannot establish its own trust.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

REPOSITORY = "jeremylongshore/intent-audit-harness"
ISSUER = "https://token.actions.githubusercontent.com"
PAYLOADS = ("audit-harness.tar.gz", "install.sh", "release.json")
LIMITS = {
    "audit-harness.tar.gz": 512 * 1024 * 1024,
    "install.sh": 4 * 1024 * 1024,
    "release.json": 4096,
    "SHA256SUMS": 4096,
    "SHA256SUMS.sigstore.json": 16 * 1024 * 1024,
}


def snapshot(source, target, limit):
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("release asset must be a bounded regular file")
        with target.open("xb") as output:
            total = 0
            while True:
                block = stream.read(min(1024 * 1024, limit - total + 1))
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise ValueError("release asset grew beyond its limit")
                output.write(block)
        target.chmod(0o600)


def verify_assets(source, output, tag, expected_commit, cosign="cosign"):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", tag):
        raise ValueError("expected an explicit version tag")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("expected a full commit SHA from a trusted release record")
    source, output = Path(source), Path(output)
    output.mkdir(mode=0o700)
    try:
        for name, limit in LIMITS.items():
            snapshot(source / name, output / name, limit)
        identity = f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/tags/{tag}"
        subprocess.run([
            cosign, "verify-blob", str(output / "SHA256SUMS"),
            "--new-bundle-format",
            "--bundle", str(output / "SHA256SUMS.sigstore.json"),
            "--certificate-identity", identity,
            "--certificate-oidc-issuer", ISSUER,
        ], check=True, timeout=120)
        rows = (output / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        if len(rows) != len(PAYLOADS):
            raise ValueError("checksum manifest must name exactly the three release payloads")
        for row, name in zip(rows, PAYLOADS):
            if not re.fullmatch(r"[a-f0-9]{64}  " + re.escape(name), row):
                raise ValueError("checksum manifest contains unexpected paths or format")
            digest = hashlib.sha256()
            with (output / name).open("rb") as payload:
                for block in iter(lambda: payload.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != row[:64]:
                raise ValueError(f"release asset digest mismatch: {name}")
        metadata = json.loads((output / "release.json").read_text(encoding="utf-8"))
        expected = {
            "format": "audit-harness-release/v1", "repository": REPOSITORY,
            "tag": tag, "commit": expected_commit, "version": tag[1:],
        }
        if metadata != expected:
            raise ValueError("signed release metadata does not match the requested identity")
    except BaseException:
        shutil.rmtree(output)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(verify_assets(args.source, args.output, args.tag, args.expected_commit)))


if __name__ == "__main__":
    main()
