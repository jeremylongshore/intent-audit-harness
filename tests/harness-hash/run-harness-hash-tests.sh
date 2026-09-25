#!/usr/bin/env bash
# Contract tests for the default policy denominator protected by harness-hash.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HASH_SCRIPT="$REPO_ROOT/scripts/harness-hash.sh"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

PASS=0
FAIL=0
pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

mkdir -p "$FIXTURE_ROOT/tests" "$FIXTURE_ROOT/.github/workflows" "$FIXTURE_ROOT/.circleci" "$FIXTURE_ROOT/src"
printf '%s\n' '{"scripts":{"test":"c8 --check-coverage node --test"}}' > "$FIXTURE_ROOT/package.json"
printf '%s\n' 'coverage.line: 95' > "$FIXTURE_ROOT/tests/TESTING.md"
printf '%s\n' '{"lines":95}' > "$FIXTURE_ROOT/.c8rc.json"
printf '%s\n' '{"branches":90}' > "$FIXTURE_ROOT/.nycrc.json"
printf '%s\n' 'module.exports = { coverageThreshold: { global: { lines: 95 } } }' > "$FIXTURE_ROOT/jest.config.js"
printf '%s\n' 'export default { test: { coverage: { thresholds: { lines: 95 } } } }' > "$FIXTURE_ROOT/vitest.config.ts"
printf '%s\n' '[tool.pytest.ini_options]' 'addopts = "--cov-fail-under=95"' > "$FIXTURE_ROOT/pyproject.toml"
printf '%s\n' '[pytest]' 'addopts = --cov-fail-under=95' > "$FIXTURE_ROOT/pytest.ini"
printf '%s\n' '[run]' 'branch = True' > "$FIXTURE_ROOT/.coveragerc"
printf '%s\n' '{"thresholds":{"high":95}}' > "$FIXTURE_ROOT/stryker.conf.json"
printf '%s\n' 'jobs: { test: { steps: [{ run: npm test }] } }' > "$FIXTURE_ROOT/.github/workflows/ci.yml"
printf '%s\n' 'version: 2.1' > "$FIXTURE_ROOT/.circleci/config.yml"
printf '%s\n' 'ordinary application source' > "$FIXTURE_ROOT/src/app.js"

if ROOT="$FIXTURE_ROOT" bash "$HASH_SCRIPT" --init >/dev/null; then
  pass "initializes a consumer manifest"
else
  fail "initializes a consumer manifest"
fi

expected=(
  package.json tests/TESTING.md .c8rc.json .nycrc.json jest.config.js
  vitest.config.ts pyproject.toml pytest.ini .coveragerc stryker.conf.json
  .github/workflows/ci.yml .circleci/config.yml
)
listed="$(ROOT="$FIXTURE_ROOT" bash "$HASH_SCRIPT" --list 2>/dev/null)"
for file in "${expected[@]}"; do
  if grep -Fxq "$file" <<< "$listed"; then
    pass "pins $file"
  else
    fail "pins $file"
  fi
done
if grep -Fxq 'src/app.js' <<< "$listed"; then
  fail "ordinary source stays outside the policy denominator"
else
  pass "ordinary source stays outside the policy denominator"
fi

printf '%s\n' '{"scripts":{"test":"node --test"}}' > "$FIXTURE_ROOT/package.json"
ec=0
ROOT="$FIXTURE_ROOT" bash "$HASH_SCRIPT" --verify >/dev/null 2>&1 || ec=$?
if [[ "$ec" -eq 2 ]]; then
  pass "changing the package test command is HARNESS_TAMPERED"
else
  fail "changing the package test command exits 2 (got $ec)"
fi

ROOT="$FIXTURE_ROOT" bash "$HASH_SCRIPT" --init >/dev/null
printf '%s\n' 'changed application source' > "$FIXTURE_ROOT/src/app.js"
if ROOT="$FIXTURE_ROOT" bash "$HASH_SCRIPT" --verify >/dev/null 2>&1; then
  pass "ordinary source edits do not require a policy re-pin"
else
  fail "ordinary source edits do not require a policy re-pin"
fi

rm -f "$FIXTURE_ROOT/.github/workflows/ci.yml"
ec=0
ROOT="$FIXTURE_ROOT" bash "$HASH_SCRIPT" --verify >/dev/null 2>&1 || ec=$?
if [[ "$ec" -eq 2 ]]; then
  pass "removing a CI enforcement workflow is HARNESS_TAMPERED"
else
  fail "removing a CI enforcement workflow exits 2 (got $ec)"
fi

echo "harness-hash contract: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
