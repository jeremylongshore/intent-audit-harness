"""Published catalog corpus, CLI admission and supported-schema boundary."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("conform", ROOT / "scripts/conform.py")
CF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CF)
CORPUS = ROOT / "tests/fixtures/conform/kernel-catalog"


class CatalogKernel(unittest.TestCase):
    def test_published_corpus_and_reference_parity(self):
        import jsonschema
        from referencing import Registry, Resource

        schema, registry, _, _, reason = CF.load_kernel("marketplace")
        self.assertIsNone(reason)
        reference = jsonschema.Draft202012Validator(
            schema,
            registry=Registry().with_resources((name, Resource.from_contents(doc)) for name, doc in registry.items()),
        )
        provenance = json.loads((CORPUS / "provenance.json").read_text())
        self.assertEqual(len(provenance["files"]), 40)
        for rel, digest in provenance["files"].items():
            with self.subTest(fixture=rel):
                raw = (CORPUS / rel).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                data = json.loads(raw)
                errors = CF.validate_instance(data, schema, _ctx={"root": schema, "registry": registry})
                self.assertEqual(bool(errors), bool(list(reference.iter_errors(data))))
                if rel.startswith("positive/"):
                    self.assertFalse(errors)
                if rel.startswith("negative/"):
                    self.assertTrue(errors)

    def test_unknown_reachable_assertions_are_refused(self):
        for keyword, value in [
            ("minimum", 0),
            ("propertyNames", {}),
            ("if", {}),
            ("uniqueItems", True),
            ("unevaluatedProperties", False),
        ]:
            with self.subTest(keyword=keyword):
                schema = {"properties": {"value": {keyword: value}}}
                self.assertIn(keyword, CF.kernel_schema_admission(schema, {}))

    def test_reference_admission_and_cycles(self):
        uri = "https://example.invalid/schema"
        self.assertIn("unresolvable", CF.kernel_schema_admission({"$ref": uri}, {}))
        self.assertIn("recursive", CF.kernel_schema_admission({"$ref": "#"}, {}))
        self.assertIn("minimum", CF.kernel_schema_admission({"$ref": uri}, {uri: {"minimum": 0}}))
        self.assertIn("format", CF.kernel_schema_admission({"format": "email"}, {}))
        self.assertIn("non-object", CF.kernel_schema_admission(False, {}))
        self.assertIsNone(CF.kernel_schema_admission({"properties": {"minimum": {"type": "string"}}}, {}))

    def test_only_documented_zod_annotation_is_nonasserting(self):
        self.assertIsNone(
            CF.kernel_schema_admission(
                {
                    "x-mutually-exclusive-fields": [{"fields": ["requires_env", "fallback_for_env"]}],
                },
                {},
            )
        )
        self.assertIn("x-other-assertion", CF.kernel_schema_admission({"x-other-assertion": True}, {}))

    def test_valid_pin_with_unsupported_assertion_is_unmeasured_not_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            kernel = Path(temp) / "kernel"
            shutil.copytree(CF.KERNEL_DIR, kernel)
            rel = "authoring/v1/upstream-base/marketplace-catalog.v1.json"
            schema = json.loads((kernel / rel).read_text())
            schema["properties"]["plugins"]["uniqueItems"] = True
            (kernel / rel).write_text(json.dumps(schema))
            pin = json.loads((kernel / "pin.json").read_text())
            pin["files"][rel] = "sha256:" + hashlib.sha256((kernel / rel).read_bytes()).hexdigest()
            (kernel / "pin.json").write_text(json.dumps(pin))
            with patch.object(CF, "KERNEL_DIR", str(kernel)):
                rows = CF.run_bundled(
                    "marketplace",
                    {
                        "gate_id": "audit-harness:local:conform-marketplace",
                        "enforcement": "blocking",
                    },
                    [str(CORPUS / "positive/canonical-01.json")],
                    "fixture",
                    "fixture",
                    str(CORPUS),
                    True,
                    "marketplace",
                )
            self.assertEqual(rows[0]["result"], "ADVISORY")
            self.assertTrue(rows[0]["metadata"]["indeterminate"])
            self.assertIn("uniqueItems", rows[0]["metadata"]["reason"])
            # Bytes changing without the pin update are rejected independently.
            (kernel / rel).write_text("{}")
            self.assertIn("hash mismatch", CF.load_kernel("marketplace", str(kernel))[-1])

    def command(self, data, tier, strict=False):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "marketplace.json").write_text(json.dumps(data))
            args = [sys.executable, str(ROOT / "scripts/conform.py"), str(repo), "--tier", tier]
            if strict:
                args.append("--strict")
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            rows = json.loads(result.stdout)
            row = next(r for r in rows if r["gate_id"].endswith("conform-marketplace"))
            return result.returncode, row

    def test_cli_opt_in_default_preservation_and_policy_binding(self):
        data = json.loads((CORPUS / "positive/canonical-01.json").read_text())
        code, floor = self.command(data, "floor", True)
        self.assertEqual(code, 0)
        self.assertEqual(floor["result"], "ADVISORY")
        self.assertTrue(floor["metadata"]["indeterminate"])
        code, good = self.command(data, "marketplace", True)
        self.assertEqual((code, good["result"]), (0, "PASS"))
        pin = ROOT / "schemas/conform/kernel/intent-eval-core-0.11.0/pin.json"
        self.assertEqual(good["policy_hash"], "sha256:" + hashlib.sha256(pin.read_bytes()).hexdigest())
        self.assertEqual(good["metadata"]["kernel"], "@intentsolutions/core@0.11.0")
        malformed = copy.deepcopy(data)
        del malformed["owner"]["name"]
        code, advisory = self.command(malformed, "marketplace")
        self.assertEqual((code, advisory["result"]), (0, "ADVISORY"))
        code, failure = self.command(malformed, "marketplace", True)
        self.assertEqual((code, failure["result"]), (1, "FAIL"))
        self.assertTrue(any("owner" in error for error in failure["metadata"]["errors"]))


if __name__ == "__main__":
    unittest.main()
