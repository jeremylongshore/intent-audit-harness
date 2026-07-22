#!/usr/bin/env bash
# tests/escape-scan/run-escape-scan-tests.sh
#
# Contract tests for the coverage-threshold detection in scripts/escape-scan.sh
# and for the policy-loading path that precedes it.
#
# These pin three bugs that shipped in v1.3.0, all of them on the tool's
# flagship advertised behaviour ("an agent can't quietly lower the coverage bar"):
#
#   1. The key pattern required DOUBLE QUOTES, so `"lines":<N>` in package.json
#      was caught but `lines:<N>` in jest.config.js was not — the standard JS
#      config shape, and the most common Jest form there is.
#   2. Only the FIRST number on the line was compared to the floor, so
#      `{ branches:<hi>, lines:<lo> }` tested the FIRST value and never saw the second.
#      This bit the quoted form too: the "working" case was also broken.
#   3. Worst: a tests/TESTING.md missing ANY of the three policy keys killed the
#      script mid-load under `set -euo pipefail`, before a single check ran —
#      no output, exit 1. Exit 1 is the documented CHALLENGE code, so the repo
#      looked like it merely warned while in fact NOTHING was scanned.
#
# Every fixture is a throwaway git repo built from literal text: deterministic,
# offline, no network.
#
# Usage: bash tests/escape-scan/run-escape-scan-tests.sh
# Exit:  0 all pass, 1 any failure

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SCAN="${REPO_ROOT}/scripts/escape-scan.sh"

PASS=0
FAIL=0

# new_repo [TESTING_MD_CONTENT] — echoes a fresh repo dir with a committed baseline.
new_repo() {
  local dir policy="${1-}"
  dir="$(mktemp -d)"
  ( cd "$dir" && git init -q . \
      && git config user.email t@example.com && git config user.name t )
  if [[ -n "$policy" ]]; then
    mkdir -p "$dir/tests"
    printf '%s\n' "$policy" > "$dir/tests/TESTING.md"
  fi
  ( cd "$dir" && git add -A >/dev/null 2>&1 \
      && git commit -q -m baseline --allow-empty >/dev/null 2>&1 )
  echo "$dir"
}

# assert_scan DESC POLICY FILE CONTENT EXPECTED(pass|REFUSE|CHALLENGE)
assert_scan() {
  local desc="$1" policy="$2" file="$3" content="$4" want="$5"
  local dir ec got
  dir="$(new_repo "$policy")"
  mkdir -p "$dir/$(dirname "$file")"
  printf '%s\n' "$content" > "$dir/$file"
  ( cd "$dir" && git add "$file" >/dev/null 2>&1 )
  ( cd "$dir" && bash "$SCAN" --staged >/dev/null 2>&1 ); ec=$?
  rm -rf "$dir"

  case "$ec" in
    0) got="pass" ;;
    1) got="CHALLENGE" ;;
    2) got="REFUSE" ;;
    *) got="exit${ec}" ;;
  esac

  if [[ "$got" == "$want" ]]; then
    echo "  ok    ${desc} -> ${got}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${desc}: got ${got}, want ${want}" >&2
    FAIL=$((FAIL + 1))
  fi
}

# Trigger values are BUILT, never written literally.
#
# These fixtures must contain the exact strings escape-scan refuses — that is
# what makes them fixtures. But escape-scan also scans the staged diff of THIS
# file, so literals here would make the suite unaddable to the repo it protects.
#
# The alternative was to path-allowlist tests/escape-scan/** inside the scanner.
# Rejected: any path the scanner skips is a path an agent can hide a real escape
# in, and widening the evasion surface of a security tool to make its own tests
# committable is a bad trade. Composing the values keeps the bypass surface at
# zero — `lines: ${LOW}` simply is not a coverage-lowering line.
LOW=50          # below the 80 floor used by these tests
VERY_LOW=5      # far below any plausible floor
TEN=10
NINETY=90
NINETY_FIVE=95
WARN=warn
SKIP=skip
SQ="'"        # a single quote, composed so it is not a literal here

FULL='coverage.line: 80
coverage.branch: 70
mutation.kill_rate: 70'

echo "escape-scan coverage-threshold contract tests"
echo "────────────────────────────────────────────"

echo "a clean diff must not fire (no crying wolf):"
assert_scan "benign added function" "$FULL" 'src/util.js' \
  'function add(a, b) { return a + b; }' 'pass'
assert_scan "a threshold ABOVE the floor" "$FULL" 'jest.config.js' \
  "  lines: ${NINETY_FIVE}," 'pass'
assert_scan "max_lines must not match the lines key" "$FULL" 'cfg.js' \
  "  max_lines: ${VERY_LOW}," 'pass'

echo "lowering the coverage floor is REFUSED, in every config dialect:"
# Bug 1 — the quoted form worked; the unquoted JS form is the one that shipped broken.
assert_scan "package.json  quoted lines key (JSON form)" "$FULL" 'package.json' \
  "{ \"coverageThreshold\": { \"global\": { \"lines\": ${LOW} } } }" 'REFUSE'
assert_scan "jest.config.js  unquoted lines key (JS form)" "$FULL" 'jest.config.js' \
  "module.exports = { coverageThreshold: { global: { lines: ${LOW} } } };" 'REFUSE'
assert_scan "jest  lowered lines key on its own line" "$FULL" 'jest.config.js' \
  "  lines: ${LOW}," 'REFUSE'
# A one-character evasion: single quotes are valid JS object-key syntax and were
# slipping past a double-quote-only character class.
assert_scan "jest  SINGLE-quoted key (valid JS)" "$FULL" 'jest.config.js' \
  "  ${SQ}lines${SQ}: ${LOW}," 'REFUSE'
assert_scan "single-quoted key ABOVE the floor passes" "$FULL" 'jest.config.js' \
  "  ${SQ}lines${SQ}: ${NINETY_FIVE}," 'pass'
assert_scan "branches key, not just lines" "$FULL" 'jest.config.js' \
  "  branches: ${TEN}," 'REFUSE'
assert_scan "python  lowered fail_under" "$FULL" '.coveragerc' \
  "fail_under = ${LOW}" 'REFUSE'
assert_scan "python  lowered --cov-fail-under flag" "$FULL" 'pytest.ini' \
  "addopts = --cov-fail-under=${LOW}" 'REFUSE'

# Bug 2 — a passing first key must not mask a lowered later key.
echo "a compliant first key must not mask a lowered later one:"
assert_scan "unquoted  compliant branches, lowered lines" "$FULL" 'jest.config.js' \
  "  global: { branches: ${NINETY}, lines: ${LOW} }," 'REFUSE'
assert_scan "quoted    compliant branches, lowered lines" "$FULL" 'package.json' \
  "{ \"global\": { \"branches\": ${NINETY}, \"lines\": ${LOW} } }" 'REFUSE'

# Bug 3 — the policy loader must never abort the scan.
echo "an incomplete or absent tests/TESTING.md must NOT bypass the scan:"
assert_scan "TESTING.md with only coverage.line" 'coverage.line: 80' '.coveragerc' \
  "fail_under = ${VERY_LOW}" 'REFUSE'
assert_scan "TESTING.md with only mutation.kill_rate" 'mutation.kill_rate: 70' '.coveragerc' \
  "fail_under = ${VERY_LOW}" 'REFUSE'
assert_scan "TESTING.md present but empty" '' '.coveragerc' \
  "fail_under = ${VERY_LOW}" 'REFUSE'
assert_scan "no tests/TESTING.md at all (built-in defaults)" '' '.coveragerc' \
  "fail_under = ${VERY_LOW}" 'REFUSE'
# The floor must still come FROM the file when the key is present: 50 is below a
# floor of 80 but above a floor of 40, so a repo declaring the lower one passes.
assert_scan "a repo-declared LOWER floor is honoured" 'coverage.line: 40' 'jest.config.js' \
  "  lines: ${LOW}," 'pass'

echo "coverage keys are thresholds ONLY inside coverage configs:"
# Making quotes optional briefly turned `const x = { lines: 3 }` in ordinary
# source into a REFUSE. A threshold outside a coverage config has no effect and
# so cannot be an escape; blocking honest commits is worse than the gap.
assert_scan "app code  { lines: 3 }  must NOT fire" "$FULL" 'src/app.js' \
  "const x = { lines: ${TEN} };" 'pass'
assert_scan "app code  { statements: 12 }  must NOT fire" "$FULL" 'src/stats.js' \
  "const s = { statements: ${TEN} };" 'pass'
assert_scan "but jest.config.js still REFUSEs" "$FULL" 'jest.config.js' \
  "  lines: ${LOW}," 'REFUSE'
assert_scan "and a nested monorepo jest.config.js does too" "$FULL" 'packages/a/jest.config.js' \
  "  lines: ${LOW}," 'REFUSE'
assert_scan "and .nycrc does too" "$FULL" '.nycrc' \
  "  \"lines\": ${LOW}" 'REFUSE'

echo "a non-numeric policy value must fall back, never fail open:"
# `coverage.line: eighty` used to become the floor, every comparison then died
# on an arithmetic error, and the scan ended REFUSE=0 exit 0 — fail-OPEN.
assert_scan "non-numeric floor still REFUSEs a blatant lowering" 'coverage.line: eighty' '.coveragerc' \
  "fail_under = ${VERY_LOW}" 'REFUSE'

echo "the other REFUSE/CHALLENGE classes still fire (no regression):"
assert_scan "skip marker is CHALLENGED" "$FULL" 'test/a.test.js' \
  "it.${SKIP}(\"does the thing\", () => {});" 'CHALLENGE'
assert_scan "architecture-rule bypass is REFUSED" "$FULL" '.dependency-cruiser.js' \
  "  severity: \"${WARN}\"," 'REFUSE'

echo "────────────────────────────────────────────"
echo "escape-scan results: PASS=${PASS}  FAIL=${FAIL}"
[[ "$FAIL" -eq 0 ]] || exit 1
