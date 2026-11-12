"""Pinned source loading, same-byte input identity and static severity boundaries."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import shared_authoring as SH  # noqa: E402
import conform as CF  # noqa: E402


class SharedAuthoring(unittest.TestCase):
    def copy_policy(self, root):
        for relative in (SH.PIN, SH.MODULE, SH.LICENSE):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)

    def test_real_pinned_checker_and_distinct_findings(self):
        checker, digest, reason = SH.load_agent_checker()
        self.assertIsNone(reason)
        self.assertEqual(digest, "sha256:" + hashlib.sha256((ROOT / SH.PIN).read_bytes()).hexdigest())
        errors, warnings, reason = SH.agent_findings(checker, {"tools": ["Read"]}, "Use mcp__fixture__read.")
        self.assertTrue(errors)
        self.assertFalse(warnings)
        self.assertIsNone(reason)
        self.assertEqual(SH.agent_findings(lambda *_: ([], "not a warning list"), {}, "")[:2], ([], []))
        self.assertIsNotNone(SH.agent_findings(lambda *_: ([], "not a warning list"), {}, "")[2])

    def test_tampered_module_is_not_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_policy(root)
            marker = root / "executed"
            (root / SH.MODULE).write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
            checker, _, reason = SH.load_agent_checker(root)
            self.assertIsNone(checker)
            self.assertIn("hash mismatch", reason)
            self.assertFalse(marker.exists())

    def test_module_executes_verified_snapshot_not_a_second_file_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_policy(root)
            original_reader = SH.read_bytes_snapshot

            def replace_after_read(base, relative):
                result = original_reader(base, relative)
                if relative == SH.MODULE:
                    (root / relative).write_text("raise RuntimeError('replacement must not execute')\n")
                return result

            with patch.object(SH, "read_bytes_snapshot", side_effect=replace_after_read):
                checker, _, reason = SH.load_agent_checker(root)
            self.assertIsNone(reason)
            self.assertEqual(checker({"tools": ["Read"]}, "Read files."), ([], []))

    def test_missing_license_and_unsupported_manifest_are_unmeasured(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_policy(root)
            (root / SH.LICENSE).unlink()
            self.assertIsNone(SH.load_agent_checker(root)[0])
            self.copy_policy(root)
            pin = json.loads((root / SH.PIN).read_text())
            pin["files"]["../outside.py"] = "sha256:" + "0" * 64
            (root / SH.PIN).write_text(json.dumps(pin))
            self.assertIsNone(SH.load_agent_checker(root)[0])

    def test_unavailable_shared_check_does_not_hide_schema_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "agent.md"
            path.write_text('---\nname: 42\ndescription: fixture\n---\nBody.')
            gate = {"gate_id": "audit-harness:local:conform-agent", "enforcement": "advisory"}
            with patch.object(CF, "load_agent_checker", return_value=(None, SH.EMPTY_SHA, "unavailable")):
                rows = CF.run_bundled("agent", gate, [str(path)], "0000000", "fixture", str(root),
                                      True, shared_validators=True)
            self.assertEqual(rows[0]["result"], "FAIL")
            self.assertTrue(rows[0]["metadata"]["indeterminate"])
            self.assertTrue(rows[0]["metadata"]["errors"])

    def test_missing_and_empty_tools_are_explicit_static_policy_only(self):
        for fields in ({}, {"tools": []}, {"tools": ""}):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "agents").mkdir()
                (root / "agents/example.md").write_text(
                    "---\n" + json.dumps({"name": "fixture", "description": "Fixture", **fields})
                    + "\n---\nUse mcp__fixture__read.")
                command = [sys.executable, str(ROOT / "scripts/conform.py"), str(root), "--strict"]
                default = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertEqual(default.returncode, 0, default.stderr)
                result = subprocess.run(command + ["--shared-validators"], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 1, result.stderr)
                row = next(r for r in json.loads(result.stdout) if r["gate_id"].endswith("conform-agent"))
                self.assertEqual(row["failure_mode"], "conform:shared-validator-violation")
                self.assertTrue(row["metadata"]["shared_validator"]["static_only"])
                self.assertIn("inheritance is not modeled", row["metadata"]["shared_validator"]["interpretation"])

    def test_cli_opt_in_preserves_errors_warnings_and_original_bytes(self):
        import jsonschema
        row_schema = json.loads((ROOT / "tests/fixtures/gate-result.schema.json").read_text())
        cases = [(["Read"], "Use mcp__fixture__read.", "FAIL", 1),
                 (["mcp__fixture__read"], "Ordinary prose.", "ADVISORY", 0),
                 (["mcp__fixture__read"], "Use mcp__fixture__read.", "PASS", 0)]
        for tools, body, verdict, code in cases:
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "agents").mkdir()
                raw = ("---\n" + json.dumps({"name": "fixture", "description": "Fixture agent", "tools": tools})
                       + "\n---\n" + body).encode()
                (root / "agents/example.md").write_bytes(raw)
                command = [sys.executable, str(ROOT / "scripts/conform.py"), str(root), "--strict"]
                default = subprocess.run(command, capture_output=True, text=True, timeout=30)
                default_row = next(r for r in json.loads(default.stdout) if r["gate_id"].endswith("conform-agent"))
                self.assertEqual(default_row["result"], "PASS")
                result = subprocess.run(command + ["--shared-validators"], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, code, result.stderr)
                row = next(r for r in json.loads(result.stdout) if r["gate_id"].endswith("conform-agent"))
                jsonschema.Draft202012Validator(row_schema).validate(row)
                self.assertEqual(row["result"], verdict)
                self.assertEqual(row["input_hash"], "sha256:" + hashlib.sha256(raw).hexdigest())
                self.assertNotEqual(row["policy_hash"], default_row["policy_hash"])
                self.assertTrue(row["metadata"]["shared_validator"]["static_only"])
                if verdict == "ADVISORY":
                    self.assertTrue(row["metadata"]["shared_validator"]["warnings"])
                if verdict == "FAIL":
                    self.assertEqual(row["failure_mode"], "conform:shared-validator-violation")


if __name__ == "__main__":
    unittest.main()
