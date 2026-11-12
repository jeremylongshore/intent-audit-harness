"""Offline release identity and reproducibility tests; never sign or publish."""

import hashlib
import importlib.util
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_assets", ROOT / "scripts/build-release-assets.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class ReleaseAssets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.git("init", "-q")
        self.git("config", "user.name", "Release fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "package.json").write_text('{"version":"2.0.0"}\n')
        self.installer = b"#!/usr/bin/env bash\nprintf 'fixture only\\n'\n"
        (self.repo / "install.sh").write_bytes(self.installer)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts/conform.py").write_text("# committed validator fixture\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture release")
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.git("tag", "v2.0.0")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], env=self.env, text=True,
        )

    def build(self, name="assets", **overrides):
        args = dict(repo=self.repo, tag="v2.0.0", expected_commit=self.commit, output=self.root / name)
        args.update(overrides)
        return BUILDER.build_assets(**args)

    def test_exact_commit_ignores_dirty_worktree_and_is_reproducible(self):
        (self.repo / "install.sh").write_text("unreviewed worktree bytes\n")
        (self.repo / "scripts/untracked.py").write_text("untracked\n")
        metadata = self.build()
        self.build("again")
        assets = self.root / "assets"
        self.assertEqual(metadata["commit"], self.commit)
        self.assertEqual((assets / "install.sh").read_bytes(), self.installer)
        for artifact in assets.iterdir():
            self.assertEqual(artifact.read_bytes(), (self.root / "again" / artifact.name).read_bytes())
        with tarfile.open(assets / "audit-harness.tar.gz") as archive:
            prefix = "intent-audit-harness-2.0.0/"
            self.assertEqual(archive.extractfile(prefix + "install.sh").read(), self.installer)
            self.assertIn(prefix + "scripts/conform.py", archive.getnames())
            self.assertNotIn(prefix + "scripts/untracked.py", archive.getnames())
        entries = (assets / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(entries), 3)
        for entry in entries:
            digest, name = entry.split("  ")
            self.assertEqual(hashlib.sha256((assets / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(json.loads((assets / "release.json").read_text()), metadata)

    def test_wrong_commit_and_version_refuse_before_creating_output(self):
        with self.assertRaisesRegex(ValueError, "expected commit"):
            self.build(expected_commit="0" * 40)
        self.git("tag", "v2.0.1")
        with self.assertRaisesRegex(ValueError, "version differ"):
            self.build(tag="v2.0.1")
        self.assertFalse((self.root / "assets").exists())

    def test_existing_output_is_never_replaced(self):
        self.build()
        manifest = (self.root / "assets/SHA256SUMS").read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual((self.root / "assets/SHA256SUMS").read_bytes(), manifest)

    def test_inherited_git_paths_cannot_redirect_the_explicit_repository(self):
        with patch.dict(os.environ, {
            "GIT_DIR": str(self.root / "nonexistent.git"),
            "GIT_WORK_TREE": str(self.root / "wrong-tree"),
            "GIT_INDEX_FILE": str(self.root / "wrong-index"),
        }):
            self.build()
        self.assertEqual((self.root / "assets/install.sh").read_bytes(), self.installer)

    def test_rejects_symbolic_commit_and_nonversion_tag(self):
        for kwargs in ({"expected_commit": "HEAD"}, {"tag": "main"}, {"tag": "v2.0.0/other"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.build(**kwargs)
        self.assertFalse((self.root / "assets").exists())


if __name__ == "__main__":
    unittest.main()
