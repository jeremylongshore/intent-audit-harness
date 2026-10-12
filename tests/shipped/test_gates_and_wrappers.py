"""Behavioral coverage for shipped architecture/bias gates and both port CLIs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = '''import os, sys
mode = os.environ['CHECKER_MODE']
if mode == 'violation':
    print('error BROKEN violation Violation FAILED: seeded boundary violation')
elif mode == 'error':
    print('checker could not run', file=sys.stderr)
sys.exit(0 if mode == 'clean' else 1)
'''
INTERPRETER = '''import json, os, pathlib, sys
pathlib.Path(os.environ['DISPATCH_RECEIPT']).write_text(json.dumps(sys.argv))
print('dispatch stdout')
print('dispatch stderr', file=sys.stderr)
sys.exit(int(os.environ['DISPATCH_EXIT']))
'''


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!' + sys.executable + '\n' + body)
    path.chmod(0o755)


class GateBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shipped-gate-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        (self.repo / 'src').mkdir(parents=True)
        (self.repo / 'src/example.py').write_text('value = 42\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, ROOT=str(self.repo), PATH=str(self.bin) + os.pathsep + os.environ['PATH'])

    def arch(self, mode):
        return subprocess.run(['/bin/bash', str(ROOT / 'scripts/arch-check.sh'), '--json'], cwd=self.repo,
                              env=dict(self.env, CHECKER_MODE=mode), text=True, capture_output=True, timeout=20)

    def test_arch_clean_and_seeded_violation_for_each_dispatcher(self):
        configurations = [('.dependency-cruiser.cjs', 'npx', 'dependency-cruiser'),
                          ('.importlinter', 'lint-imports', 'import-linter'),
                          ('deptrac.yaml', 'vendor/bin/deptrac', 'deptrac'),
                          ('arch-go.yml', 'arch-go', 'arch-go'),
                          ('build.gradle', 'gradlew', 'archunit')]
        for config, tool, expected_tool in configurations:
            with self.subTest(tool=tool):
                path = self.repo / config
                path.write_text('com.tngtech.archunit' if tool == 'gradlew' else 'fixture policy\n')
                binary = self.repo / tool if '/' in tool or tool == 'gradlew' else self.bin / tool
                executable(binary, CHECKER)
                for mode, code, result, count in [('clean', 0, 'PASS', 0), ('violation', 1, 'FAIL', 1)]:
                    observed = self.arch(mode)
                    self.assertEqual(observed.returncode, code, observed.stderr)
                    row = json.loads(observed.stdout)
                    self.assertEqual(row['metadata']['tool'], expected_tool)
                    self.assertEqual(row['result'], result)
                    self.assertEqual(row['metadata']['violations'], count)
                    self.assertTrue(Path(row['metadata']['log']).is_file())
                path.unlink()

    def test_arch_failed_checker_without_pattern_still_emits_valid_json(self):
        (self.repo / '.dependency-cruiser.cjs').write_text('fixture policy\n')
        executable(self.bin / 'npx', CHECKER)
        observed = self.arch('error')
        self.assertEqual(observed.returncode, 1)
        row = json.loads(observed.stdout)
        self.assertEqual(row['result'], 'FAIL')
        self.assertEqual(row['metadata']['violations'], 0)

    def test_arch_unconfigured_repo_is_not_a_pass(self):
        observed = self.arch('clean')
        self.assertEqual(observed.returncode, 2)
        self.assertEqual(json.loads(observed.stdout)['metadata']['status'], 'not-configured')

    def test_bias_clean_seeded_and_empty_directories(self):
        self.assertIsNotNone(shutil.which('bc'), 'bias behavior tests require bc')
        cases = [('clean', 'def test_clean():\n    assert 2 + 2 == 4\n', 0, 'LOW', 'info'),
                 ('seeded', 'def test_seeded():\n    assert object() is not None\n', 1, 'CRITICAL', 'error'),
                 ('empty', '', 0, 'LOW', 'info')]
        for name, contents, count, grade, severity in cases:
            with self.subTest(case=name):
                target = self.root / name
                target.mkdir()
                (target / 'test_example.py').write_text(contents)
                result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/bias-count.sh'), str(target), '--json'],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                row = json.loads(result.stdout)
                self.assertEqual(row['result'], 'ADVISORY')
                self.assertEqual(row['metadata']['bias_total'], count)
                self.assertEqual(row['metadata']['grade'], grade)
                self.assertEqual(row['advisory_severity'], severity)
                self.assertIn('TEST BIAS SCAN', result.stderr)


class PortDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='harness-port-smoke-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        shutil.copytree(ROOT / 'python/src', cls.root / 'python')
        shutil.copytree(ROOT / 'rust', cls.root / 'rust')
        cargo = shutil.which('cargo')
        if cargo is None:
            raise RuntimeError('port smoke tests require the Rust cargo toolchain')
        subprocess.run([cargo, 'generate-lockfile', '--offline'], cwd=cls.root / 'rust', check=True,
                       capture_output=True, text=True, timeout=90)
        subprocess.run([cargo, 'build', '--locked', '--offline'], cwd=cls.root / 'rust', check=True,
                       capture_output=True, text=True, timeout=90)
        cls.rust = cls.root / 'rust/target/debug/audit-harness'

    def setUp(self):
        self.receipt = self.root / 'dispatch.json'
        self.bin = self.root / 'bin'
        for name in ('bash', 'python3'):
            executable(self.bin / name, INTERPRETER)
        self.env = dict(os.environ, PATH=str(self.bin), PYTHONPATH=str(self.root / 'python'),
                        XDG_CACHE_HOME=str(self.root / 'cache'), DISPATCH_RECEIPT=str(self.receipt))

    def test_default_arguments_literal_arguments_and_exit_codes(self):
        routes = [('verify', 'harness-hash.sh', ['--verify']), ('init', 'harness-hash.sh', ['--init']),
                  ('list', 'harness-hash.sh', ['--list']), ('escape-scan', 'escape-scan.sh', []),
                  ('arch', 'arch-check.sh', []), ('bias', 'bias-count.sh', []),
                  ('gherkin-lint', 'gherkin-lint.sh', []), ('crap', 'crap-score.py', [])]
        for name, command in [('python', [sys.executable, '-m', 'intent_audit_harness']), ('rust', [str(self.rust)])]:
            for subcommand, script, defaults in routes:
                for code in (0, 1, 2, 42):
                    with self.subTest(port=name, command=subcommand, code=code):
                        args = ['--json', 'path with spaces', 'literal;argument']
                        result = subprocess.run([*command, subcommand, *args], cwd=self.root,
                                                env=dict(self.env, DISPATCH_EXIT=str(code)),
                                                capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, code, result.stderr)
                        argv = json.loads(self.receipt.read_text())
                        self.assertEqual(Path(argv[0]).name, 'python3' if script.endswith('.py') else 'bash')
                        self.assertEqual(Path(argv[1]).name, script)
                        self.assertEqual(argv[2:], defaults + args)
                        self.assertEqual(result.stdout, 'dispatch stdout\n')
                        self.assertEqual(result.stderr, 'dispatch stderr\n')

    def test_unknown_commands_and_missing_interpreters_fail(self):
        for command in ([sys.executable, '-m', 'intent_audit_harness'], [str(self.rust)]):
            for subcommand in ('unknown-command', 'arch'):
                result = subprocess.run([*command, subcommand], cwd=self.root,
                                        env=dict(self.env, PATH=str(self.root / 'missing')),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_version_and_help_need_no_interpreter(self):
        expected = json.loads((ROOT / 'package.json').read_text())['version']
        for command in ([sys.executable, '-m', 'intent_audit_harness'], [str(self.rust)]):
            for flag in ('--version', '--help'):
                result = subprocess.run([*command, flag], cwd=self.root,
                                        env=dict(self.env, PATH=str(self.root / 'missing')),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected if flag == '--version' else 'Usage:', result.stdout)


if __name__ == '__main__':
    unittest.main()
