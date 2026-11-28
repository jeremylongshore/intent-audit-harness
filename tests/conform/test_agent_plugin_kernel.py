"""Published whole-object agent/plugin contracts without changing default floors."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("conform", ROOT / "scripts/conform.py")
CF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CF)
KINDS = ("agent", "plugin")


class AgentPluginKernel(unittest.TestCase):
    def corpus(self, kind):
        return ROOT / f"tests/fixtures/conform/kernel-{kind}"

    def test_all_eighty_source_fixtures_and_reference_outcomes(self):
        import jsonschema
        from referencing import Registry, Resource

        checker = jsonschema.FormatChecker()
        self.assertIn("uri", checker.checkers)
        self.assertFalse(checker.conforms("not-a-url", "uri"))

        for kind in KINDS:
            schema, registry, _, _, reason = CF.load_kernel(kind)
            self.assertIsNone(reason)
            reference = jsonschema.Draft202012Validator(
                schema,
                format_checker=checker,
                registry=Registry().with_resources(
                    (name, Resource.from_contents(doc)) for name, doc in registry.items()
                ),
            )
            provenance = json.loads((self.corpus(kind) / "provenance.json").read_text())
            self.assertEqual(len(provenance["files"]), 40)
            for rel, digest in provenance["files"].items():
                with self.subTest(kind=kind, fixture=rel):
                    raw = (self.corpus(kind) / rel).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                    data = json.loads(raw)
                    errors = CF.validate_instance(data, schema, _ctx={"root": schema, "registry": registry})
                    self.assertEqual(bool(errors), bool(list(reference.iter_errors(data))))
                    if rel.startswith("positive/"):
                        self.assertFalse(errors)
                    if rel.startswith("negative/"):
                        self.assertTrue(errors)

    def command(self, kind, data, tier, strict=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            if kind == "agent":
                path = root / "agents/example.md"
                content = "---\n" + json.dumps(data) + "\n---\nAgent fixture body.\n"
            else:
                path = root / ".claude-plugin/plugin.json"
                content = json.dumps(data)
            path.parent.mkdir()
            path.write_text(content)
            args = [sys.executable, str(ROOT / "scripts/conform.py"), str(root), "--tier", tier]
            if strict:
                args.append("--strict")
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            rows = json.loads(result.stdout)
            row = next(r for r in rows if r["gate_id"].endswith("conform-" + kind))
            self.assertEqual(row["input_hash"], "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
            return result.returncode, row

    def test_cli_whole_object_opt_in_default_and_exact_policy(self):
        pin = ROOT / "schemas/conform/kernel/intent-eval-core-0.11.0/pin.json"
        for kind in KINDS:
            with self.subTest(kind=kind):
                data = json.loads((self.corpus(kind) / "positive/canonical-01.json").read_text())
                code, valid = self.command(kind, data, "marketplace", True)
                self.assertEqual((code, valid["result"]), (0, "PASS"))
                self.assertEqual(valid["policy_hash"], "sha256:" + hashlib.sha256(pin.read_bytes()).hexdigest())
                self.assertEqual(valid["metadata"]["tier"], "marketplace")
                del data["version"]
                code, floor = self.command(kind, data, "floor", True)
                self.assertEqual((code, floor["result"]), (0, "PASS"))
                self.assertEqual(floor["metadata"]["tier"], "floor")
                code, advisory = self.command(kind, data, "marketplace")
                self.assertEqual((code, advisory["result"]), (0, "ADVISORY"))
                code, failure = self.command(kind, data, "marketplace", True)
                self.assertEqual((code, failure["result"]), (1, "FAIL"))
                self.assertTrue(any("version" in e for e in failure["metadata"]["errors"]))

    def test_each_new_family_refuses_changed_package_bytes(self):
        pin = json.loads((Path(CF.KERNEL_DIR) / "pin.json").read_text())
        for kind in KINDS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                kernel = Path(temp) / "kernel"
                shutil.copytree(CF.KERNEL_DIR, kernel)
                (kernel / pin["entries"][kind]).write_text("{}")
                self.assertIn("hash mismatch", CF.load_kernel(kind, str(kernel))[-1])


if __name__ == "__main__":
    unittest.main()
