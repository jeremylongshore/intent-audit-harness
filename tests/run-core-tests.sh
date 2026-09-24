#!/usr/bin/env bash
# Aggregate deterministic/offline test entry point for contributors and releases.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUITES=(
  tests/regression/run-regression.sh
  tests/escape-scan/run-escape-scan-tests.sh
  tests/worktree-run/run-worktree-run-tests.sh
  tests/harness-hash/run-harness-hash-tests.sh
  tests/semver/run-semver-tests.sh
  tests/cred-gate/run-cred-gate-tests.sh
  tests/classify/run-classify-tests.sh
  tests/conform/run-conform-tests.sh
  tests/audit/run-audit-tests.sh
  tests/scan/run-scan-tests.sh
  tests/currency/run-currency-tests.sh
  tests/migration-notes/run-migration-notes-tests.sh
  tests/crap-score/run-crap-score-tests.sh
  tests/golden/run-golden.sh
  tests/dns-preflight/run-dns-preflight-tests.sh
  tests/kernel-shadow/run-kernel-shadow-tests.sh
)

cd "$ROOT"
for suite in "${SUITES[@]}"; do
  echo "==> $suite"
  bash "$suite"
done

echo "All deterministic core suites passed."
