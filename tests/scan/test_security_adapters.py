"""CLI contracts for scanner failures, redacted evidence and SBOM custody."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCAN = Path(__file__).resolve().parents[2] / "scripts" / "scan.py"
CANARY = "SYNTHETIC-SCANNER-SECRET-CANARY"
FAKE = r'''#!/usr/bin/python3
import json, os, pathlib, sys
tool = pathlib.Path(sys.argv[0]).name
mode = os.environ.get("SCANNER_FIXTURE_MODE", "clean")
if "--version" in sys.argv or sys.argv[1:2] == ["version"]:
    version = "[not provided]" if mode == "unversioned" else "1.2.3-fixture"
    if tool == "syft":
        print(json.dumps({"application": "syft", "version": version, "goVersion": "go1.26.5"}))
    else:
        print(tool + " " + version)
    sys.exit(0)
if mode == "crash":
    print("SYNTHETIC-SCANNER-SECRET-CANARY", file=sys.stderr)
    sys.exit(2)
if mode == "fatal-one":
    print("SYNTHETIC-SCANNER-SECRET-CANARY", file=sys.stderr)
    sys.exit(1)
if mode == "invalid":
    print("not-json SYNTHETIC-SCANNER-SECRET-CANARY")
    sys.exit(0)
if mode == "wrong-shape":
    print("{}")
    sys.exit(0)
if mode == "oversized":
    print(" " * (16 * 1024 * 1024) + "[]")
    sys.exit(0)
if tool == "gitleaks":
    rows = [] if mode == "clean" else [{"RuleID": "test-rule", "File": "fixture.txt", "StartLine": 1,
                                      "Secret": "SYNTHETIC-SCANNER-SECRET-CANARY",
                                      "Match": "SYNTHETIC-SCANNER-SECRET-CANARY"}]
    print(json.dumps(rows))
    if mode == "disagreement":
        sys.exit(0)
    sys.exit(0 if not rows else int(sys.argv[sys.argv.index("--exit-code") + 1]) if "--exit-code" in sys.argv else 1)
if tool == "semgrep":
    rows = [{"check_id": "test-rule", "path": "fixture.py", "start": {"line": 1},
             "extra": {"lines": "SYNTHETIC-SCANNER-SECRET-CANARY"}}] if mode in ("findings", "disagreement") else []
    errors = [{"type": "ParseError", "message": "SYNTHETIC-SCANNER-SECRET-CANARY"}] if mode == "partial" else []
    print(json.dumps({"results": rows, "errors": errors, "version": "1.2.3-fixture"}))
    sys.exit(1 if rows and mode != "disagreement" else 0)
print(json.dumps({"artifacts": [{"id": "synthetic", "name": "fixture-package", "version": "1.0.0", "type": "python"}],
                  "artifactRelationships": [], "source": {"id": "fixture", "type": "directory", "target": "."},
                  "descriptor": {"name": "syft", "version": "1.2.3-fixture"},
                  "schema": {"version": "16.0.0", "url": "https://example.invalid/syft-schema"}}))
'''


class SecurityAdapters(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="harness-scanner-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("gitleaks", "semgrep", "syft"):
            executable = self.bin / tool
            executable.write_text(FAKE)
            executable.chmod(0o755)

    def scan(self, tool, mode="clean", flags=(), applicability="required", present=True, enforcement="advisory"):
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"subject": {"commit_sha": "a" * 40}, "gates": [{
            "gate_id": "audit-harness:ci:" + (tool or "unwired"), "tool": tool, "dimension": "security",
            "enforcement": enforcement, "applicability": applicability,
        }]}))
        env = dict(os.environ, PATH=str(self.bin) if present else str(self.root / "missing"),
                   AUDIT_HARNESS_DISABLE="0", SCANNER_FIXTURE_MODE=mode)
        result = subprocess.run([sys.executable, str(SCAN), str(self.repo), "--profile", str(profile), *flags],
                                env=env, capture_output=True, text=True, timeout=15)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result, json.loads(result.stdout)[0]

    def test_required_missing_scanners_fail_closed(self):
        for tool in ("gitleaks", "semgrep", "syft"):
            with self.subTest(tool=tool):
                result, row = self.scan(tool, flags=("--fail-closed",), present=False)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(row["result"], "FAIL")
                self.assertTrue(row["metadata"]["indeterminate"])

    def test_missing_default_or_recommended_scanner_stays_advisory(self):
        for flags, applicability in (((), "required"), (("--fail-closed",), "recommended")):
            with self.subTest(flags=flags, applicability=applicability):
                result, row = self.scan("semgrep", flags=flags, applicability=applicability, present=False)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(row["result"], "ADVISORY")
                self.assertTrue(row["metadata"]["indeterminate"])

    def test_unwired_required_security_gates_fail_closed(self):
        for tool in (None, "future-scanner", "markdownlint"):
            with self.subTest(tool=tool):
                result, row = self.scan(tool, flags=("--fail-closed",))
                self.assertEqual(result.returncode, 1)
                self.assertTrue(row["metadata"]["indeterminate"])

    def test_blocking_and_waived_profile_semantics(self):
        result, row = self.scan("semgrep", flags=("--fail-closed",), applicability="recommended",
                                enforcement="blocking", present=False)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(row["metadata"]["indeterminate"])
        for tool in ("semgrep", "syft", "future-scanner"):
            with self.subTest(tool=tool):
                result, row = self.scan(tool, flags=("--fail-closed",), applicability="waived", present=False)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(row["result"], "NOT_APPLICABLE")

    def test_scanner_crashes_are_operational_failures_without_raw_output(self):
        for tool, modes in (("gitleaks", ("fatal-one", "crash")), ("semgrep", ("crash",)), ("syft", ("crash",))):
            for mode in modes:
                with self.subTest(tool=tool, mode=mode):
                    result, row = self.scan(tool, mode, ("--fail-closed",))
                    self.assertEqual(result.returncode, 1)
                    self.assertTrue(row["metadata"]["indeterminate"])
                    self.assertNotIn("findings", row["failure_mode"])

    def test_invalid_or_incomplete_machine_reports_cannot_pass(self):
        for tool in ("gitleaks", "semgrep", "syft"):
            for mode in ("invalid", "wrong-shape"):
                with self.subTest(tool=tool, mode=mode):
                    result, row = self.scan(tool, mode, ("--fail-closed",))
                    self.assertEqual(result.returncode, 1)
                    self.assertTrue(row["metadata"]["indeterminate"])
        result, row = self.scan("semgrep", "partial", ("--fail-closed",))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(row["metadata"]["indeterminate"])

    def test_findings_are_counted_and_never_echo_sensitive_snippets(self):
        for tool in ("gitleaks", "semgrep"):
            for flags, verdict in (((), "ADVISORY"), (("--strict",), "FAIL"), (("--fail-closed",), "FAIL")):
                with self.subTest(tool=tool, flags=flags):
                    _, row = self.scan(tool, "findings", flags)
                    self.assertEqual(row["result"], verdict)
                    self.assertEqual(row["metadata"]["finding_count"], 1)
                    self.assertFalse(row["metadata"].get("indeterminate", False))

    def test_exit_report_disagreement_and_oversized_reports_fail_closed(self):
        for tool in ("gitleaks", "semgrep"):
            for mode in ("disagreement", "oversized"):
                with self.subTest(tool=tool, mode=mode):
                    result, row = self.scan(tool, mode, ("--fail-closed",))
                    self.assertEqual(result.returncode, 1)
                    self.assertTrue(row["metadata"]["indeterminate"])

    def test_clean_reports_preserve_machine_provenance(self):
        for tool in ("gitleaks", "semgrep"):
            with self.subTest(tool=tool):
                result, row = self.scan(tool, flags=("--fail-closed",))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(row["result"], "PASS")
                self.assertEqual(row["metadata"]["finding_count"], 0)
                self.assertEqual(row["metadata"]["scanner_exit_code"], 0)
                self.assertEqual(row["metadata"]["tool_version"], "1.2.3-fixture")

    def test_unversioned_syft_never_reports_its_compiler_version(self):
        artifact = self.root / "sbom.json"
        result, row = self.scan("syft", "unversioned", ("--fail-closed", "--sbom-output", str(artifact)))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(row["metadata"]["tool_version"], "unknown")

    def test_syft_artifact_is_preserved_and_digest_matches_exact_bytes(self):
        artifact = self.root / "sbom.json"
        result, row = self.scan("syft", flags=("--fail-closed", "--sbom-output", str(artifact)))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(row["result"], "PASS")
        self.assertEqual(json.loads(artifact.read_bytes())["artifacts"][0]["name"], "fixture-package")
        self.assertEqual(row["metadata"]["sbom_sha256"], "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertEqual(row["metadata"]["sbom_uri"], artifact.as_uri())

    def test_bad_syft_report_preserves_existing_artifact(self):
        artifact = self.root / "sbom.json"
        artifact.write_bytes(b"previous-evidence\n")
        result, row = self.scan("syft", "invalid", ("--fail-closed", "--sbom-output", str(artifact)))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(row["metadata"]["indeterminate"])
        self.assertEqual(artifact.read_bytes(), b"previous-evidence\n")

    def test_required_syft_without_output_is_unmeasured(self):
        result, row = self.scan("syft", flags=("--fail-closed",))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(row["metadata"]["indeterminate"])

    def test_sbom_output_cannot_mutate_the_audited_repository(self):
        artifact = self.repo / "sbom.json"
        result, row = self.scan("syft", flags=("--fail-closed", "--sbom-output", str(artifact)))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(row["metadata"]["indeterminate"])
        self.assertFalse(artifact.exists())

    def test_sbom_output_refuses_symlinks_and_parent_aliases_into_repo(self):
        artifact = self.root / "existing-sbom.json"
        artifact.write_bytes(b"previous-evidence\n")
        alias = self.root / "sbom-link.json"
        alias.symlink_to(artifact)
        repo_alias = self.root / "repo-alias"
        repo_alias.symlink_to(self.repo, target_is_directory=True)
        for output in (alias, repo_alias / "sbom.json"):
            with self.subTest(output=output):
                result, row = self.scan("syft", flags=("--fail-closed", "--sbom-output", str(output)))
                self.assertEqual(result.returncode, 1)
                self.assertTrue(row["metadata"]["indeterminate"])
        self.assertEqual(artifact.read_bytes(), b"previous-evidence\n")
        self.assertFalse((self.repo / "sbom.json").exists())


if __name__ == "__main__":
    unittest.main()
