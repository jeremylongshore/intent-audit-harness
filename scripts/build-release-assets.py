#!/usr/bin/env python3
"""Prepare unsigned release assets from an exact tag/commit, never worktree bytes."""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def git_env():
    # Hooks and parent shells can point Git at a different repository/index.
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(repo), *args], env=git_env(),
    )


def build_assets(repo, tag, expected_commit, output):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", tag):
        raise ValueError("expected an explicit version tag")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("expected a full commit SHA")
    commit = git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").decode().strip()
    if commit != expected_commit:
        raise ValueError("release tag does not resolve to the expected commit")
    package = json.loads(git(repo, "show", f"{commit}:package.json"))
    if package.get("version") != tag[1:]:
        raise ValueError("tag and package version differ")
    installer = git(repo, "show", f"{commit}:install.sh")
    if not installer.startswith(b"#!/usr/bin/env bash\n"):
        raise ValueError("tag does not contain the expected Bash installer")

    # Refuse existing output instead of overwriting previously signed evidence.
    output = Path(output)
    output.mkdir(mode=0o700)
    try:
        (output / "install.sh").write_bytes(installer)
        archive = output / "audit-harness.tar.gz"
        with archive.open("wb") as stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                with subprocess.Popen(
                    ["git", "--no-replace-objects", "-C", str(repo), "archive", "--format=tar",
                     f"--prefix=intent-audit-harness-{tag[1:]}/", commit],
                    stdout=subprocess.PIPE,
                    env=git_env(),
                ) as process:
                    shutil.copyfileobj(process.stdout, compressed)
                    if process.wait() != 0:
                        raise RuntimeError("git archive failed")
        metadata = {
            "format": "audit-harness-release/v1",
            "repository": "jeremylongshore/intent-audit-harness",
            "tag": tag,
            "commit": commit,
            "version": package["version"],
        }
        (output / "release.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        lines = []
        for name in ("audit-harness.tar.gz", "install.sh", "release.json"):
            digest = hashlib.sha256((output / name).read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}\n")
        (output / "SHA256SUMS").write_text("".join(lines), encoding="ascii")
    except BaseException:
        shutil.rmtree(output)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_assets(args.repo, args.tag, args.expected_commit, args.output)))


if __name__ == "__main__":
    main()
