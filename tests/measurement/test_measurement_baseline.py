import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("measurement_baseline", ROOT / "ci/measurement_baseline.py")
BASELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASELINE)
SOURCE = ("def assess(attempts):\n"
          "    if attempts < 0:\n"
          "        return 'invalid'\n"
          "    if attempts > 7:\n"
          "        return 'exhausted'\n"
          "    return 'available'\n")


def coverage_file(executed, missing, executed_arcs=(), missing_arcs=()):
    return {
        "executed_lines": executed, "missing_lines": missing, "excluded_lines": [],
        "executed_branches": list(executed_arcs), "missing_branches": list(missing_arcs),
        "summary": {
            "covered_lines": len(executed), "num_statements": len(executed) + len(missing),
            "missing_lines": len(missing), "excluded_lines": 0,
            "covered_branches": len(executed_arcs), "missing_branches": len(missing_arcs),
            "num_branches": len(executed_arcs) + len(missing_arcs), "num_partial_branches": 0,
        },
    }


def function(name="assess", line=1, complexity=3, kind="function", **children):
    return {"name": name, "lineno": line, "complexity": complexity, "type": kind, **children}


class MeasurementBaseline(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.write("scripts/assess.py", SOURCE)
        self.provenance = {
            "schema_version": BASELINE.INPUT_SCHEMA, "commit_sha": "9a" * 20,
            "source_files": BASELINE.source_inventory(self.root),
            "providers": {
                "coverage": {"status": "available", "version": "7.13.0", "exit_code": 0},
                "radon": {"status": "available", "version": "6.0.1", "exit_code": 0},
            },
            "commands": [{"argv": ["python3", "tests/behavior.py"], "exit_code": 0}],
            "limitations": [],
        }
        self.coverage = {
            "meta": {"branch_coverage": True, "version": "7.13.0"},
            "files": {"scripts/assess.py": coverage_file([1, 2, 3], [4, 5, 6],
                                                       [[2, 3]], [[2, 4], [4, 5], [4, 6]])},
        }
        self.complexity = {"scripts/assess.py": [function()]}

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def refresh_inventory(self):
        self.provenance["source_files"] = BASELINE.source_inventory(self.root)

    def report(self):
        return BASELINE.build_report(self.root, self.provenance, self.coverage, self.complexity)

    def test_real_line_fraction_drives_explicit_crap_proxy(self):
        report = self.report()
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["scopes"]["production"]["eligible_functions"], 1)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 1)
        self.assertEqual(report["files"][0]["functions"][0], {
            "name": "assess", "lineno": 1, "complexity": 3,
            "coverage_percent": 50.0, "coverage_basis": BASELINE.PROXY, "crap": 4.125,
        })
        self.assertEqual(report["scopes"]["production"]["coverage"]["branch_percent"], 25.0)
        self.assertEqual(report["thresholds"], None)
        self.assertEqual(report["enforcement"], "advisory")
        self.assertNotIn("grade", report)

    def test_missing_providers_leave_eligible_denominator_and_no_score(self):
        for provider in self.provenance["providers"].values():
            provider.update(status="unavailable", version=None, exit_code=None)
        report = self.report()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["scopes"]["production"]["eligible_files"], 1)
        self.assertEqual(report["scopes"]["production"]["eligible_functions"], 1)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertEqual(report["scopes"]["production"]["coverage"]["line_percent"], None)
        self.assertIn("coverage: provider unavailable", report["reasons"])
        self.assertIn("radon: provider unavailable", report["reasons"])

    def test_failed_provider_artifact_is_not_accepted(self):
        self.provenance["providers"]["coverage"].update(status="failed", exit_code=1)
        report = self.report()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["files"][0]["functions"][0]["crap"], None)
        self.assertEqual(report["scopes"]["production"]["coverage_matched_files"], 0)
        self.assertIn("coverage: provider failed", report["reasons"])

    def test_success_status_with_failed_exit_is_rejected(self):
        self.provenance["providers"]["radon"]["exit_code"] = 7
        report = self.report()
        self.assertEqual(report["scopes"]["production"]["complexity_functions"], 0)
        self.assertIn("radon: successful provider exit and version required", report["reasons"])

    def test_measured_zero_differs_from_missing_coverage(self):
        self.coverage["files"]["scripts/assess.py"] = coverage_file(
            [], [1, 2, 3, 4, 5, 6], [], [[2, 3], [2, 4], [4, 5], [4, 6]]
        )
        report = self.report()
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["files"][0]["functions"][0]["coverage_percent"], 0.0)
        self.assertEqual(report["files"][0]["functions"][0]["crap"], 12.0)
        self.coverage["files"] = {}
        missing = self.report()
        self.assertEqual(missing["status"], "partial")
        self.assertEqual(missing["files"][0]["functions"][0]["coverage_percent"], None)
        self.assertEqual(missing["files"][0]["functions"][0]["crap"], None)

    def test_unexecuted_eligible_source_remains_in_line_denominator(self):
        self.write("scripts/retry.py", "def retry():\n    return 11\n")
        self.refresh_inventory()
        self.coverage["files"]["scripts/retry.py"] = coverage_file([], [1, 2])
        self.complexity["scripts/retry.py"] = [function("retry", complexity=1)]
        scope = self.report()["scopes"]["production"]
        self.assertEqual(scope["eligible_files"], 2)
        self.assertEqual(scope["coverage_matched_files"], 2)
        self.assertEqual(scope["coverage"]["num_statements"], 8)
        self.assertEqual(scope["coverage"]["covered_lines"], 3)
        self.assertEqual(scope["coverage"]["line_percent"], 37.5)

    def test_absent_eligible_file_reports_incomplete_denominator(self):
        self.write("scripts/retry.py", "def retry():\n    return 11\n")
        self.refresh_inventory()
        report = self.report()
        scope = report["scopes"]["production"]
        self.assertEqual(report["status"], "partial")
        self.assertEqual(scope["eligible_files"], 2)
        self.assertEqual(scope["coverage_matched_files"], 1)
        self.assertEqual(scope["coverage"]["complete"], False)
        self.assertIn("scripts/retry.py: coverage missing", report["reasons"])

    def test_empty_complexity_mapping_never_erases_source_functions(self):
        self.complexity = {}
        report = self.report()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["scopes"]["production"]["eligible_functions"], 1)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertIn("scripts/assess.py: complexity matched 0 of 1 eligible functions", report["reasons"])

    def test_empty_source_scope_has_null_percentages(self):
        (self.root / "scripts/assess.py").unlink()
        self.refresh_inventory()
        self.coverage["files"] = {}
        self.complexity = {}
        report = self.report()
        self.assertEqual(report["status"], "empty")
        self.assertEqual(report["scopes"]["production"]["eligible_files"], 0)
        self.assertEqual(report["scopes"]["production"]["coverage"]["line_percent"], None)
        self.assertEqual(report["scopes"]["production"]["coverage"]["branch_percent"], None)

    def test_comment_only_file_has_no_invented_one_hundred_percent(self):
        self.write("scripts/assess.py", "# no executable statements\n")
        self.refresh_inventory()
        self.coverage["files"]["scripts/assess.py"] = coverage_file([], [])
        self.complexity["scripts/assess.py"] = []
        report = self.report()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["files"][0]["coverage"]["status"], "empty")
        self.assertEqual(report["files"][0]["coverage"]["line_percent"], None)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)

    def test_source_hash_mismatch_invalidates_all_provider_evidence(self):
        self.write("scripts/assess.py", SOURCE.replace("7", "13"))
        report = self.report()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["source_identity_valid"], False)
        self.assertEqual(report["scopes"]["production"]["coverage_matched_files"], 0)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertIn("source inventory or SHA256 differs from collection provenance", report["reasons"])

    def test_new_eligible_source_invalidates_stale_inventory(self):
        self.write("scripts/retry.py", "def retry():\n    return 11\n")
        self.assertEqual(self.report()["source_identity_valid"], False)

    def test_recorded_source_change_invalidates_evidence_even_if_source_was_restored(self):
        self.provenance["source_unchanged_after_commands"] = False
        report = self.report()
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["source_identity_valid"], False)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertIn("source changed during collection; provider evidence is not bound to one inventory",
                      report["reasons"])

    def test_paths_outside_scope_are_reported_without_fabricating_zero(self):
        self.coverage["files"] = {"../other/scripts/assess.py": self.coverage["files"]["scripts/assess.py"]}
        report = self.report()
        self.assertEqual(report["files"][0]["coverage"], None)
        self.assertEqual(report["files"][0]["functions"][0]["crap"], None)
        self.assertIn("coverage: path outside root: ../other/scripts/assess.py", report["reasons"])

    def test_absolute_source_path_joins_exact_root_relative_identity(self):
        self.coverage["files"][str(self.root / "scripts/assess.py")] = self.coverage["files"].pop("scripts/assess.py")
        self.assertEqual(self.report()["scopes"]["production"]["scored_functions"], 1)

    def test_aliased_duplicate_paths_are_not_double_counted(self):
        self.coverage["files"]["scripts/./assess.py"] = copy.deepcopy(self.coverage["files"]["scripts/assess.py"])
        report = self.report()
        self.assertEqual(report["scopes"]["production"]["coverage_matched_files"], 0)
        self.assertIn("coverage: duplicate normalized path: scripts/assess.py", report["reasons"])

    def test_classes_methods_and_closures_are_counted_once(self):
        self.write("scripts/assess.py", "class Worker:\n"
                   "    def dispatch(self):\n"
                   "        def deliver():\n"
                   "            return 11\n"
                   "        return deliver()\n")
        self.refresh_inventory()
        self.coverage["files"]["scripts/assess.py"] = coverage_file([1, 2, 3, 4, 5], [])
        method = function("dispatch", 2, 2, "method", closures=[function("deliver", 3, 1)])
        self.complexity["scripts/assess.py"] = [
            {"name": "Worker", "type": "class", "lineno": 1, "complexity": 99, "methods": [method]}, method,
        ]
        report = self.report()
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["scopes"]["production"]["eligible_functions"], 2)
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 2)
        self.assertEqual([(row["name"], row["crap"]) for row in report["files"][0]["functions"]],
                         [("Worker.dispatch", 2.0), ("Worker.dispatch.deliver", 1.0)])

    def test_conflicting_duplicate_function_metrics_are_invalid(self):
        self.complexity["scripts/assess.py"].append(function(complexity=5))
        report = self.report()
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertIn("scripts/assess.py: complexity invalid: conflicting duplicate complexity: assess:1",
                      report["reasons"])

    def test_unknown_function_identity_cannot_join_by_filename_alone(self):
        self.complexity["scripts/assess.py"] = [function("different_function")]
        report = self.report()
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertIn("scripts/assess.py: complexity invalid: complexity function absent from source: "
                      "different_function:1", report["reasons"])

    def test_malformed_coverage_counts_and_nan_do_not_produce_scores(self):
        for field, value in (("covered_lines", True), ("num_statements", -4),
                             ("covered_branches", 7), ("percent_covered", float("nan"))):
            with self.subTest(field=field):
                original = copy.deepcopy(self.coverage)
                self.coverage["files"]["scripts/assess.py"]["summary"][field] = value
                report = self.report()
                self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
                self.assertEqual(report["files"][0]["coverage"], None)
                self.coverage = original

    def test_malformed_provider_shapes_remain_diagnostic(self):
        for artifact in ([], "malformed", 19, {}):
            with self.subTest(artifact=artifact):
                report = BASELINE.build_report(self.root, self.provenance, artifact, artifact)
                self.assertEqual(report["status"], "unavailable")
                self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)

    def test_malformed_and_unrepresentable_complexity_are_diagnostic(self):
        for value in (True, -2, 0, float("nan"), 10 ** 400):
            with self.subTest(value=value):
                self.complexity["scripts/assess.py"] = [function(complexity=value)]
                report = self.report()
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)

    def test_missing_branch_data_does_not_claim_complete_baseline(self):
        self.coverage["meta"]["branch_coverage"] = False
        report = self.report()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["scopes"]["production"]["coverage_matched_files"], 0)
        self.assertIn("coverage: artifact metadata/version invalid or branch data absent", report["reasons"])

    def test_behavioral_failure_remains_visible_even_with_usable_metrics(self):
        self.provenance["commands"][0]["exit_code"] = 9
        report = self.report()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["failed_commands"], [{"argv": ["python3", "tests/behavior.py"], "exit_code": 9}])
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 1)

    def test_production_and_tests_have_separate_denominators(self):
        self.write("tests/unit/test_assess.py", "def test_retries():\n    assert 11 > 7\n")
        self.refresh_inventory()
        self.coverage["files"]["tests/unit/test_assess.py"] = coverage_file([1, 2], [])
        self.complexity["tests/unit/test_assess.py"] = [function("test_retries", complexity=2)]
        report = self.report()
        self.assertEqual(report["scopes"]["production"]["coverage"]["line_percent"], 50.0)
        self.assertEqual(report["scopes"]["test"]["coverage"]["line_percent"], 100.0)
        self.assertEqual(report["scopes"]["production"]["eligible_files"], 1)
        self.assertEqual(report["scopes"]["test"]["eligible_files"], 1)

    def test_mirrors_fixtures_and_symlinks_do_not_expand_canonical_scope(self):
        self.write("python/src/intent_audit_harness/scripts/assess.py", SOURCE)
        self.write("rust/scripts/assess.py", SOURCE)
        self.write("tests/fixtures/synthetic/assess.py", SOURCE)
        (self.root / "scripts/alias.py").symlink_to(self.root / "scripts/assess.py")
        inventory = BASELINE.source_inventory(self.root)
        self.assertEqual(inventory, [{"path": "scripts/assess.py", "kind": "production",
                                     "sha256": hashlib.sha256(SOURCE.encode()).hexdigest()}])
        excluded = self.report()["excluded_files"]
        self.assertEqual([item["path"] for item in excluded], [
            "python/src/intent_audit_harness/scripts/assess.py", "rust/scripts/assess.py",
            "tests/fixtures/synthetic/assess.py",
        ])

    def run_cli(self, provenance=None, coverage=None, complexity=None):
        paths = {}
        for name, value in (("provenance", provenance), ("coverage", coverage), ("complexity", complexity)):
            paths[name] = self.root / (name + ".json")
            if value is not None:
                paths[name].write_text(value if isinstance(value, str) else json.dumps(value))
        output = self.root / "report"
        result = subprocess.run([sys.executable, str(ROOT / "ci/measurement_baseline.py"),
                                 "--root", str(self.root), "--provenance", str(paths["provenance"]),
                                 "--coverage", str(paths["coverage"]), "--complexity", str(paths["complexity"]),
                                 "--output-dir", str(output)], capture_output=True, text=True)
        return result, output

    def test_cli_missing_artifacts_emits_json_and_markdown_without_traceback(self):
        result, output = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        report = json.loads((output / "summary.json").read_text())
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["scopes"]["production"]["eligible_functions"], 1)
        self.assertIn("Status: **unavailable**", (output / "summary.md").read_text())

    def test_cli_malformed_json_is_an_explicit_diagnostic(self):
        result, output = self.run_cli(self.provenance, "{broken", self.complexity)
        self.assertEqual(result.returncode, 0)
        report = json.loads((output / "summary.json").read_text())
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertTrue(any(reason.startswith("coverage: artifact unreadable or malformed:")
                            for reason in report["reasons"]))

    def test_cli_rejects_raw_artifact_digest_mismatch(self):
        self.provenance["artifacts"] = {"coverage.json": "0" * 64}
        result, output = self.run_cli(self.provenance, self.coverage, self.complexity)
        self.assertEqual(result.returncode, 0)
        report = json.loads((output / "summary.json").read_text())
        self.assertEqual(report["scopes"]["production"]["scored_functions"], 0)
        self.assertIn("coverage: artifact SHA256 differs from provenance", report["reasons"])

    def test_cli_duplicate_keys_are_malformed_artifacts(self):
        result, output = self.run_cli(self.provenance, '{"files": {}, "files": {}}', self.complexity)
        self.assertEqual(result.returncode, 0)
        report = json.loads((output / "summary.json").read_text())
        self.assertIn("coverage: artifact unreadable or malformed: duplicate JSON key: files", report["reasons"])

    def test_cli_nonfinite_json_is_malformed_artifact(self):
        result, output = self.run_cli(self.provenance, '{"files": NaN}', self.complexity)
        self.assertEqual(result.returncode, 0)
        report = json.loads((output / "summary.json").read_text())
        self.assertIn("coverage: artifact unreadable or malformed: nonfinite JSON number: NaN", report["reasons"])

    def test_cli_write_failure_returns_nonzero(self):
        self.write("report", "occupied destination")
        result, _ = self.run_cli(self.provenance, self.coverage, self.complexity)
        self.assertEqual(result.returncode, 2)
        self.assertIn("measurement report could not be written:", result.stderr)


if __name__ == "__main__":
    unittest.main()
