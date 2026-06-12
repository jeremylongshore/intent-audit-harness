#!/usr/bin/env python3
"""Regression tests for crap-score.py complexity/coverage joins.

Covers three review findings (2026-06-11):
  f-iah-python-1 — Go test-kind: gocyclo was invoked with -ignore '.*\\.go$',
                   which ignores EVERY .go file, so test CRAP was always empty.
  f-iah-python-2 — Go coverage join: gocyclo emits repo-relative paths while
                   `go tool cover -func` emits module-qualified paths; the
                   coverage dict lookup always missed (coverage=0.0 for all).
  f-iah-python-3 — JS coverage join: c8 coverage-summary.json keys are
                   absolute paths while complexity-report paths are
                   repo-relative; the lookup always missed (coverage=0.0).

The external tools (gocyclo / go / cr) are stubbed: `run` is replaced with a
fake that emulates each tool's documented output, and `which_or_none` is
replaced so the code under test believes the tools are installed. The gocyclo
stub honors -ignore with re.search — the same unanchored matching gocyclo
itself uses — so finding 1 fails before the fix and passes after.

Run standalone:
    python3 tests/crap-score/test_crap_score_joins.py
or via the suite runner:
    bash tests/crap-score/run-crap-score-tests.sh
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "crap-score.py"


def load_crap_score():
    spec = importlib.util.spec_from_file_location("crap_score", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: dataclass machinery resolves annotations through
    # sys.modules[cls.__module__] (standard importlib loading recipe).
    sys.modules["crap_score"] = mod
    spec.loader.exec_module(mod)
    return mod


class GocycloTestKindRegression(unittest.TestCase):
    """f-iah-python-1: kind='test' must analyze *_test.go files."""

    GO_FILES = ["main.go", "main_test.go", "pkg/util.go", "pkg/util_test.go"]

    def setUp(self):
        self.mod = load_crap_score()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def fake_run(self, cmd, cwd):
        if cmd[0] == "gocyclo":
            # Emulate gocyclo: -ignore REGEX skips files matching the regex
            # (unanchored search, like Go's regexp.MatchString).
            ignore = None
            if "-ignore" in cmd:
                ignore = cmd[cmd.index("-ignore") + 1]
            lines = []
            for f in self.GO_FILES:
                if ignore and re.search(ignore, f):
                    continue
                lines.append(f"4 pkg Func {f}:1:1")
            return 0, "\n".join(lines) + ("\n" if lines else ""), ""
        if cmd[0] == "go":
            return 0, "", ""
        raise AssertionError(f"unexpected command: {cmd}")

    def patched(self):
        self.mod.which_or_none = lambda c: "/stub/" + c if c == "gocyclo" else None
        self.mod.run = self.fake_run

    def test_test_kind_scores_test_files(self):
        self.patched()
        scores = self.mod.score_go(self.root, "test")
        paths = sorted(s.path for s in scores)
        self.assertEqual(
            paths, ["main_test.go", "pkg/util_test.go"],
            "kind='test' must score *_test.go files — an ignore-all gocyclo "
            "pattern silently empties the test CRAP gate",
        )

    def test_src_kind_scores_only_non_test_files(self):
        self.patched()
        scores = self.mod.score_go(self.root, "src")
        paths = sorted(s.path for s in scores)
        self.assertEqual(paths, ["main.go", "pkg/util.go"])


class GoCoverageJoinRegression(unittest.TestCase):
    """f-iah-python-2: module-qualified cover paths must join gocyclo paths."""

    def setUp(self):
        self.mod = load_crap_score()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        (self.root / "go.mod").write_text(
            "module github.com/acme/widget\n\ngo 1.22\n"
        )
        (self.root / "coverage.out").write_text("mode: atomic\n")

    def fake_run(self, cmd, cwd):
        if cmd[0] == "gocyclo":
            return 0, "7 widget Frobnicate pkg/frob.go:10:1\n", ""
        if cmd[:3] == ["go", "tool", "cover"]:
            return 0, (
                "github.com/acme/widget/pkg/frob.go:10:\tFrobnicate\t80.0%\n"
                "total:\t(statements)\t80.0%\n"
            ), ""
        raise AssertionError(f"unexpected command: {cmd}")

    def test_coverage_joins_module_qualified_paths(self):
        self.mod.which_or_none = lambda c: "/stub/" + c
        self.mod.run = self.fake_run
        scores = self.mod.score_go(self.root, "src")
        self.assertEqual(len(scores), 1)
        self.assertEqual(
            scores[0].coverage, 80.0,
            "go tool cover module-qualified path must be stripped to "
            "repo-relative so it joins the gocyclo complexity path",
        )
        # CRAP must be computed with the real coverage, not 0%:
        self.assertAlmostEqual(
            scores[0].crap, self.mod.crap(7, 80.0), places=6
        )


class JsCoverageJoinRegression(unittest.TestCase):
    """f-iah-python-3: absolute c8 coverage keys must join relative cr paths."""

    def setUp(self):
        self.mod = load_crap_score()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        (self.root / "src").mkdir()
        (self.root / "src" / "foo.js").write_text("function f(){}\n")
        cov_dir = self.root / "coverage"
        cov_dir.mkdir()
        abs_key = str(self.root / "src" / "foo.js")
        (cov_dir / "coverage-summary.json").write_text(json.dumps({
            "total": {"lines": {"pct": 75.0}},
            abs_key: {"lines": {"pct": 75.0}},
        }))

    def fake_run(self, cmd, cwd):
        # complexity-report invocation: cr --format json src
        return 0, json.dumps({
            "reports": [{
                "path": "src/foo.js",
                "functions": [{"name": "f", "cyclomatic": 3}],
            }],
        }), ""

    def test_coverage_joins_absolute_summary_keys(self):
        self.mod.which_or_none = lambda c: "/stub/cr" if c == "cr" else None
        self.mod.run = self.fake_run
        scores = self.mod.score_js(self.root, "src")
        self.assertEqual(len(scores), 1)
        self.assertEqual(
            scores[0].coverage, 75.0,
            "absolute coverage-summary.json keys must be normalized to "
            "repo-relative so they join complexity-report paths",
        )
        self.assertAlmostEqual(
            scores[0].crap, self.mod.crap(3, 75.0), places=6
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
