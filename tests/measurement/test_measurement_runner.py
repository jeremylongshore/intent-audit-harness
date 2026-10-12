#!/usr/bin/env python3
"""Runner process isolation, failure handling, and optional real-provider proof."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ci"))
import run_measurement as runner  # noqa: E402


HAS_PROVIDERS = all(importlib.util.find_spec(name) is not None for name in ("coverage", "radon"))


class MeasurementRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="measurement-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "scripts/branchy.py").write_text(
            "def choose(value):\n    if value:\n        return 1\n    return 2\n\nchoose(False)\n",
        )
        (self.root / "scripts/unexecuted-script.py").write_text("def untouched():\n    return 3\n")
        (self.root / "tests/test_unexecuted.py").write_text("def test_example():\n    assert True\n")
        for args in (("init", "-q"), ("add", "."),
                     ("-c", "user.name=measurement-test", "-c", "user.email=measurement@example.invalid",
                      "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture")):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_missing_providers_preserve_behavior_failure_and_emit_reports(self):
        output = self.base / "out"
        command = (sys.executable, "-c", "raise SystemExit(7)")
        with patch.object(runner, "BEHAVIOR_COMMANDS", (command,)), patch.dict(os.environ, PATH=os.defpath):
            code = runner.collect(self.root, output, str(self.base / "missing-python"),
                                  str(self.base / "missing-radon-python"))
        self.assertEqual(code, 1)
        provenance = json.loads((output / "provenance.json").read_text())
        self.assertEqual(provenance["commands"][0]["exit_code"], 7)
        self.assertEqual(provenance["providers"]["coverage"]["status"], "unavailable")
        self.assertIsNone(json.loads((output / "coverage.json").read_text()))
        self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "unavailable")
        self.assertTrue((output / "summary.md").is_file())

    def test_output_reuse_is_rejected(self):
        output = self.base / "out"
        output.mkdir()
        (output / "coverage.json").write_text("stale")
        with self.assertRaisesRegex(ValueError, "empty"):
            runner.collect(self.root, output, sys.executable, sys.executable)

    def test_source_changes_invalidate_collection_and_return_failure(self):
        output = self.base / "out"
        command = (sys.executable, "-c", "from pathlib import Path; "
                   "Path('scripts/branchy.py').write_text('def changed():\\n    return 5\\n')")
        with patch.object(runner, "BEHAVIOR_COMMANDS", (command,)), patch.dict(os.environ, PATH=os.defpath):
            code = runner.collect(self.root, output, str(self.base / "missing-python"),
                                  str(self.base / "missing-radon-python"))
        self.assertEqual(code, 2)
        provenance = json.loads((output / "provenance.json").read_text())
        self.assertFalse(provenance["source_unchanged_after_commands"])
        summary = json.loads((output / "summary.json").read_text())
        self.assertFalse(summary["source_identity_valid"])
        self.assertEqual(summary["status"], "unavailable")

    def test_ambient_radon_is_rejected_before_behavior(self):
        tool_dir = self.base / "ambient"
        tool_dir.mkdir()
        radon = tool_dir / "radon"
        radon.write_text("#!/bin/sh\nexit 0\n")
        radon.chmod(0o755)
        with patch.dict(os.environ, PATH=str(tool_dir)):
            with self.assertRaisesRegex(ValueError, "radon remains"):
                runner.behavioral_environment(self.base, sys.executable, [], None)

    @unittest.skipUnless(HAS_PROVIDERS, "run with the locked measurement interpreter for provider proof")
    def test_real_subprocess_coverage_unexecuted_denominator_and_complexity(self):
        output = self.base / "out"
        # Two subprocess boundaries: shell -> Python -> shell -> Python product.
        child = "import subprocess; subprocess.run(['bash','-c','python3 scripts/branchy.py'],check=True)"
        command = ("bash", "-c", "python3 -c " + __import__("shlex").quote(child))
        with patch.object(runner, "BEHAVIOR_COMMANDS", (command,)), patch.dict(os.environ, PATH=os.defpath):
            self.assertEqual(runner.collect(self.root, output, sys.executable, sys.executable), 0)
        coverage = json.loads((output / "coverage.json").read_text())
        paths = {str((self.root / name).resolve()): info for name, info in coverage["files"].items()}
        branchy = paths[str(self.root / "scripts/branchy.py")]
        self.assertTrue(coverage["meta"]["branch_coverage"])
        self.assertIn(4, branchy["executed_lines"])
        self.assertIn(3, branchy["missing_lines"])
        self.assertGreater(branchy["summary"]["missing_branches"], 0)
        unexecuted = paths[str(self.root / "scripts/unexecuted-script.py")]
        self.assertEqual(unexecuted["executed_lines"], [])
        self.assertGreater(len(unexecuted["missing_lines"]), 0)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(summary["status"], "measured")
        self.assertEqual(summary["scopes"]["production"]["scored_functions"], 2)
        provenance = json.loads((output / "provenance.json").read_text())
        self.assertTrue(provenance["source_unchanged_after_commands"])
        self.assertIsNone(provenance["behavioral_radon_executable"])

    @unittest.skipUnless(HAS_PROVIDERS, "run with the locked measurement interpreter for provider proof")
    def test_provider_modules_available_but_legacy_scorer_and_golden_see_no_radon(self):
        config = self.base / "coverage.ini"
        config.write_text("[run]\nbranch = true\nparallel = true\ndisable_warnings = no-data-collected\n"
                          f"data_file = {self.base / '.coverage'}\ninclude = {ROOT / 'scripts/crap-score.py'}\n")
        with patch.dict(os.environ, PATH=os.pathsep.join([str(Path(sys.executable).parent), os.defpath])):
            env = runner.behavioral_environment(self.base, sys.executable, [sys.executable], config)
        # The actual production lookup is the contract, not a mock of shutil.which.
        script = ("import radon,runpy,sys; scorer=runpy.run_path(sys.argv[1]); "
                  "assert scorer['which_or_none']('radon') is None")
        result = subprocess.run(["python3", "-c", script, str(ROOT / "scripts/crap-score.py")],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        golden = subprocess.run(["bash", "tests/golden/run-golden.sh"], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        self.assertEqual(golden.returncode, 0, golden.stdout + golden.stderr)
        self.assertTrue(list(self.base.glob(".coverage.*")))


if __name__ == "__main__":
    unittest.main()
