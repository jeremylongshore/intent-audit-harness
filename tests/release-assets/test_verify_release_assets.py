"""Verifier control-flow tests. Mocked Cosign is not cryptographic qualification."""

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_assets", ROOT / "scripts/verify-release-assets.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class VerifyAssets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "download"
        self.source.mkdir()
        self.output = self.root / "verified"
        self.commit = "a" * 40
        self.metadata = {
            "format": "audit-harness-release/v1", "repository": VERIFIER.REPOSITORY,
            "tag": "v2.0.0", "commit": self.commit, "version": "2.0.0",
        }
        (self.source / "install.sh").write_bytes(b"fixture: must never execute\n")
        (self.source / "audit-harness.tar.gz").write_bytes(b"archive fixture\n")
        (self.source / "release.json").write_text(json.dumps(self.metadata))
        rows = [hashlib.sha256((self.source / name).read_bytes()).hexdigest() + "  " + name
                for name in VERIFIER.PAYLOADS]
        (self.source / "SHA256SUMS").write_text("\n".join(rows) + "\n")
        (self.source / "SHA256SUMS.sigstore.json").write_text("mock bundle; not a signature\n")

    def verify(self, **kwargs):
        args = dict(source=self.source, output=self.output, tag="v2.0.0", expected_commit=self.commit)
        args.update(kwargs)
        return VERIFIER.verify_assets(**args)

    def test_exact_signer_identity_and_private_verified_snapshot(self):
        def inspect_call(argv, **kwargs):
            self.assertEqual(argv[0:2], ["cosign", "verify-blob"])
            self.assertEqual(argv[argv.index("--certificate-identity") + 1],
                             "https://github.com/jeremylongshore/intent-audit-harness/.github/workflows/release.yml@refs/tags/v2.0.0")
            self.assertEqual(argv[argv.index("--certificate-oidc-issuer") + 1], VERIFIER.ISSUER)
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["timeout"], 120)
            # Downloads changed after snapshot cannot replace verified bytes.
            (self.source / "install.sh").write_bytes(b"later unverified content\n")
        with patch.object(VERIFIER.subprocess, "run", side_effect=inspect_call):
            self.assertEqual(self.verify(), self.metadata)
        self.assertEqual((self.output / "install.sh").read_bytes(), b"fixture: must never execute\n")
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in self.output.iterdir()))

    def test_signature_refusal_removes_partial_output(self):
        with patch.object(VERIFIER.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "cosign")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.verify()
        self.assertFalse(self.output.exists())

    def test_changed_payload_and_wrong_commit_refuse(self):
        with patch.object(VERIFIER.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "requested identity"):
                self.verify(expected_commit="b" * 40)
            (self.source / "audit-harness.tar.gz").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                self.verify()
        self.assertFalse(self.output.exists())

    def test_manifest_path_injection_refuses(self):
        manifest = self.source / "SHA256SUMS"
        manifest.write_text(manifest.read_text().replace("install.sh", "../install.sh"))
        with patch.object(VERIFIER.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "unexpected paths"):
                self.verify()
        self.assertFalse(self.output.exists())

    def test_symlink_input_refuses_before_signature_verification(self):
        installer = self.source / "install.sh"
        installer.unlink()
        installer.symlink_to(self.source / "release.json")
        with patch.object(VERIFIER.subprocess, "run") as cosign:
            with self.assertRaises(OSError):
                self.verify()
            cosign.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_verified_directory_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_text("keep\n")
        with self.assertRaises(FileExistsError):
            self.verify()
        self.assertEqual(sentinel.read_text(), "keep\n")

    def test_fifo_and_oversized_input_refuse_before_cosign(self):
        installer = self.source / "install.sh"
        installer.unlink()
        os.mkfifo(installer)
        with patch.object(VERIFIER.subprocess, "run") as cosign:
            with self.assertRaisesRegex(ValueError, "bounded regular"):
                self.verify()
            cosign.assert_not_called()
        self.assertFalse(self.output.exists())
        installer.unlink()
        with installer.open("wb") as stream:
            stream.truncate(VERIFIER.LIMITS["install.sh"] + 1)
        with patch.object(VERIFIER.subprocess, "run") as cosign:
            with self.assertRaisesRegex(ValueError, "bounded regular"):
                self.verify()
            cosign.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
