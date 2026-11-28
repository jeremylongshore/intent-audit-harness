"""Published MCP/hook corpus parity and original-artifact CLI verdicts."""

import copy
import hashlib
import importlib.util
import json
import subprocess
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


class ProjectedKernel(unittest.TestCase):
    def fixture(self, kind):
        path = ROOT / f"tests/fixtures/conform/kernel-{kind}/positive/canonical-01.json"
        return json.loads(path.read_text())

    def test_repeated_references_use_one_bound_snapshot(self):
        server = self.fixture("mcp")
        manifest = {"mcpServers": ["./extra.json", "./extra.json"]}
        first = {server["name"]: server}
        changed = {server["name"]: {**server, "enabled": False}}
        reads = []

        def changing_reader(_root, path):
            reads.append(path)
            if path == "plugin.json":
                return manifest, "sha256:manifest"
            return (first, "sha256:first") if reads.count(path) == 1 else (changed, "sha256:changed")

        bindings = {}
        with patch.object(CF, "read_json_snapshot", side_effect=changing_reader):
            targets = CF.projected_targets("mcp", ROOT, "plugin.json", "manifest", bindings)
        self.assertEqual(reads, ["plugin.json", "extra.json"])
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0], targets[1])
        self.assertEqual(bindings, {"plugin.json": "sha256:manifest", "extra.json": "sha256:first"})

    def test_package_manifest_reference_is_relative_to_plugin_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "packages/example"
            (package / ".claude-plugin").mkdir(parents=True)
            (package / "package.json").write_text('{}')
            manifest = package / ".claude-plugin/plugin.json"
            manifest.write_text(json.dumps({"mcpServers": "./extra.json"}))
            referenced = package / "extra.json"
            referenced.write_text(json.dumps(self.envelope("mcp", self.fixture("mcp"))))
            # A root-level namesake must not replace the package's declaration.
            (root / "extra.json").write_text('{"mcpServers":{}}')
            rows = [row for row in self.run_repo(root) if row["gate_id"].endswith("conform-mcp")]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["result"], "PASS")
            self.assertEqual(set(rows[0]["metadata"]["input_bindings"]), {
                "packages/example/.claude-plugin/plugin.json", "packages/example/extra.json",
            })

    def test_ambiguous_frontmatter_fails_and_aliases_remain_unmeasured(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "SKILL.md"
            for content, expected in (
                ("hooks: invalid\nhooks: {}", "FAIL"),
                ("a: &a [*a]\nhooks: {}", "ADVISORY"),
            ):
                raw = ("---\n" + content + "\n---\n").encode()
                path.write_bytes(raw)
                with self.subTest(content=content):
                    rows = [row for row in self.run_repo(root) if row["gate_id"].endswith("conform-hook")]
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["result"], expected)
                    self.assertEqual(rows[0]["input_hash"], "sha256:" + hashlib.sha256(raw).hexdigest())
                    if expected == "ADVISORY":
                        self.assertTrue(rows[0]["metadata"]["indeterminate"])

    def test_eighty_original_fixtures_match_reference_and_labels(self):
        import jsonschema
        from referencing import Registry, Resource
        for kind in ("mcp", "hook"):
            schema, registry, _, _, reason = CF.load_kernel(kind)
            self.assertIsNone(reason)
            reference = jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker(),
                registry=Registry().with_resources(
                    (name, Resource.from_contents(doc)) for name, doc in registry.items()))
            corpus = ROOT / f"tests/fixtures/conform/kernel-{kind}"
            provenance = json.loads((corpus / "provenance.json").read_text())
            self.assertEqual(len(provenance["files"]), 40)
            for rel, digest in provenance["files"].items():
                with self.subTest(kind=kind, fixture=rel):
                    raw = (corpus / rel).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                    data = json.loads(raw)
                    errors = CF.validate_instance(data, schema, _ctx={"root": schema, "registry": registry})
                    self.assertEqual(bool(errors), bool(list(reference.iter_errors(data))))
                    if rel.startswith("positive/"):
                        self.assertFalse(errors)
                    if rel.startswith("negative/"):
                        self.assertTrue(errors)

    def envelope(self, kind, data):
        data = copy.deepcopy(data)
        if kind == "mcp":
            name = data.pop("name")
            return {"mcpServers": {name: data}}
        event, matcher = data.pop("event"), data.pop("matcher")
        return {"hooks": {event: [{"matcher": matcher, "hooks": [data]}]}}

    def command(self, kind, data):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / (".mcp.json" if kind == "mcp" else "hooks/hooks.json")
            path.parent.mkdir(exist_ok=True)
            raw = json.dumps(data).encode()
            path.write_bytes(raw)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/conform.py"), str(root),
                                     "--tier", "marketplace", "--strict"], capture_output=True, text=True)
            row = next(row for row in json.loads(result.stdout) if row["gate_id"].endswith("conform-" + kind))
            self.assertEqual(row["input_hash"], "sha256:" + hashlib.sha256(raw).hexdigest())
            return result.returncode, row

    def test_valid_envelopes_pass_but_missing_authoring_fields_are_not_defaulted(self):
        for kind in ("mcp", "hook"):
            data = self.fixture(kind)
            code, row = self.command(kind, self.envelope(kind, data))
            self.assertEqual((code, row["result"]), (0, "PASS"))
            self.assertEqual(len(row["metadata"]["target_pointers"]), 1)
            del data["enabled"]
            code, row = self.command(kind, self.envelope(kind, data))
            self.assertEqual((code, row["result"]), (1, "FAIL"))
            self.assertTrue(any("enabled" in error for error in row["metadata"]["errors"]))

    def test_hook_minimum_zero_and_integer_type_have_actual_cli_effect(self):
        for timeout, expected in ((0, "PASS"), (-1, "FAIL"), (True, "FAIL"), (0.5, "FAIL")):
            with self.subTest(timeout=timeout):
                data = self.fixture("hook")
                data["timeout"] = timeout
                _, row = self.command("hook", self.envelope("hook", data))
                self.assertEqual(row["result"], expected)

    def test_empty_envelopes_are_not_schema_passes(self):
        for kind, data in (("mcp", {"mcpServers": {}}), ("hook", {"hooks": {}})):
            code, row = self.command(kind, data)
            self.assertEqual((code, row["result"]), (0, "NOT_APPLICABLE"))
            self.assertEqual(row["metadata"]["target_pointers"], [])

    def run_repo(self, root, tier="marketplace"):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/conform.py"), str(root),
                                 "--tier", tier, "--strict"], capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return json.loads(result.stdout)

    def test_embedded_settings_and_frontmatter_are_opt_in_with_original_byte_binding(self):
        data = self.envelope("hook", self.fixture("hook"))
        for relative in (".claude/settings.json", ".claude/settings.local.json", "skills/example/SKILL.md",
                         "agents/example.md"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path = root / relative
                path.parent.mkdir(parents=True)
                raw = json.dumps(data)
                if path.suffix == ".md":
                    raw = "---\n" + raw + "\n---\nFixture only.\n"
                path.write_text(raw)
                rows = self.run_repo(root)
                hook = next(row for row in rows if row["gate_id"].endswith("conform-hook"))
                self.assertEqual(hook["result"], "PASS")
                self.assertEqual(hook["input_hash"], "sha256:" + hashlib.sha256(raw.encode()).hexdigest())
                self.assertFalse(any(row["gate_id"].endswith("conform-hook") for row in self.run_repo(root, "floor")))

    def test_manifest_inline_and_local_reference_bind_both_inputs_and_preserve_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".claude-plugin").mkdir()
            inline = self.envelope("hook", self.fixture("hook"))["hooks"]
            manifest = root / ".claude-plugin/plugin.json"
            manifest.write_text(json.dumps({"name": "fixture", "hooks": [inline, "./extra.json"]}))
            reference = root / "extra.json"
            reference.write_text(json.dumps({"hooks": inline}))
            first = next(row for row in self.run_repo(root) if row["gate_id"].endswith("conform-hook"))
            self.assertEqual(first["result"], "PASS")
            self.assertEqual(set(first["metadata"]["input_bindings"]), {".claude-plugin/plugin.json", "extra.json"})
            self.assertTrue(any(path.startswith("/hooks/0/") for path in first["metadata"]["target_pointers"]))
            self.assertTrue(any(path.startswith("extra.json#/") for path in first["metadata"]["target_pointers"]))
            bad = self.fixture("hook")
            bad["timeout"] = -1
            reference.write_text(json.dumps(self.envelope("hook", bad)))
            second = next(row for row in self.run_repo(root) if row["gate_id"].endswith("conform-hook"))
            self.assertEqual(second["result"], "FAIL")
            self.assertNotEqual(first["input_hash"], second["input_hash"])
            self.assertTrue(any("extra.json#" in error for error in second["metadata"]["errors"]))

    def test_inline_mcp_missing_fields_and_unsupported_references_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "plugin.json"
            data = self.fixture("mcp")
            name = data.pop("name")
            path.write_text(json.dumps({"name": "fixture", "mcpServers": {name: data}}))
            row = next(row for row in self.run_repo(root) if row["gate_id"].endswith("conform-mcp"))
            self.assertEqual(row["result"], "PASS")
            for reference in ("https://example.invalid/bundle.mcpb", "./server.mcpb", "../outside.json"):
                path.write_text(json.dumps({"name": "fixture", "mcpServers": reference}))
                row = next(row for row in self.run_repo(root) if row["gate_id"].endswith("conform-mcp"))
                self.assertEqual(row["result"], "ADVISORY")
                self.assertTrue(row["metadata"]["indeterminate"])


if __name__ == "__main__":
    unittest.main()
