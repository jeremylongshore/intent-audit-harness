#!/usr/bin/env bash
# crap-score join-regression suite.
#
# Pins the complexity/coverage join behavior of scripts/crap-score.py with
# stubbed providers (no gocyclo/go/cr install needed — deterministic in CI):
#   1. Go test-kind invokes gocyclo WITHOUT an ignore-everything pattern
#      (f-iah-python-1)
#   2. Go coverage join strips the go.mod module prefix so `go tool cover`
#      paths match gocyclo paths (f-iah-python-2)
#   3. JS coverage join normalizes absolute c8 coverage-summary.json keys to
#      repo-relative complexity-report paths (f-iah-python-3)
#
# Run from the repository root:
#   bash tests/crap-score/run-crap-score-tests.sh
#
# Exit 0 = all green; non-zero = regression.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

python3 "$ROOT/tests/crap-score/test_crap_score_joins.py"
