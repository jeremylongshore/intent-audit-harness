#!/usr/bin/env python3
"""Advisory Node collection integrity and optional native-provider qualification."""
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
import node_measurement as measurement  # noqa: E402
import run_measurement as runner  # noqa: E402

PROVIDER = os.environ.get("AUDIT_HARNESS_NODE_TEST_PROVIDER_ROOT")
HAS_PROVIDER = bool(PROVIDER and (Path(PROVIDER) / "node_modules/c8/package.json").is_file())


def reports(root, output, sources, covered=0):
    """A small complete converter response; not execution evidence."""
    output.mkdir(exist_ok=True)
    records, summaries = {}, {}
    for item in sources:
        path = str(root / item["path"])
        records[path] = {"path": path, "statementMap": {"0": {
            "start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 1}}},
            "s": {"0": covered}, "fnMap": {}, "f": {}, "branchMap": {}, "b": {}}
        summaries[path] = {key: {"total": 1, "covered": covered} for key in ("statements", "lines")}
        summaries[path].update({key: {"total": 0, "covered": 0} for key in ("functions", "branches")})
    measurement.write_json(output / "coverage-final.json", records)
    measurement.write_json(output / "coverage-summary.json", summaries)


class NodeMeasurementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="node-measurement-test-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "repo"
        self.output = self.base / "output"
        self.output.mkdir()
        for name, text in {
            "bin/audit-harness.js": "console.log('covered');\n",
            "scripts/crap_typescript.mjs": "export function unused() { return 1; }\n",
            "tests/cli/example.test.cjs": "require('../../bin/audit-harness.js');\n",
            "tests/fixtures/example.js": "throw new Error('fixture');\n",
            "python/src/intent_audit_harness/scripts/copied.mjs": "export const copy = 1;\n",
            "ci/example.mjs": "export const ci = 1;\n",
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.state = measurement.prepare(self.root, self.output, None)

    def fake_provider(self):
        executable = self.base / "converter"
        executable.write_text("fixture")
        self.state["provider"] = {"status": "available", "node": str(executable),
                                  "c8": str(executable), "hashes": {str(executable): measurement.digest(executable)}}
        measurement.write_json(Path(self.state["raw_directory"]) / "coverage.json", {"result": [{
            "url": (self.root / "bin/audit-harness.js").as_uri(),
            "functions": [{"ranges": [{"startOffset": 0, "endOffset": 1, "count": 0}]}],
        }]})

    def converter(self, argv, **kwargs):
        self.assertNotIn("NODE_V8_COVERAGE", kwargs["env"])
        self.assertNotIn("COVERAGE_PROCESS_START", kwargs["env"])
        self.assertEqual(argv[-2], "--config")
        config = json.loads(Path(argv[-1]).read_text())
        self.assertEqual(config["exclude"], [])
        self.assertTrue(config["all"])
        self.assertEqual(config["src"], [str(self.root)])
        reports(self.root, Path(config["reports-dir"]), self.state["sources"])
        return subprocess.CompletedProcess(argv, 0)

    def test_inventory_separates_production_tests_and_excludes_copies(self):
        self.assertEqual([(s["path"], s["kind"]) for s in self.state["sources"]], [
            ("bin/audit-harness.js", "production"), ("scripts/crap_typescript.mjs", "production"),
            ("tests/cli/example.test.cjs", "test"),
        ])
        (self.root / "bin/alias.js").symlink_to(self.root / "bin/audit-harness.js")
        self.assertEqual(measurement.inventory(self.root), self.state["sources"])

    def test_missing_provider_is_unavailable_not_zero(self):
        state = measurement.finish(self.root, self.output, self.state)
        self.assertEqual(state["status"], "unavailable")
        self.assertNotIn("scopes", state)
        self.assertIn("not requested", state["reasons"][0])
        self.assertIsNone(state["crap"])

    def test_missing_raw_data_is_unavailable_even_when_all_could_invent_zero(self):
        self.fake_provider()
        for p in Path(self.state["raw_directory"]).glob("*"):
            p.unlink()
        with patch.object(measurement.subprocess, "run") as run:
            result = measurement.finish(self.root, self.output, self.state)
        run.assert_not_called()
        self.assertIn("not measured zero", result["reasons"][0])

    def test_changed_source_invalidates_identity_before_conversion(self):
        self.fake_provider()
        (self.root / "bin/audit-harness.js").write_text("changed")
        result = measurement.finish(self.root, self.output, self.state)
        self.assertFalse(result["source_identity_valid"])
        self.assertEqual(result["status"], "unavailable")

    def test_converter_failure_keeps_nonzero_receipt(self):
        self.fake_provider()
        with patch.object(measurement.subprocess, "run", return_value=subprocess.CompletedProcess([], 9)):
            result = measurement.finish(self.root, self.output, self.state)
        self.assertEqual(result["commands"][0]["exit_code"], 9)
        self.assertNotIn("scopes", result)

    def test_explicit_config_and_converter_isolation_preserve_real_zero(self):
        self.fake_provider()
        with patch.object(measurement.subprocess, "run", side_effect=self.converter), patch.dict(
            os.environ, NODE_V8_COVERAGE="ambient", COVERAGE_PROCESS_START="ambient",
        ):
            result = measurement.finish(self.root, self.output, self.state)
        self.assertEqual(result["status"], "measured")
        self.assertEqual(result["scopes"]["production"]["lines"]["percent"], 0)
        self.assertEqual(result["scopes"]["test"]["files"], 1)
        self.assertTrue(result["artifacts"])

    def test_source_changed_by_converter_invalidates_completed_report(self):
        self.fake_provider()

        def change(argv, **kwargs):
            result = self.converter(argv, **kwargs)
            (self.root / "bin/audit-harness.js").write_text("different")
            return result

        with patch.object(measurement.subprocess, "run", side_effect=change):
            result = measurement.finish(self.root, self.output, self.state)
        self.assertFalse(result["source_identity_valid"])
        self.assertNotIn("scopes", result)

    def test_provider_change_is_unavailable(self):
        self.fake_provider()
        Path(self.state["provider"]["c8"]).write_text("changed")
        result = measurement.finish(self.root, self.output, self.state)
        self.assertIn("provider changed", result["reasons"][0])

    def test_missing_foreign_duplicate_alias_and_invalid_counts_are_refused(self):
        directory = self.output / "node-report"
        for mode in ("missing", "foreign", "alias", "counts", "malformed-counts", "keys"):
            with self.subTest(mode=mode):
                reports(self.root, directory, self.state["sources"])
                path = directory / "coverage-summary.json"
                data = json.loads(path.read_text())
                key = str(self.root / "bin/audit-harness.js")
                if mode == "missing":
                    data.pop(key)
                elif mode == "foreign":
                    data[str(self.base / "outside.js")] = data[key]
                elif mode == "alias":
                    data[str(self.root / "bin/../bin/audit-harness.js")] = data[key]
                elif mode == "counts":
                    data[key]["lines"]["covered"] = 2
                elif mode == "malformed-counts":
                    data[key]["lines"] = []
                else:
                    path = directory / "coverage-final.json"
                    data = json.loads(path.read_text())
                    data[key]["s"] = {}
                measurement.write_json(path, data)
                with self.assertRaises(ValueError):
                    measurement.validate_reports(self.root, directory, self.state["sources"])

    def test_malformed_native_json_is_unavailable(self):
        self.fake_provider()
        (Path(self.state["raw_directory"]) / "coverage.json").write_text('{"result": false}')
        result = measurement.finish(self.root, self.output, self.state)
        self.assertIn("Malformed native", result["reasons"][0])

    def test_only_npm_internals_do_not_prove_canonical_instrumentation(self):
        self.fake_provider()
        measurement.write_json(Path(self.state["raw_directory"]) / "coverage.json", {"result": [
            {"url": "file:///usr/lib/node_modules/npm/bin/npm-cli.js", "functions": [{}]},
        ]})
        with patch.object(measurement.subprocess, "run") as run:
            result = measurement.finish(self.root, self.output, self.state)
        run.assert_not_called()
        self.assertIn("instrumentation unproven", result["reasons"][0])

    def test_invalid_hits_and_summary_disagreement_are_refused(self):
        directory = self.output / "node-report"
        for value in (-1, True, "1", 0.5, 1):
            with self.subTest(hit=value):
                reports(self.root, directory, self.state["sources"])
                path = directory / "coverage-final.json"
                data = json.loads(path.read_text())
                data[str(self.root / "bin/audit-harness.js")]["s"]["0"] = value
                measurement.write_json(path, data)
                with self.assertRaises(ValueError):
                    measurement.validate_reports(self.root, directory, self.state["sources"])

    def test_line_only_summary_disagreement_is_refused(self):
        directory = self.output / "node-report"
        reports(self.root, directory, self.state["sources"])
        path = directory / "coverage-summary.json"
        data = json.loads(path.read_text())
        data[str(self.root / "bin/audit-harness.js")]["lines"]["covered"] = 1
        measurement.write_json(path, data)
        with self.assertRaisesRegex(ValueError, "hits and summary"):
            measurement.validate_reports(self.root, directory, self.state["sources"])

    def test_shared_statement_line_uses_max_hit_once(self):
        directory = self.output / "node-report"
        reports(self.root, directory, self.state["sources"])
        path = directory / "coverage-final.json"
        data = json.loads(path.read_text())
        key = str(self.root / "bin/audit-harness.js")
        data[key]["statementMap"]["1"] = data[key]["statementMap"]["0"]
        data[key]["s"]["1"] = 7
        measurement.write_json(path, data)
        path = directory / "coverage-summary.json"
        data = json.loads(path.read_text())
        data[key]["statements"] = {"total": 2, "covered": 1}
        data[key]["lines"] = {"total": 1, "covered": 1}
        measurement.write_json(path, data)
        scopes = measurement.validate_reports(self.root, directory, self.state["sources"])
        self.assertEqual(scopes["production"]["lines"], {"total": 2, "covered": 1, "percent": 50})

    def test_malformed_statement_start_position_is_refused(self):
        directory = self.output / "node-report"
        for start in (None, {}, {"line": True, "column": 0}, {"line": 0, "column": 0},
                      {"line": "1", "column": 0}, {"line": 1.5, "column": 0},
                      {"line": 1, "column": -1}):
            with self.subTest(start=start):
                reports(self.root, directory, self.state["sources"])
                path = directory / "coverage-final.json"
                data = json.loads(path.read_text())
                data[str(self.root / "bin/audit-harness.js")]["statementMap"]["0"]["start"] = start
                measurement.write_json(path, data)
                with self.assertRaisesRegex(ValueError, "start position"):
                    measurement.validate_reports(self.root, directory, self.state["sources"])

    def test_summary_markdown_has_separated_blocks_and_one_final_newline(self):
        for available, success in ((False, None), (True, True), (True, False)):
            with self.subTest(available=available, success=success):
                self.state["reasons"] = []
                self.state["behavioral_commands"] = [{"exit_code": 0 if success else 1}] if success is not None else []
                if available:
                    self.fake_provider()
                with patch.object(measurement.subprocess, "run", side_effect=self.converter):
                    measurement.finish(self.root, self.output, self.state)
                markdown = (self.output / "node-summary.md").read_text()
                self.assertNotIn("\n\n\n", markdown)
                self.assertTrue(markdown.endswith("\n"))
                self.assertFalse(markdown.endswith("\n\n"))
                self.assertIn("\n\nNo AST complexity/CRAP", markdown)
                if success is False:
                    self.assertIn("passing tests.\n\n- production:", markdown)

    def test_branch_lengths_must_match_locations(self):
        directory = self.output / "node-report"
        reports(self.root, directory, self.state["sources"])
        path = directory / "coverage-final.json"
        data = json.loads(path.read_text())
        record = data[str(self.root / "bin/audit-harness.js")]
        record["branchMap"] = {"0": {"locations": [{}, {}]}}
        record["b"] = {"0": [1]}
        measurement.write_json(path, data)
        with self.assertRaisesRegex(ValueError, "branch hits"):
            measurement.validate_reports(self.root, directory, self.state["sources"])

    def test_missing_node_provider_does_not_skip_or_duplicate_behavior(self):
        output = self.base / "runner-output"
        command = (sys.executable, "-c", "from pathlib import Path; "
                   "p=Path('calls'); p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
                   "raise SystemExit(7)")
        with patch.object(runner, "BEHAVIOR_COMMANDS", (command,)), patch.dict(os.environ, PATH=os.defpath):
            code = runner.collect(self.root, output, str(self.base / "missing-python"),
                                  str(self.base / "missing-radon"), self.base / "missing-node-provider")
        self.assertEqual(code, 1)
        self.assertEqual((self.root / "calls").read_text(), "x")
        report = json.loads((output / "node-summary.json").read_text())
        self.assertEqual(report["status"], "unavailable")
        self.assertFalse(report["behavioral_success"])

    @unittest.skipUnless(HAS_PROVIDER, "opt-in exact locked c8 provider required")
    def test_native_child_collection_includes_unexecuted_production_and_test_file(self):
        output = self.base / "native"
        output.mkdir()
        state = measurement.prepare(self.root, output, Path(PROVIDER))
        self.assertEqual(state["provider"]["status"], "available", state["provider"])
        env = dict(os.environ, NODE_V8_COVERAGE=state["raw_directory"])
        # shell -> Node test -> canonical Node dispatcher; unused module stays unloaded.
        result = subprocess.run(["bash", "-c", "node tests/cli/example.test.cjs"], cwd=self.root,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = measurement.finish(self.root, output, state)
        self.assertEqual(result["status"], "measured", result["reasons"])
        summary = json.loads((output / "node-report/coverage-summary.json").read_text())
        self.assertGreater(summary[str(self.root / "bin/audit-harness.js")]["lines"]["covered"], 0)
        self.assertEqual(summary[str(self.root / "scripts/crap_typescript.mjs")]["lines"]["covered"], 0)
        self.assertGreater(summary[str(self.root / "scripts/crap_typescript.mjs")]["lines"]["total"], 0)
        self.assertGreater(summary[str(self.root / "tests/cli/example.test.cjs")]["lines"]["covered"], 0)


if __name__ == "__main__":
    unittest.main()
