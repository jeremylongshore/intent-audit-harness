#!/usr/bin/env python3
"""Offline acceptance and falsification of the read-only compliance verifier."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/skill-gates.py"
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("gates", SOURCE)
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


class SkillGates(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "source.txt").write_text("source\n")
        self.policy = {"schema": G.POLICY, "mode": "observe", "skill": "verify-pilot",
                       "inputs": ["source.txt"], "must_read": ["source.txt"],
                       "must_run": [{"id": "unit", "argv": [sys.executable, "-V"],
                                     "timeout_ms": 1000, "min_tests": 1}],
                       "checklist": ["tests"], "deny_tools": ["WebFetch"]}
        self.path = self.root / "policy.json"
        self.path.write_text(json.dumps(self.policy))
        self.policy, self.policy_hash = G.policy_at(self.path)
        self.current = G.identity(self.root, self.policy, self.policy_hash, SOURCE)
        self.binding = G.digest(G.canonical(self.current))
        self.receipt = {"schema": G.RECEIPT, "session": "session-a", "identity": self.current,
                        "reads": {"source.txt": self.current["inputs"]["source.txt"]},
                        "commands": {"unit": {"status": "completed", "exit_code": 0, "tests_passed": 3,
                                              "tests_failed": 0, "identity_sha256": self.binding,
                                              "stdout_sha256": "a" * 64}},
                        "report": {"checklist": ["tests"], "identity_sha256": self.binding}}

    def errors(self, receipt=None, current=None):
        return G.assess(self.policy, self.receipt if receipt is None else receipt,
                        current or self.current, "session-a")

    def test_complete_evidence_passes_without_writes(self):
        before = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(self.errors(), [])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_absence_malformed_session_and_report_fail(self):
        for value in (None, [], {}, {"extra": True}):
            with self.subTest(value=value):
                self.assertTrue(G.assess(self.policy, value, self.current, "session-a"))
        for field, value in (("session", "session-b"), ("schema", "future"), ("reads", {}),
                             ("commands", {}), ("report", None), ("report", {"checklist": ["tests"]})):
            with self.subTest(field=field, value=value):
                r = copy.deepcopy(self.receipt)
                r[field] = value
                self.assertTrue(self.errors(r))

    def test_failed_empty_partial_and_forged_count_observations_fail(self):
        for field, value in (("status", "running"), ("status", "timed_out"), ("status", "inputs_changed"),
                             ("exit_code", 1), ("exit_code", False), ("tests_passed", 0),
                             ("tests_passed", True), ("tests_passed", "3"), ("tests_failed", 1),
                             ("tests_failed", False), ("identity_sha256", "0" * 64),
                             ("stdout_sha256", "invalid")):
            with self.subTest(field=field, value=value):
                r = copy.deepcopy(self.receipt)
                r["commands"]["unit"][field] = value
                self.assertIn("run:unit", self.errors(r))

    def test_every_identity_component_is_bound(self):
        for key in self.current:
            with self.subTest(component=key):
                changed = copy.deepcopy(self.current)
                changed[key] = "changed"
                if key == "inputs":
                    changed[key] = {"source.txt": "0" * 64}
                self.assertIn("receipt:stale-identity", self.errors(current=changed))
        (self.root / "source.txt").write_text("changed\n")
        changed = G.identity(self.root, self.policy, self.policy_hash, SOURCE)
        self.assertIn("receipt:stale-identity", self.errors(current=changed))

    def test_policy_typos_duplicates_bounds_and_paths_refuse(self):
        for key, value in (("schema", "future"), ("mode", "disabled"), ("inputs", ["../escape"]),
                           ("must_read", []), ("checklist", ["x", "x"]), ("must_run", []),
                           ("deny_tools", "Bash"), ("extra", 1)):
            with self.subTest(field=key):
                p = copy.deepcopy(self.policy)
                p[key] = value
                self.path.write_text(json.dumps(p))
                with self.assertRaises(ValueError):
                    G.policy_at(self.path)
        self.path.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):
            G.policy_at(self.path)
        for name in ("../escape", "/absolute", "a//b", "./source.txt", "a\\b"):
            with self.assertRaises(ValueError):
                G.relative(name)

    def test_symlink_and_missing_executable_refuse(self):
        (self.root / "link").symlink_to(self.root / "source.txt")
        with self.assertRaises(ValueError):
            G.file_path(self.root, "link")
        self.policy["must_run"][0]["argv"] = ["iep-intentionally-missing-executable"]
        with self.assertRaises(ValueError):
            G.identity(self.root, self.policy, self.policy_hash, SOURCE)

    def test_cli_advisory_and_strict_never_pass_missing_evidence(self):
        args = ["node", str(SOURCE.parents[1] / "bin/audit-harness.js"), "skill-gates",
                "--policy", str(self.path), "--receipt", str(self.root / "missing.json"),
                "--root", str(self.root), "--session", "session-a", "--collector", str(SOURCE), "--json"]
        for strict, expected, code in ((False, "ADVISORY", 0), (True, "FAIL", 1)):
            out = subprocess.run(args + (["--strict"] if strict else []), capture_output=True, text=True)
            self.assertEqual(out.returncode, code, out.stderr)
            self.assertEqual(json.loads(out.stdout)["result"], expected)

    def test_rows_cross_the_existing_evidence_bundle_boundary(self):
        for errors, strict, expected in (([], False, "pass"), (["read:source.txt"], False, "advisory"),
                                         (["run:unit"], True, "fail")):
            with self.subTest(expected=expected):
                row = G.row(self.policy_hash, self.receipt, errors, strict)
                bundle = self.root / (expected + ".json")
                output = subprocess.run(["bash", str(SOURCE.parent / "emit-evidence.sh"), "--append-to", str(bundle)],
                                        input=json.dumps(row), text=True, capture_output=True)
                self.assertEqual(output.returncode, 0, output.stderr)
                self.assertEqual(json.loads(bundle.read_text())[0]["predicate"]["gate_decision"], expected)


if __name__ == "__main__":
    unittest.main()
