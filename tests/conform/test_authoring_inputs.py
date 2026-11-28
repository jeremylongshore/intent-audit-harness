"""Original byte binding, confinement and nonblocking special-file refusal."""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from authoring_inputs import (
    InvalidArtifact, MAX_JSON_BYTES, UnmeasuredReference,
    read_frontmatter_snapshot, read_json_snapshot, reference_path,
)


class AuthoringInputs(unittest.TestCase):
    def test_reference_syntax_does_not_expand_or_fetch(self):
        self.assertEqual(reference_path("./config/extra.json"), "config/extra.json")
        for value in ("https://example.invalid/a.json", "./bundle.mcpb", "../a.json", "/a.json",
                      "./a/../b.json", "./a\\b.json", "./a//b.json", "./a\0.json", None):
            with self.subTest(value=value), self.assertRaises(UnmeasuredReference):
                reference_path(value)

    def test_digest_binds_exact_original_bytes_not_reserialized_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir()
            raw = b'{ "hooks" : {} }\n'
            (root / "config/a.json").write_bytes(raw)
            self.assertEqual(read_json_snapshot(root, "config/a.json"),
                             ({"hooks": {}}, "sha256:" + hashlib.sha256(raw).hexdigest()))

    def test_symlink_file_and_parent_escape_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "a.json").write_text('{"fixture":"outside"}')
            (root / "file.json").symlink_to(outside / "a.json")
            (root / "dir").symlink_to(outside, target_is_directory=True)
            for path in ("file.json", "dir/a.json", "../outside/a.json", "/outside/a.json"):
                with self.subTest(path=path), self.assertRaises(UnmeasuredReference):
                    read_json_snapshot(root, path)

    def test_fifo_oversize_and_invalid_json_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.mkfifo(root / "pipe.json")
            (root / "large.json").write_bytes(b" " * (MAX_JSON_BYTES + 1))
            (root / "bad.json").write_text("synthetic-sensitive-value")
            for path in ("pipe.json", "large.json", "missing.json"):
                with self.subTest(path=path), self.assertRaises(UnmeasuredReference) as caught:
                    read_json_snapshot(root, path)
                self.assertNotIn("synthetic-sensitive-value", str(caught.exception))

    def test_malformed_or_ambiguous_json_is_a_violation_not_an_unmeasured_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for raw in (b'synthetic-sensitive-value', b'{"hooks":{},"hooks":{}}', b'{"value":NaN}'):
                (root / "bad.json").write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(InvalidArtifact) as caught:
                    read_json_snapshot(root, "bad.json")
                self.assertNotIn("synthetic-sensitive-value", str(caught.exception))

    def test_deep_nesting_is_unmeasured_with_exact_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = b'[' * 500 + b'0' + b']' * 500
            (root / "deep.json").write_bytes(raw)
            with self.assertRaises(UnmeasuredReference) as caught:
                read_json_snapshot(root, "deep.json")
            self.assertEqual(caught.exception.input_hash, "sha256:" + hashlib.sha256(raw).hexdigest())

    def test_frontmatter_duplicate_keys_cannot_hide_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = b"---\nhooks: invalid\nhooks: {}\n---\n"
            (root / "SKILL.md").write_bytes(raw)
            with self.assertRaises(InvalidArtifact) as caught:
                read_frontmatter_snapshot(root, "SKILL.md")
            self.assertEqual(caught.exception.input_hash, "sha256:" + hashlib.sha256(raw).hexdigest())

    def test_frontmatter_alias_graphs_are_unmeasured_before_construction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for content in ("a: &a [*a]", "a: &a [0]\nb: &b [*a, *a]\nhooks: {}"):
                raw = ("---\n" + content + "\n---\n").encode()
                (root / "SKILL.md").write_bytes(raw)
                with self.subTest(content=content), self.assertRaises(UnmeasuredReference) as caught:
                    read_frontmatter_snapshot(root, "SKILL.md")
                self.assertEqual(caught.exception.input_hash, "sha256:" + hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
