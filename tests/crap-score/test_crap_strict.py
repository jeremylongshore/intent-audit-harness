#!/usr/bin/env python3
"""Strict-mode behavioral tests with an executed hermetic Radon substitute."""

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
SPEC = importlib.util.spec_from_file_location("crap_strict", ROOT / "scripts/crap_strict.py")
STRICT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRICT)


class StrictMeasurement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = "packages/a/src/math.py"
        self.test = "packages/a/src/math_test.py"
        for name in (self.source, self.test):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("def calculate(x):\n    return x + 1\n")
        self.provider = self.root / "radon"
        self.provider.write_text(
            f"#!{sys.executable}\n"
            f"import json,sys\n"
            f"from pathlib import Path\n"
            f"path=sys.argv[-1]\n"
            f"print(json.dumps({{path:json.loads(Path('provider.json').read_text())}}))\n"
        )
        self.provider.chmod(0o755)
        self.blocks = [{"type": "function", "name": "calculate", "lineno": 1, "complexity": 2}]
        self.save_blocks()
        self.coverage = {
            "files": {
                name: {
                    "summary": {"covered_lines": 2, "num_statements": 2, "percent_covered": 100},
                    "executed_lines": [1, 2],
                    "missing_lines": [],
                    "excluded_lines": [],
                }
                for name in (self.source, self.test)
            }
        }
        self.save_coverage()
        self.requested = {"src": [self.source], "test": [self.test]}

    def save_blocks(self):
        (self.root / "provider.json").write_text(json.dumps(self.blocks))

    def save_coverage(self):
        (self.root / "coverage.json").write_text(json.dumps(self.coverage))

    def measure(self, **kwargs):
        with patch.object(STRICT.shutil, "which", return_value=str(self.provider)):
            return STRICT.measure(
                self.root,
                kwargs.get("requested", self.requested),
                self.root / "coverage.json",
                kwargs.get("language", "python"),
            )

    def incomplete(self, phrase, **kwargs):
        report = self.measure(**kwargs)
        self.assertFalse(report["complete"])
        self.assertIn(phrase, " ".join(report["reasons"]))
        return report

    def test_workspace_colocated_scopes_are_measured_separately(self):
        report = self.measure()
        self.assertTrue(report["complete"], report["reasons"])
        self.assertEqual([r["crap"] for r in report["methods"]], [2, 2])
        self.assertEqual(report["scopes"]["src"]["scored_functions"], 1)
        self.assertEqual(report["scopes"]["test"]["discovered_files"], 1)
        self.assertEqual(report["coverage_basis"], STRICT.PROXY)

    def test_missing_provider(self):
        with patch.object(STRICT.shutil, "which", return_value=None):
            result = STRICT.measure(self.root, self.requested, self.root / "coverage.json", "python")
        self.assertFalse(result["complete"])
        self.assertIn("missing or unsupported complexity provider", result["reasons"])

    def test_provider_failure(self):
        self.provider.write_text(f"#!{sys.executable}\nraise SystemExit(3)\n")
        self.incomplete("provider failed")

    def test_provider_invalid_json(self):
        self.provider.write_text(f"#!{sys.executable}\nprint('not JSON')\n")
        self.incomplete("Expecting value")

    def test_provider_omitted_function(self):
        self.blocks = []
        self.save_blocks()
        self.incomplete("omitted source functions")

    def test_provider_unknown_function(self):
        self.blocks[0]["name"] = "invented"
        self.save_blocks()
        self.incomplete("unknown complexity function")

    def test_provider_duplicate_function(self):
        self.blocks += self.blocks
        self.save_blocks()
        self.incomplete("duplicate")

    def test_radon_class_method_dual_representation(self):
        method = {"type": "method", "name": "read", "lineno": 2, "complexity": 1, "classname": "Box", "closures": []}
        blocks = [{"type": "class", "name": "Box", "methods": [method]}, method]
        self.assertEqual(STRICT.complexity_rows(blocks, {(2, "read")}), {(2, "read"): 1})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            STRICT.complexity_rows(blocks + [method], {(2, "read")})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            STRICT.complexity_rows([blocks[0], dict(method, complexity=2)], {(2, "read")})

    def test_recursive_glob_cannot_silently_skip_symlink_directory(self):
        (self.root / "packages/linked").symlink_to(self.root / "packages/a", target_is_directory=True)
        self.incomplete("invalid scope pattern", requested={"src": ["packages/**/*.py"]})

    def test_provider_invalid_complexity(self):
        for value in (0, -1, True, 1.5, "2", float("inf")):
            with self.subTest(value=value):
                self.blocks[0]["complexity"] = value
                self.save_blocks()
                self.incomplete("invalid")

    def test_missing_coverage_file(self):
        (self.root / "coverage.json").unlink()
        self.incomplete("coverage unavailable")

    def test_missing_coverage_join(self):
        del self.coverage["files"][self.source]
        self.save_coverage()
        self.incomplete("coverage missing for requested file")

    def test_malformed_percentages(self):
        for value in (True, -1, 101, "100", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.coverage["files"][self.source]["summary"]["percent_covered"] = value
                self.save_coverage()
                self.incomplete("invalid coverage percentage")

    def test_inconsistent_line_evidence(self):
        self.coverage["files"][self.source]["executed_lines"] = [1]
        self.save_coverage()
        self.incomplete("disagree")

    def test_outside_coverage_path(self):
        self.coverage["files"]["../escape.py"] = self.coverage["files"][self.source]
        self.save_coverage()
        self.incomplete("outside root")

    def test_duplicate_normalized_coverage(self):
        self.coverage["files"][str(self.root / self.source)] = self.coverage["files"][self.source]
        self.save_coverage()
        self.incomplete("duplicate normalized coverage")

    def test_bad_scope_patterns(self):
        for pattern in ("", "../*.py", "/tmp/*.py", "missing/*.py"):
            with self.subTest(pattern=pattern):
                self.incomplete("scope pattern", requested={"src": [self.source, pattern]})

    def test_scope_overlap(self):
        self.incomplete("overlapping", requested={"src": [self.source], "test": [self.source]})

    def test_symlink_source(self):
        (self.root / "alias.py").symlink_to(self.root / self.source)
        self.incomplete("symlinked", requested={"src": ["alias.py"]})

    def test_no_methods_cannot_pass(self):
        (self.root / self.source).write_text("value = 1\n")
        self.blocks = []
        self.save_blocks()
        self.incomplete("no functions scored", requested={"src": [self.source]})

    def test_unimplemented_typescript_provider_is_not_a_pass(self):
        self.incomplete("unsupported strict provider", language="js")

    def test_source_changes_during_provider_execution(self):
        self.provider.write_text(
            f"#!{sys.executable}\n"
            f"import json,sys\n"
            f"from pathlib import Path\n"
            f"p=Path(sys.argv[-1]);p.write_text(p.read_text()+'# changed\\n')\n"
            f"print(json.dumps({{sys.argv[-1]:json.loads(Path('provider.json').read_text())}}))\n"
        )
        self.incomplete("source changed")

    def cli(self, *extra):
        env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"])
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/crap-score.py"),
                "--strict-measurement",
                "--root",
                str(self.root),
                "--lang",
                "python",
                "--coverage-json",
                "coverage.json",
                "--target",
                "src",
                "--source-glob",
                self.source,
                "--json",
                *extra,
            ],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_auto_detects_explicit_python_inventory(self):
        self.assertTrue(self.measure(language="auto")["complete"])

    def test_input_hash_changes_with_valid_coverage(self):
        before = json.loads(self.cli().stdout)["input_hash"]
        row = self.coverage["files"][self.source]
        row["summary"].update(covered_lines=1, percent_covered=50)
        row["executed_lines"] = [1]
        row["missing_lines"] = [2]
        self.save_coverage()
        after = json.loads(self.cli().stdout)["input_hash"]
        self.assertNotEqual(before, after)

    def test_coverage_modified_during_provider_rejected(self):
        self.provider.write_text(
            f"#!{sys.executable}\n"
            f"import json,sys\n"
            f"from pathlib import Path\n"
            f"p=Path('coverage.json');p.write_text(p.read_text()+' ')\n"
            f"print(json.dumps({{sys.argv[-1]:json.loads(Path('provider.json').read_text())}}))\n"
        )
        self.incomplete("coverage changed")

    def test_prior_file_changed_by_later_provider_rejected(self):
        self.provider.write_text(
            f"#!{sys.executable}\n"
            f"import json,sys\n"
            f"from pathlib import Path\n"
            f"p=Path({self.source!r})\n"
            f"if sys.argv[-1] != str(p): p.write_text(p.read_text()+'# changed\\n')\n"
            f"print(json.dumps({{sys.argv[-1]:json.loads(Path('provider.json').read_text())}}))\n"
        )
        self.incomplete("source changed")

    def test_json_duplicate_keys_rejected(self):
        (self.root / "coverage.json").write_text('{"files":{},"files":{}}')
        self.incomplete("duplicate JSON key")

    def test_cli_both_format_writes_csv(self):
        result = self.cli("--format", "both")
        self.assertEqual(result.returncode, 0)
        self.assertIn("calculate", (self.root / "reports/crap/crap-src.csv").read_text())

    def test_cli_success_and_threshold_failure(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "PASS")
        result = self.cli("--threshold-prod", "1")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["failure_mode"], "crap-threshold-exceeded")

    def test_cli_incomplete_fails_closed(self):
        self.blocks = []
        self.save_blocks()
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["result"], "FAIL")
        self.assertEqual(json.loads(result.stdout)["failure_mode"], "crap-measurement-incomplete")

    def test_cli_nonfinite_threshold_refused(self):
        self.assertEqual(self.cli("--threshold-avg", "nan").returncode, 2)

    def test_cli_unrequested_kind_refused(self):
        self.assertEqual(self.cli("--test-glob", self.test).returncode, 2)


if __name__ == "__main__":
    unittest.main()
