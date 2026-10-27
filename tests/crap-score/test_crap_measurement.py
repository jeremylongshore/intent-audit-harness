"""Measurement honesty and read-only deep-audit regression controls."""
import hashlib
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_audit():
    spec = importlib.util.spec_from_file_location("audit_measurement_test", ROOT / "scripts/audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_scorer():
    spec = importlib.util.spec_from_file_location("crap_measurement_test", ROOT / "scripts/crap-score.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def snapshot(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode,
            os.readlink(p) if p.is_symlink() else
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "directory")
            for p in root.rglob("*")}


class MeasurementControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "subject"
        self.root.mkdir()
        (self.root / "package.json").write_text('{}')
        (self.root / "src").mkdir()
        (self.root / "src/main.ts").write_text('export function run(): number { return 1; }')

    def test_missing_tool_is_not_a_measured_pass(self):
        out = Path(self.tmp.name) / "output"
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/crap-score.py"),
                               "--root", str(self.root), "--out", str(out), "--json"],
                              env={**os.environ, "PATH": "/nonexistent"}, capture_output=True, text=True)
        row = json.loads(proc.stdout)
        self.assertEqual(row["result"], "ADVISORY")
        self.assertEqual(proc.returncode, 2)
        self.assertGreater(row["metadata"]["partitions"]["src"]["candidate_files"], 0)
        self.assertNotEqual(row["input_hash"], "sha256:" + hashlib.sha256(b"").hexdigest())

    def test_deep_audit_does_not_write_reports_into_subject(self):
        profile = Path(self.tmp.name) / "profile.json"
        profile.write_text(json.dumps({"subject": {"commit_sha": "abcdef0"}, "gates": [
            {"gate_id": "audit-harness:ci:crap-score", "dimension": "testing-depth",
             "enforcement": "advisory"}]}))
        before = snapshot(self.root)
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/audit.py"),
                               str(self.root), "--deep", "--profile", str(profile)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / "reports").exists())
        rows = json.loads(proc.stdout)
        row = next(r for r in rows if r["gate_id"].endswith(":crap-score"))
        self.assertEqual(row["result"], "ADVISORY")
        self.assertTrue(row["metadata"]["indeterminate"])

    def test_child_exit_zero_alone_cannot_authorize_pass(self):
        audit = load_audit()
        gate = {"gate_id": "audit-harness:ci:crap-score", "enforcement": "advisory"}
        for output in ['{"pass":true}', '{}', 'null', 'not JSON', '',
                       '{"result":"PASS","input_hash":"sha256:bad","metadata":{}}']:
            with self.subTest(output=output), patch.object(audit.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, output, '')
                row = audit.run_crap(str(self.root), gate, "abcdef0", "audit-harness@1.5.1", False)
                self.assertEqual(row["result"], "ADVISORY")
                self.assertTrue(row["metadata"]["indeterminate"])

    def score(self, mod, lang):
        output = io.StringIO()
        args = ["crap-score", "--root", str(self.root), "--lang", lang,
                "--out", str(Path(self.tmp.name) / "output"), "--json", "--read-only"]
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(output):
            code = mod.main()
        return code, json.loads(output.getvalue())

    def test_native_collector_positive_and_read_only_controls(self):
        # Tool output fixtures exercise the native adapters and joins, not a
        # mocked PASS verdict. No language toolchain or subject test is run.
        for lang, ext in [("python", "py"), ("go", "go"), ("js", "js"),
                          ("js", "ts"), ("rust", "rs")]:
            with self.subTest(lang=lang, extension=ext):
                for p in self.root.rglob("*"):
                    if p.is_file() and p.name != 'package.json':
                        p.unlink()
                (self.root / "tests").mkdir(exist_ok=True)
                source = f"src/main.{ext}"
                test = f"tests/main_test.{ext}" if lang == "go" else f"tests/main.test.{ext}"
                text = 'def f():\n    return 1\n' if lang == 'python' else 'owned fixture'
                (self.root / source).write_text(text)
                (self.root / test).write_text(text)
                mod = load_scorer()
                calls = []

                def native(cmd, cwd, calls=calls, source=source, test=test):
                    calls.append(cmd)
                    if cmd[0] == "radon":
                        path = cmd[-1]
                        return 0, json.dumps({path: [{"name": "f", "type": "function",
                                                     "lineno": 1, "complexity": 2}]}), ''
                    if cmd[0] == "gocyclo":
                        paths = [source] if '-ignore' in cmd else [source, test]
                        return 0, '\n'.join(f'2 pkg f {p}:1:1' for p in paths), ''
                    if cmd[0] == '/stub/cr':
                        path = cmd[-1]
                        return 0, json.dumps({"reports": [{"path": path,
                                                "functions": [{"name": "f", "cyclomatic": 2}]}]}), ''
                    if cmd[0] == '/stub/rust-code-analysis-cli':
                        path = cmd[-1]
                        return 0, json.dumps({"name": path, "kind": "unit", "spaces": [
                            {"name": "f", "kind": "function", "spaces": [],
                             "metrics": {"cyclomatic": {"sum": 2}}}]}), ''
                    self.fail(f"read-only scorer attempted unexpected command: {cmd}")

                before = snapshot(self.root)
                with patch.object(mod, 'which_or_none', side_effect=lambda name: '/stub/' + name), \
                        patch.object(mod, 'run', side_effect=native):
                    code, row = self.score(mod, lang)
                self.assertEqual(code, 0)
                self.assertEqual(row['result'], 'PASS')
                self.assertEqual(row['metadata']['production_methods_scored'], 1)
                self.assertEqual(row['metadata']['test_methods_scored'], 1)
                self.assertEqual(snapshot(self.root), before)
                self.assertTrue(calls)
                for rc, output in [(0, '{}'), (0, 'invalid'), (1, '')]:
                    with patch.object(mod, 'which_or_none', side_effect=lambda name: '/stub/' + name), \
                            patch.object(mod, 'run', return_value=(rc, output, '')):
                        code, row = self.score(mod, lang)
                    self.assertEqual(code, 2)
                    self.assertEqual(row['result'], 'ADVISORY')
                with patch.object(mod, 'which_or_none', return_value=None):
                    code, row = self.score(mod, lang)
                self.assertEqual(code, 2)
                self.assertEqual(row['result'], 'ADVISORY')
                self.assertEqual(snapshot(self.root), before)

    def test_zero_and_partial_and_empty_scope_are_not_passes(self):
        mod = load_scorer()
        for scores in [[], [mod.MethodScore('js', 'src/main.ts', 'run', 2, 0, 6, 'src')]]:
            with self.subTest(scores=len(scores)), patch.dict(
                    mod.DISPATCH, {'js': lambda *a, scores=scores, **k: scores}):
                code, row = self.score(mod, 'js')
                self.assertEqual(code, 2)
                self.assertEqual(row['result'], 'ADVISORY')
                self.assertEqual(row['metadata']['partitions']['test']['status'], 'empty')
        (self.root / 'src/main.ts').unlink()
        code, row = self.score(mod, 'js')
        self.assertEqual(code, 2)
        self.assertEqual(row['result'], 'ADVISORY')
        self.assertTrue(all(p['status'] == 'empty' for p in row['metadata']['partitions'].values()))

    def test_measured_threshold_violation_survives_partial_scope(self):
        mod = load_scorer()
        bad = mod.MethodScore('js', 'src/main.ts', 'run', 9, 0, 90, 'src')
        with patch.dict(mod.DISPATCH, {'js': lambda *a, **k: [bad]}):
            code, row = self.score(mod, 'js')
        self.assertEqual(code, 1)
        self.assertEqual(row['result'], 'FAIL')

    def test_partial_average_cannot_be_a_project_average_failure(self):
        mod = load_scorer()
        (self.root / 'src/extra.ts').write_text('export function extra() {}')
        measured = mod.MethodScore('js', 'src/main.ts', 'run', 3, 0, 12, 'src')
        with patch.dict(mod.DISPATCH, {'js': lambda *a, **k: [measured]}):
            code, row = self.score(mod, 'js')
        self.assertEqual(code, 2)
        self.assertEqual(row['result'], 'ADVISORY')
        self.assertFalse(row['metadata']['avg_fail'])
        self.assertIsNone(row['metadata']['production_avg_crap'])

    def test_colocated_javascript_tests_use_their_own_threshold(self):
        (self.root / 'src/main.ts').unlink()
        for name in ['main.js', 'main.test.js']:
            (self.root / 'src' / name).write_text('function f() {}')
        mod = load_scorer()
        for src_complexity, test_complexity, expected in [(1, 1, 'PASS'), (6, 1, 'FAIL'), (1, 4, 'FAIL')]:
            def native(cmd, cwd, src_complexity=src_complexity, test_complexity=test_complexity):
                target = cmd[-1]
                files = ['src/main.js', 'src/main.test.js'] if target == 'src' else [target]
                reports = [{'path': path, 'functions': [{'name': 'f', 'cyclomatic':
                            test_complexity if '.test.' in path else src_complexity}]} for path in files]
                return 0, json.dumps({'reports': reports}), ''

            with self.subTest(src=src_complexity, test=test_complexity), \
                    patch.object(mod, 'which_or_none', return_value='/stub/cr'), \
                    patch.object(mod, 'run', side_effect=native):
                code, row = self.score(mod, 'js')
            self.assertEqual(row['result'], expected)
            self.assertEqual(code, 0 if expected == 'PASS' else 1)

    def test_failed_or_malformed_collectors_are_not_passes(self):
        mod = load_scorer()
        for rc, out in [(1, '{}'), (0, 'invalid'), (0, 'null'), (0, '{}'),
                        (0, '{"reports":[]}'), (0, '{"reports":[{"functions":"bad"}]}')]:
            with self.subTest(rc=rc, output=out), \
                    patch.object(mod, 'which_or_none', return_value='/stub/cr'), \
                    patch.object(mod, 'run', return_value=(rc, out, '')):
                code, row = self.score(mod, 'js')
                self.assertEqual(code, 2)
                self.assertEqual(row['result'], 'ADVISORY')

    def test_audit_consumes_child_provenance_and_rejects_contradictions(self):
        audit = load_audit()
        gate = {'gate_id': 'audit-harness:ci:crap-score', 'enforcement': 'advisory'}
        child = {'gate_id': gate['gate_id'], 'result': 'PASS',
                 'input_hash': 'sha256:' + '1' * 64, 'policy_hash': 'sha256:' + '2' * 64,
                 'metadata': {'requested_partitions': ['src', 'test'],
                    'production_methods_scored': 1, 'test_methods_scored': 1,
                    'production_blockers_count': 0, 'test_blockers_count': 0, 'avg_fail': False,
                    'partitions': {k: {'candidate_files': 1, 'methods_scored': 1,
                                      'status': 'measured'} for k in ['src', 'test']}}}
        with patch.object(audit.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(child), '')
            row = audit.run_crap(str(self.root), gate, 'abcdef0', 'audit-harness@1.5.1', False)
            command = run.call_args.args[0]
            self.assertIn('--read-only', command)
            self.assertNotIn(self.root, Path(command[command.index('--out') + 1]).parents)
        self.assertEqual(row['result'], 'PASS')
        self.assertEqual(row['input_hash'], child['input_hash'])
        self.assertEqual(row['policy_hash'], child['policy_hash'])
        self.assertNotIn('summary_path', row['metadata'])
        for field, value in [('production_methods_scored', True),
                             ('production_blockers_count', 1), ('avg_fail', True),
                             ('requested_partitions', ['src']), ('partitions', {})]:
            wrong = json.loads(json.dumps(child))
            wrong['metadata'][field] = value
            with self.subTest(field=field), patch.object(audit.subprocess, 'run') as run:
                run.return_value = subprocess.CompletedProcess([], 0, json.dumps(wrong), '')
                row = audit.run_crap(str(self.root), gate, 'abcdef0', 'audit-harness@1.5.1', False)
                self.assertEqual(row['result'], 'ADVISORY')
        with patch.object(audit.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, json.dumps(child), '')
            row = audit.run_crap(str(self.root), gate, 'abcdef0', 'audit-harness@1.5.1', False)
            self.assertEqual(row['result'], 'ADVISORY')
        child['result'] = 'FAIL'
        child['metadata']['production_blockers_count'] = 1
        with patch.object(audit.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, json.dumps(child), '')
            row = audit.run_crap(str(self.root), gate, 'abcdef0', 'audit-harness@1.5.1', True)
        self.assertEqual(row['result'], 'FAIL')
        self.assertEqual(row['failure_mode'], 'testing-depth:crap-threshold')
        with patch.object(audit.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 120)):
            row = audit.run_crap(str(self.root), gate, 'abcdef0', 'audit-harness@1.5.1', False)
        self.assertEqual(row['result'], 'ADVISORY')

    def test_read_only_refuses_subject_output_and_never_invokes_coverage_generation(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/crap-score.py'),
                              '--root', str(self.root), '--read-only', '--json'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.root / 'reports').exists())

    def test_nested_installed_harness_does_not_write_python_bytecode(self):
        installed = self.root / '.installed/scripts'
        installed.mkdir(parents=True)
        for name in ['audit.py', 'crap-score.py', 'classify.py']:
            (installed / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
        profile = Path(self.tmp.name) / 'profile.json'
        profile.write_text(json.dumps({'subject': {'commit_sha': 'abcdef0'}, 'gates': [
            {'gate_id': 'audit-harness:ci:crap-score', 'dimension': 'testing-depth',
             'enforcement': 'advisory'}]}))
        before = snapshot(self.root)
        proc = subprocess.run([sys.executable, str(installed / 'audit.py'), str(self.root),
                              '--deep', '--profile', str(profile)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_python_class_methods_cannot_hide_behind_class_average(self):
        mod = load_scorer()
        (self.root / 'src/main.py').write_text('class Worker:\n    def risk(self):\n        return 1\n')
        method = {'type': 'method', 'name': 'risk', 'lineno': 2, 'complexity': 6}
        data = {'src/main.py': [{'type': 'class', 'name': 'Worker', 'lineno': 1,
                                'complexity': 1, 'methods': [method]}, method]}
        with patch.object(mod, 'which_or_none', return_value='/stub/radon'), \
                patch.object(mod, 'run', return_value=(0, json.dumps(data), '')):
            scores = mod.score_python(self.root, 'src', read_only=True)
        self.assertEqual(len(scores), 1, 'class aggregate and duplicate method are not independent functions')
        self.assertGreater(scores[0].crap, 30)
        data['src/main.py'] = [{'type': 'class', 'name': 'Worker', 'lineno': 1,
                               'complexity': 1, 'methods': []}]
        with patch.object(mod, 'which_or_none', return_value='/stub/radon'), \
                patch.object(mod, 'run', return_value=(0, json.dumps(data), '')):
            with self.assertRaisesRegex(mod.MeasurementError, 'inventory differs'):
                mod.score_python(self.root, 'src', read_only=True)

    def test_go_uncovered_function_cannot_receive_last_function_coverage(self):
        mod = load_scorer()
        (self.root / 'go.mod').write_text('module example.org/probe\n')
        (self.root / 'coverage.out').write_text('mode: atomic\n')

        def native(cmd, cwd):
            if cmd[0] == 'gocyclo':
                return 0, '6 pkg Risk src/main.go:1:1\n1 pkg Fine src/main.go:10:1\n', ''
            return 0, ('example.org/probe/src/main.go:1:\tRisk\t0.0%\n'
                       'example.org/probe/src/main.go:10:\tFine\t100.0%\n'), ''

        with patch.object(mod, 'which_or_none', return_value='/stub/go'), \
                patch.object(mod, 'run', side_effect=native):
            scores = mod.score_go(self.root, 'src', read_only=True)
        self.assertEqual(scores[0].coverage, 0)
        self.assertEqual(scores[1].coverage, 100)
        self.assertGreater(scores[0].crap, 30)

    def test_rust_container_aggregate_cannot_replace_nested_function(self):
        mod = load_scorer()
        (self.root / 'src/main.rs').write_text('impl Worker { fn risk() {} }')
        data = {'name': 'src/main.rs', 'kind': 'unit', 'spaces': [
            {'name': 'Worker', 'kind': 'impl', 'metrics': {'cyclomatic': {'sum': 1}},
             'spaces': [{'name': 'risk', 'kind': 'function', 'spaces': [],
                         'metrics': {'cyclomatic': {'sum': 6}}}]}]}
        with patch.object(mod, 'which_or_none', return_value='/stub/rust'), \
                patch.object(mod, 'run', return_value=(0, json.dumps(data), '')):
            scores = mod.score_rust(self.root, 'src', read_only=True)
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0].method, 'risk')
        self.assertGreater(scores[0].crap, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
