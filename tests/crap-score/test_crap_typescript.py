#!/usr/bin/env python3
"""Hermetic provider-contract tests; opt-in real compiler tests never download it."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("crap_strict", ROOT / "scripts/crap_strict.py")
STRICT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRICT)
FIXTURES = Path(__file__).parent / "fixtures/typescript"


def coverage_record(path):
    return {
        "path": path,
        "statementMap": {"0": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 1}}},
        "s": {"0": 1},
        "fnMap": {},
        "f": {},
        "branchMap": {},
        "b": {},
    }


class TypeScriptContract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "code.ts"
        self.source.write_text("export const value = () => 1;\n")
        self.parser = self.root / "node_modules/typescript/lib/typescript.js"
        self.parser.parent.mkdir(parents=True)
        self.parser.write_text("hermetic parser identity\n")
        self.function = {"id": "21:28", "start": 21, "end": 28, "line": 1, "name": "value", "kind": "ArrowFunction"}
        self.record = {
            "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "type_only": False,
            "inventory": [self.function],
            "methods": [{"id": "21:28", "complexity": 1}],
        }
        self.provider = {
            "schema_version": "crap-typescript/v1",
            "files": {"code.ts": self.record},
            "provider": {
                "name": "typescript",
                "version": "fixture-1",
                "path": str(self.parser),
                "sha256": hashlib.sha256(self.parser.read_bytes()).hexdigest(),
            },
            "complexity_definition": "typescript-function-decisions/v1",
        }
        self.node = self.root / "node"
        self.node.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nprint(Path('provider.json').read_text())\n"
        )
        self.node.chmod(0o755)
        self.coverage = {"code.ts": coverage_record("code.ts")}
        self.save()

    def save(self):
        (self.root / "provider.json").write_text(json.dumps(self.provider))
        (self.root / "coverage.json").write_text(json.dumps(self.coverage))

    def measure(self, language="typescript", requested=None):
        self.save()
        with patch.object(STRICT.shutil, "which", return_value=str(self.node)):
            return STRICT.measure(self.root, requested or {"src": ["code.ts"]}, self.root / "coverage.json", language)

    def incomplete(self, phrase):
        report = self.measure()
        self.assertFalse(report["complete"], report)
        self.assertIn(phrase, " ".join(report["reasons"]))
        return report

    def test_complete_statement_proxy_and_identities(self):
        report = self.measure()
        self.assertTrue(report["complete"], report["reasons"])
        self.assertEqual(report["coverage_basis"], STRICT.TS_PROXY)
        self.assertEqual(report["scopes"]["src"]["scored_functions"], 1)
        for key in ("parser_sha256", "helper_sha256", "coverage_sha256", "provider_executable_sha256"):
            self.assertEqual(len(report["inputs"][key]), 64)
        self.assertEqual(report["inputs"]["parser_version"], "fixture-1")

    def test_auto_language(self):
        self.assertTrue(self.measure(language="auto")["complete"])

    def test_missing_parser(self):
        self.parser.unlink()
        self.incomplete("No such file")

    def test_missing_node(self):
        with patch.object(STRICT.shutil, "which", return_value=None):
            result = STRICT.measure(self.root, {"src": ["code.ts"]}, self.root / "coverage.json", "typescript")
        self.assertFalse(result["complete"])
        self.assertIn("missing Node", " ".join(result["reasons"]))

    def test_failed_provider(self):
        self.node.write_text(f"#!{sys.executable}\nraise SystemExit(3)\n")
        self.incomplete("provider failed")

    def test_malformed_provider(self):
        self.node.write_text(f"#!{sys.executable}\nprint('broken')\n")
        self.incomplete("Expecting value")

    def test_provider_file_omission(self):
        self.provider["files"] = {}
        self.incomplete("file inventory mismatch")

    def test_provider_function_omission(self):
        self.record["methods"] = []
        report = self.incomplete("function inventory mismatch")
        self.assertEqual(report["scopes"]["src"]["discovered_functions"], 1)
        self.assertEqual(report["scopes"]["src"]["scored_functions"], 0)

    def test_provider_function_duplicate(self):
        self.record["methods"] *= 2
        self.incomplete("duplicate TypeScript complexity")

    def test_provider_wrong_identity(self):
        self.provider["provider"]["sha256"] = "0" * 64
        self.incomplete("identity mismatch")

    def test_provider_malformed_function(self):
        for field, value in (("end", 1000), ("start", True), ("line", 0), ("kind", "madeup")):
            with self.subTest(field=field):
                original = self.function[field]
                self.function[field] = value
                self.incomplete("invalid or duplicate TypeScript function")
                self.function[field] = original

    def test_provider_malformed_complexity(self):
        for value in (0, True, "1", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.record["methods"][0]["complexity"] = value
                self.incomplete("TypeScript complexity")

    def test_coverage_missing_file(self):
        self.coverage = {}
        self.incomplete("coverage missing")

    def test_coverage_wrong_path(self):
        self.coverage["code.ts"]["path"] = "missing.ts"
        self.incomplete("file path")

    def test_coverage_duplicate_normalized_file(self):
        self.coverage[str(self.source)] = self.coverage["code.ts"]
        self.incomplete("duplicate normalized")

    def test_coverage_outside_root(self):
        self.coverage["../outside.ts"] = self.coverage["code.ts"]
        self.incomplete("outside root")

    def test_coverage_invalid_counts(self):
        for value in (True, -1, "1", float("nan"), float("inf"), 1.5, 2**53):
            with self.subTest(value=value):
                self.coverage["code.ts"]["s"]["0"] = value
                self.incomplete("statement count")

    def test_coverage_missing_counter(self):
        self.coverage["code.ts"]["s"] = {}
        self.incomplete("statement/count inventory mismatch")

    def test_coverage_invalid_location(self):
        self.coverage["code.ts"]["statementMap"]["0"]["end"]["column"] = 999
        self.incomplete("invalid Istanbul location")

    def test_coverage_malformed_unused_counters(self):
        self.coverage["code.ts"]["f"] = {"invented": 1}
        self.incomplete("counter inventory mismatch")

    def implicit_else(self):
        location = {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 28}}
        self.coverage["code.ts"]["branchMap"] = {
            "0": {"type": "if", "loc": location, "locations": [copy.deepcopy(location), {"start": {}, "end": {}}]}
        }
        self.coverage["code.ts"]["b"] = {"0": [1, 0]}

    def test_implicit_else_no_source_location(self):
        self.implicit_else()
        report = self.measure()
        self.assertTrue(report["complete"], report["reasons"])
        self.assertEqual(report["methods"][0]["coverage"], 100)
        self.assertEqual(self.coverage["code.ts"]["branchMap"]["0"]["locations"][1], {"start": {}, "end": {}})
        self.coverage["code.ts"]["b"]["0"] = [0, 2]
        self.assertTrue(self.measure()["complete"])

    def test_implicit_else_rejects_near_miss_shapes(self):
        def replace_type(entry):
            entry["type"] = "cond-expr"

        def reverse(entry):
            entry["locations"].reverse()

        def third(entry):
            entry["locations"].append(copy.deepcopy(entry["locations"][0]))

        def absent_parent(entry):
            del entry["loc"]

        def empty_parent(entry):
            entry["loc"] = {"start": {}, "end": {}}

        def invalid_parent(entry):
            entry["loc"]["end"]["column"] = 999

        def empty_first(entry):
            entry["locations"][0] = {"start": {}, "end": {}}

        def invalid_first(entry):
            entry["locations"][0]["start"]["column"] = -1

        mutations = [
            replace_type,
            reverse,
            third,
            absent_parent,
            empty_parent,
            invalid_parent,
            empty_first,
            invalid_first,
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate.__name__):
                self.implicit_else()
                mutate(self.coverage["code.ts"]["branchMap"]["0"])
                report = self.measure()
                self.assertFalse(report["complete"])
        for sentinel in (
            {},
            {"start": {}},
            {"start": None, "end": None},
            {"start": {}, "end": {}, "extra": True},
            {"start": {"line": 1, "column": float("nan")}, "end": {}},
            {"start": {}, "end": {"line": 1, "column": float("inf")}},
        ):
            with self.subTest(sentinel=sentinel):
                self.implicit_else()
                self.coverage["code.ts"]["branchMap"]["0"]["locations"][1] = sentinel
                self.assertFalse(self.measure()["complete"])

    def test_implicit_else_still_requires_valid_counters(self):
        for values in ([1, -1], [1, True], [1, float("inf")], [1, None], [1], [1, 0, 0]):
            with self.subTest(values=values):
                self.implicit_else()
                self.coverage["code.ts"]["b"]["0"] = values
                self.assertFalse(self.measure()["complete"])

    def test_empty_locations_remain_invalid_for_functions_and_statements(self):
        empty = {"start": {}, "end": {}}
        self.coverage["code.ts"]["statementMap"]["0"] = empty
        self.incomplete("invalid Istanbul location")
        self.coverage["code.ts"] = coverage_record("code.ts")
        self.coverage["code.ts"]["fnMap"] = {"0": {"loc": empty}}
        self.coverage["code.ts"]["f"] = {"0": 1}
        self.incomplete("invalid Istanbul location")

    def test_zero_function_runtime_requires_coverage(self):
        self.record.update(inventory=[], methods=[])
        self.coverage = {}
        self.incomplete("coverage missing")

    def test_type_only_file_explicit_but_not_empty_pass(self):
        self.record.update(type_only=True, inventory=[], methods=[])
        self.coverage = {}
        report = self.incomplete("no functions scored")
        self.assertEqual(report["scopes"]["src"]["type_only_files"], 1)
        self.assertEqual(report["scopes"]["src"]["scored_files"], 0)

    def test_type_only_contradiction(self):
        self.record["type_only"] = True
        self.incomplete("function inventory mismatch")

    def test_empty_runtime_statements(self):
        self.coverage["code.ts"].update(statementMap={}, s={})
        self.incomplete("empty Istanbul statements")

    def test_source_changed_by_provider(self):
        self.node.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\n"
            "print(Path('provider.json').read_text())\nPath('code.ts').write_text('changed')\n"
        )
        self.incomplete("changed during measurement")

    def test_coverage_changed_by_provider(self):
        self.node.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\n"
            "print(Path('provider.json').read_text())\nPath('coverage.json').write_text('{}')\n"
        )
        self.incomplete("coverage changed during measurement")

    def test_statement_proxy_changes_score_and_coverage_identity(self):
        covered = self.measure()
        self.coverage["code.ts"]["s"]["0"] = 0
        uncovered = self.measure()
        self.assertTrue(uncovered["complete"])
        self.assertEqual(uncovered["methods"][0]["coverage"], 0)
        self.assertEqual(uncovered["methods"][0]["crap"], 2)
        self.assertNotEqual(covered["inputs"]["coverage_sha256"], uncovered["inputs"]["coverage_sha256"])

    def test_parser_changed_by_provider(self):
        self.node.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\n"
            "print(Path('provider.json').read_text())\n"
            "Path('node_modules/typescript/lib/typescript.js').write_text('changed')\n"
        )
        self.incomplete("parser changed during measurement")

    def test_mixed_language_inventory(self):
        (self.root / "other.py").write_text("def other(): pass\n")
        report = self.measure(language="auto", requested={"src": ["code.ts", "other.py"]})
        self.assertFalse(report["complete"])
        self.assertIn("mixed or unsupported", " ".join(report["reasons"]))

    def test_workspace_glob_ignores_unrelated_dependency_symlinks(self):
        directory = self.root / "packages/a/src"
        directory.mkdir(parents=True)
        shutil.copyfile(self.source, directory / "code.ts")
        (self.root / "packages/a/node_modules").symlink_to(self.root / "node_modules", target_is_directory=True)
        self.provider["files"] = {"packages/a/src/code.ts": self.record}
        self.coverage = {"packages/a/src/code.ts": coverage_record("packages/a/src/code.ts")}
        report = self.measure(requested={"src": ["packages/*/src/**/*.ts"]})
        self.assertTrue(report["complete"], report["reasons"])

    def test_cli_gate_result(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/crap-score.py"),
                "--strict-measurement",
                "--root",
                str(self.root),
                "--lang",
                "typescript",
                "--target",
                "src",
                "--source-glob",
                "code.ts",
                "--coverage-json",
                "coverage.json",
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": str(self.root) + os.pathsep + os.environ["PATH"]},
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["result"], "PASS")


@unittest.skipUnless(
    os.environ.get("AUDIT_HARNESS_TYPESCRIPT_ROOT"), "optional caller-installed TypeScript unavailable"
)
class RealTypeScript(unittest.TestCase):
    def test_real_ast_inventory_complexity_and_missing_runtime_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FIXTURES, root / "src")
            (root / "node_modules").mkdir()
            (root / "node_modules/typescript").symlink_to(
                Path(os.environ["AUDIT_HARNESS_TYPESCRIPT_ROOT"]) / "node_modules/typescript", target_is_directory=True
            )
            coverage = {
                f"src/{name}": coverage_record(f"src/{name}") for name in ("functions.ts", "decisions.ts", "runtime.ts")
            }
            (root / "coverage.json").write_text(json.dumps(coverage))
            report = STRICT.measure(root, {"src": ["src/*.ts"]}, root / "coverage.json", "typescript")
            self.assertTrue(report["complete"], report["reasons"])
            functions = [m for m in report["methods"] if m["path"] == "src/functions.ts"]
            self.assertEqual([m["complexity"] for m in functions], [2, 3, 2, 1, 2, 1, 1, 2, 1, 2])
            decisions = [m for m in report["methods"] if m["path"] == "src/decisions.ts"]
            self.assertEqual([m["complexity"] for m in decisions], [18, 2, 2, 1])
            self.assertEqual(report["scopes"]["src"]["type_only_files"], 1)
            self.assertEqual(report["scopes"]["src"]["discovered_files"], 4)
            self.assertEqual(report["scopes"]["src"]["scored_files"], 3)
            del coverage["src/runtime.ts"]
            (root / "coverage.json").write_text(json.dumps(coverage))
            report = STRICT.measure(root, {"src": ["src/*.ts"]}, root / "coverage.json", "typescript")
            self.assertFalse(report["complete"])
            self.assertIn("coverage missing", " ".join(report["reasons"]))

    def test_ambient_declarations_with_initializers_are_erased(self):
        samples = [
            "declare const x = sideEffect();",
            "declare namespace N { const x = sideEffect(); }",
            "declare class C { x = sideEffect(); static { sideEffect(); } }",
            "declare enum E { X = sideEffect() }",
            'declare module "x" { export const x = sideEffect(); }',
            "export declare const x: number;",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "node_modules").mkdir()
            (root / "node_modules/typescript").symlink_to(
                Path(os.environ["AUDIT_HARNESS_TYPESCRIPT_ROOT"]) / "node_modules/typescript", target_is_directory=True
            )
            files = []
            for index, sample in enumerate(samples):
                path = f"ambient{index}.ts"
                (root / path).write_text(sample)
                files.append({"path": path, "sha256": hashlib.sha256(sample.encode()).hexdigest()})
            result = subprocess.run(
                ["node", str(ROOT / "scripts/crap_typescript.mjs")],
                input=json.dumps({"root": str(root), "files": files}),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all(entry["type_only"] for entry in json.loads(result.stdout)["files"].values()))
            emitted = subprocess.run(
                [
                    "node",
                    "-e",
                    """
const ts = require(process.cwd() + '/node_modules/typescript');
const fs = require('fs');
const samples = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify(samples.map(source => ts.transpileModule(source, {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}
}).outputText.trim())));
""",
                ],
                cwd=root,
                input=json.dumps(samples),
                capture_output=True,
                text=True,
            )
            self.assertEqual(emitted.returncode, 0, emitted.stderr)
            self.assertTrue(all(text in ('"use strict";', "export {};", "") for text in json.loads(emitted.stdout)))

    def test_real_parser_rejects_invalid_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "node_modules").mkdir()
            (root / "node_modules/typescript").symlink_to(
                Path(os.environ["AUDIT_HARNESS_TYPESCRIPT_ROOT"]) / "node_modules/typescript", target_is_directory=True
            )
            source = root / "broken.ts"
            source.write_text("export function broken( { !\n")
            request = {
                "root": str(root),
                "files": [{"path": "broken.ts", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
            }
            result = subprocess.run(
                ["node", str(ROOT / "scripts/crap_typescript.mjs")],
                input=json.dumps(request),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("parse diagnostics", result.stderr)


if __name__ == "__main__":
    unittest.main()
