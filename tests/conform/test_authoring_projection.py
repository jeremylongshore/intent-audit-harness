"""Envelope identity, missing fields and original input preservation."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from authoring_projection import ProjectionError, component_parts, project_hooks, project_mcp


class AuthoringProjection(unittest.TestCase):
    def test_mcp_lifts_only_name_and_keeps_source_unchanged(self):
        data = {"mcpServers": {"server~/one": {"command": "fixture", "type": "stdio"}}}
        original = copy.deepcopy(data)
        self.assertEqual(project_mcp(data), [
            ("/mcpServers/server~0~1one", {"command": "fixture", "type": "stdio", "name": "server~/one"}),
        ])
        self.assertEqual(data, original)

    def test_explicit_bare_mcp_map_preserves_original_pointers(self):
        self.assertEqual(project_mcp({"one": {"command": "fixture"}}, bare=True),
                         [("/one", {"command": "fixture", "name": "one"})])
        self.assertEqual(project_mcp({}, bare=True), [])

    def test_mcp_rejects_ambiguous_identity_and_noninline_entries(self):
        for data in (None, [], {}, {"mcpServers": []}, {"mcpServers": "external.json"},
                     {"mcpServers": {"one": "external.json"}},
                     {"mcpServers": {"one": {"name": "two"}}}):
            with self.subTest(data=data), self.assertRaises(ProjectionError):
                project_mcp(data)
        self.assertEqual(project_mcp({"mcpServers": {"one": {"name": "one"}}}),
                         [("/mcpServers/one", {"name": "one"})])

    def test_hook_projection_keeps_order_and_only_lifts_declared_fields(self):
        data = {"hooks": {"PreToolUse": [
            {"matcher": "Read", "hooks": [{"type": "command", "command": "fixture"}, {"type": "prompt"}]},
            {"hooks": [{"command": "second"}]},
        ], "PostToolUse": [{"matcher": "Write", "hooks": [{"command": "third"}]}]}}
        original = copy.deepcopy(data)
        self.assertEqual(project_hooks(data), [
            ("/hooks/PreToolUse/0/hooks/0",
             {"type": "command", "command": "fixture", "event": "PreToolUse", "matcher": "Read"}),
            ("/hooks/PreToolUse/0/hooks/1", {"type": "prompt", "event": "PreToolUse", "matcher": "Read"}),
            ("/hooks/PreToolUse/1/hooks/0", {"command": "second", "event": "PreToolUse"}),
            ("/hooks/PostToolUse/0/hooks/0", {"command": "third", "event": "PostToolUse", "matcher": "Write"}),
        ])
        self.assertEqual(data, original)

    def test_hook_conflicts_and_malformed_groups_are_refused_without_values_in_errors(self):
        secret_fixture = "synthetic-sensitive-value"
        for groups in ({}, [None], [{}], [{"hooks": "external.json"}], [{"hooks": [None]}],
                       [{"hooks": [{"event": secret_fixture}]}],
                       [{"hooks": [{"matcher": secret_fixture}]}],
                       [{"matcher": "Read", "hooks": [{"matcher": secret_fixture}]}]):
            with self.subTest(groups=groups), self.assertRaises(ProjectionError) as caught:
                project_hooks({"hooks": {"PreToolUse": groups}})
            self.assertNotIn(secret_fixture, str(caught.exception))
        for data in (None, {}, {"hooks": "external.json"}, {"hooks": []}):
            with self.subTest(data=data), self.assertRaises(ProjectionError):
                project_hooks(data)

    def test_empty_envelopes_have_no_measurement_targets(self):
        self.assertEqual(project_mcp({"mcpServers": {}}), [])
        self.assertEqual(project_hooks({"hooks": {}}), [])
        self.assertEqual(project_hooks({"hooks": {"PreToolUse": []}}), [])
        self.assertEqual(project_hooks({"hooks": {"PreToolUse": [{"hooks": []}]}}), [])

    def test_manifest_mixed_parts_preserve_order_and_original_inline_pointers(self):
        inline = {"PreToolUse": [{"matcher": "Read", "hooks": [{"command": "fixture"}]}]}
        manifest = {"hooks": ["./extra.json", inline]}
        original = copy.deepcopy(manifest)
        self.assertEqual(component_parts(manifest, "hooks"), [("/hooks/0", "./extra.json"), ("/hooks/1", inline)])
        self.assertEqual(project_hooks(inline, bare=True, base="/hooks/1"), [
            ("/hooks/1/PreToolUse/0/hooks/0", {"command": "fixture", "event": "PreToolUse", "matcher": "Read"}),
        ])
        self.assertEqual(project_mcp({"one": {}}, bare=True, base="/mcpServers/2"),
                         [("/mcpServers/2/one", {"name": "one"})])
        self.assertEqual(manifest, original)
        self.assertEqual(component_parts({}, "hooks"), [])
        for value in (None, 1, "", [False], [[{}]]):
            with self.subTest(value=value), self.assertRaises(ProjectionError):
                component_parts({"hooks": value}, "hooks")


if __name__ == "__main__":
    unittest.main()
