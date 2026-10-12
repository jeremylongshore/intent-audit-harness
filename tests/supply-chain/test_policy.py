"""Refuse mutable CI inputs and unverified/corrupt executable downloads."""
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "ci" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = load("check-supply-chain")
INSTALLER = load("install-tool")
SHA = "a" * 40


class WorkflowPolicy(unittest.TestCase):
    def workflow(self, step):
        return "jobs:\n  test:\n    steps:\n      " + step + "\n"

    def test_current_repository_satisfies_policy(self):
        self.assertEqual(POLICY.check(ROOT), [])

    def test_full_sha_with_readable_comment_is_accepted(self):
        for use in (f"owner/action@{SHA}", f'"owner/action/path@{SHA}"'):
            self.assertEqual(POLICY.check_workflow(self.workflow(f"- uses: {use} # v1.2.3")), [])

    def test_mutable_short_dynamic_and_unexplained_refs_are_rejected(self):
        for step in ("- uses: owner/action@v1 # v1", "- uses: owner/action@abc1234 # v1",
                     "- uses: owner/action@${{ inputs.ref }} # dynamic", f"- uses: owner/action@{SHA}"):
            with self.subTest(step=step):
                self.assertTrue(POLICY.check_workflow(self.workflow(step)))

    def test_quoted_keys_and_aliases_do_not_bypass_policy(self):
        self.assertTrue(POLICY.check_workflow(self.workflow('- "uses": owner/action@main # branch')))
        text = "unsafe: &step\n  uses: owner/action@main # branch\njobs:\n  test:\n    steps: [*step]\n"
        self.assertTrue(POLICY.check_workflow(text))

    def test_direct_downloads_and_unlocked_installs_are_rejected(self):
        for command in ("curl -sSL https://example.invalid/tool | bash",
                        "wget https://example.invalid/schema.json",
                        "python3 -m pip install jsonschema==4.26.0",
                        "npm install --no-save package@1.0.0", "gh release download v1"):
            with self.subTest(command=command):
                self.assertTrue(POLICY.check_workflow(self.workflow("- run: " + command)))

    def test_locked_install_and_notification_post_are_allowed(self):
        for command in ("npm ci --ignore-scripts --prefix ci",
                        "curl --fail-with-body -X POST https://example.invalid/notification",
                        "python3 -m pip install --require-hashes --only-binary=:all: -r ci/requirements.txt",
                        '"$RUNNER_TEMP/provider/bin/python" -m pip install --require-hashes '
                        '--only-binary=:all: -r ci/measurement-requirements.txt'):
            text = self.workflow("- run: |\n          " + command)
            self.assertEqual(POLICY.check_workflow(text), [])

    def test_arbitrary_traversal_and_extra_requirements_are_rejected(self):
        for requirements in ("requirements.txt", "ci/arbitrary-requirements.txt",
                             "ci/../ci/measurement-requirements.txt", "../ci/measurement-requirements.txt",
                             "ci/measurement-requirements.txt -r other.txt",
                             "ci/measurement-requirements.txt --no-deps"):
            with self.subTest(requirements=requirements):
                command = "python3 -m pip install --require-hashes --only-binary=:all: -r " + requirements
                self.assertTrue(POLICY.check_workflow(self.workflow("- run: " + command)))

    def test_measurement_install_requires_hash_and_binary_flags(self):
        for flags in ("", "--require-hashes ", "--only-binary=:all: "):
            with self.subTest(flags=flags):
                command = f"python3 -m pip install {flags}-r ci/measurement-requirements.txt"
                self.assertTrue(POLICY.check_workflow(self.workflow("- run: " + command)))

    def test_invalid_yaml_fails_closed(self):
        self.assertTrue(POLICY.check_workflow("jobs: [invalid"))


class RequirementsPolicy(unittest.TestCase):
    def fixture(self, root):
        for relative in ("ci/requirements.txt", "ci/measurement-requirements.txt", "ci/downloads.json",
                         "ci/package.json", "ci/package-lock.json", ".github/dependabot.yml",
                         "tests/fixtures/gate-result-v1.schema.json"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def test_both_trusted_locks_require_exact_versions_and_payload_hashes(self):
        for relative in ("ci/requirements.txt", "ci/measurement-requirements.txt"):
            for requirement in ("coverage==7.13.4", "coverage>=7.13.4 --hash=sha256:" + "a" * 64,
                                "coverage==7.13.4 --hash=sha256:abc123", "-r ../requirements.txt"):
                with self.subTest(path=relative, requirement=requirement), tempfile.TemporaryDirectory() as work:
                    root = Path(work)
                    self.fixture(root)
                    (root / relative).write_text(requirement + "\n")
                    errors = POLICY.check(root)
                    self.assertTrue(any(relative in error and "payload hash" in error for error in errors), errors)

    def test_missing_or_redirected_lock_cannot_bypass_hash_validation(self):
        for relative in ("ci/requirements.txt", "ci/measurement-requirements.txt"):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as work:
                root = Path(work)
                self.fixture(root)
                path = root / relative
                path.unlink()
                self.assertTrue(any(relative in error for error in POLICY.check(root)))
                path.symlink_to(ROOT / relative)
                self.assertTrue(any(relative in error for error in POLICY.check(root)))


class VerifiedInstaller(unittest.TestCase):
    def archive(self, symlink=False):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            binary = b"synthetic executable\n"
            member = tarfile.TarInfo("release/tool")
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = len(binary)
                archive.addfile(member, io.BytesIO(binary))
            trap = tarfile.TarInfo("../must-not-extract")
            trap.size = len(binary)
            archive.addfile(trap, io.BytesIO(binary))
        return output.getvalue()

    def test_valid_archive_installs_only_pinned_member(self):
        data = self.archive()
        with tempfile.TemporaryDirectory() as work:
            destination = Path(work) / "bin"
            pin = {"url": "https://example.invalid/tool", "member": "release/tool",
                   "sha256": hashlib.sha256(data).hexdigest()}
            INSTALLER.install(pin, "tool", destination, opener=lambda *_args, **_kwargs: io.BytesIO(data))
            self.assertEqual((destination / "tool").read_bytes(), b"synthetic executable\n")
            self.assertEqual((destination / "tool").stat().st_mode & 0o777, 0o755)
            self.assertFalse((Path(work) / "must-not-extract").exists())

    def test_bad_digest_or_symlink_member_preserves_existing_executable(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as work:
                destination = Path(work)
                executable = destination / "tool"
                executable.write_bytes(b"previous approved executable")
                data = self.archive(symlink=symlink)
                pin = {"url": "https://example.invalid/tool", "member": "release/tool",
                       "sha256": hashlib.sha256(data).hexdigest() if symlink else "0" * 64}
                with self.assertRaises(ValueError):
                    INSTALLER.install(pin, "tool", destination,
                                      opener=lambda *_args, _data=data, **_kwargs: io.BytesIO(_data))
                self.assertEqual(executable.read_bytes(), b"previous approved executable")


if __name__ == "__main__":
    unittest.main()
