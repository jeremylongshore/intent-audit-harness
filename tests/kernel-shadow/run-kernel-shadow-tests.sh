#!/usr/bin/env bash
# tests/kernel-shadow/run-kernel-shadow-tests.sh
#
# Contract tests for scripts/kernel-shadow-check.sh.
#
# The detector previously had NO tests, and shipped a blind spot that mattered: it
# reported bobs-big-brain-compiler CLEAN while that repo pinned
# `"@intentsolutions/core": "^0.1.1"` against a kernel at 0.10.0. These tests pin
# both detection classes so that regression is caught here rather than in a consumer.
#
# Every case sets KERNEL_LATEST_VERSION so the suite is deterministic and offline —
# no npm lookup, no dependence on what happens to be published today.
#
# Usage: bash tests/kernel-shadow/run-kernel-shadow-tests.sh
# Exit:  0 all pass, 1 any failure

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CHECK="${REPO_ROOT}/scripts/kernel-shadow-check.sh"

PASS=0
FAIL=0

# Build a throwaway repo whose only content is one package.json declaring RANGE.
make_fixture() {
  local dir="$1" range="$2"
  mkdir -p "$dir/pkg"
  ( cd "$dir" && git init -q . )
  printf '{"name":"fixture","dependencies":{"@intentsolutions/core":"%s"}}\n' "$range" \
    > "$dir/pkg/package.json"
}

# assert_range RANGE LATEST EXPECTED("admits"|"stale"|"unknown")
assert_range() {
  local range="$1" latest="$2" expected="$3"
  local tmp out verdict
  tmp="$(mktemp -d)"
  make_fixture "$tmp" "$range"
  out="$( cd "$tmp" && KERNEL_LATEST_VERSION="$latest" bash "$CHECK" 2>&1 )"
  rm -rf "$tmp"

  if grep -q 'cannot resolve to' <<<"$out"; then
    verdict="stale"
  elif grep -q 'range form not understood' <<<"$out"; then
    verdict="unknown"
  else
    verdict="admits"
  fi

  if [[ "$verdict" == "$expected" ]]; then
    echo "  ok    ${range} vs ${latest} -> ${expected}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${range} vs ${latest} -> got ${verdict}, want ${expected}" >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_exit() {
  local desc="$1" expected="$2"; shift 2
  "$@" >/dev/null 2>&1
  local got=$?
  if [[ "$got" == "$expected" ]]; then
    echo "  ok    ${desc} (exit ${got})"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${desc}: exit ${got}, want ${expected}" >&2
    FAIL=$((FAIL + 1))
  fi
}

echo "kernel-shadow-check contract tests"
echo "──────────────────────────────────"

echo "range admission — the 0.x caret trap (the bug that shipped):"
# ^0.1.1 == >=0.1.1 <0.2.0. It can NEVER reach 0.10.0. This is the exact range
# bobs-big-brain-compiler carried while the detector called it clean.
assert_range '^0.1.1'  '0.10.0' 'stale'
assert_range '^0.9.0'  '0.10.0' 'stale'
assert_range '^0.10.0' '0.10.0' 'admits'
# Guard against the naive reading "caret crosses minors" — true for >=1.0.0, false for 0.x.
assert_range '^0.1.1'  '0.1.9'  'admits'

echo "range admission — tilde is minor-pinned at every major:"
assert_range '~0.10.1' '0.10.0' 'admits'
assert_range '~0.9.1'  '0.10.0' 'stale'
assert_range '~1.2.0'  '1.3.0'  'stale'

echo "range admission — caret above 1.0.0 crosses minors:"
assert_range '^1.2.3'  '1.9.0'  'admits'
assert_range '^1.2.3'  '2.0.0'  'stale'
assert_range '^1.2.3'  '0.10.0' 'stale'

echo "range admission — exact, open, and link forms:"
assert_range '0.10.0'      '0.10.0' 'admits'
assert_range '0.9.0'       '0.10.0' 'stale'
assert_range '>=0.9.0'     '0.10.0' 'admits'
assert_range '*'           '0.10.0' 'admits'
assert_range 'workspace:^' '0.10.0' 'admits'

echo "unknown forms are surfaced, never assumed OK:"
# The safe failure for an unparsed range is "tell a human", not "looks fine".
assert_range 'not-a-range'      '0.10.0' 'unknown'
assert_range '0.1.x || ^0.2.0'  '0.10.0' 'unknown'

echo "exit codes:"
STALE_FIXTURE="$(mktemp -d)"
make_fixture "$STALE_FIXTURE" '^0.1.1'
assert_exit "advisory mode does not fail the build" 0 \
  env -C "$STALE_FIXTURE" KERNEL_LATEST_VERSION=0.10.0 bash "$CHECK"
assert_exit "--strict gates a stale range" 1 \
  env -C "$STALE_FIXTURE" KERNEL_LATEST_VERSION=0.10.0 bash "$CHECK" --strict
rm -rf "$STALE_FIXTURE"

CLEAN_FIXTURE="$(mktemp -d)"
make_fixture "$CLEAN_FIXTURE" '^0.10.0'
assert_exit "--strict passes a current range" 0 \
  env -C "$CLEAN_FIXTURE" KERNEL_LATEST_VERSION=0.10.0 bash "$CHECK" --strict
rm -rf "$CLEAN_FIXTURE"

echo "an unresolvable kernel version SKIPS loudly, never reports clean:"
# "we could not check" and "it is fine" are different answers; only one is safe to
# print as clean. Simulate an npm lookup failure and assert we do not claim cleanliness.
OFFLINE_FIXTURE="$(mktemp -d)"
make_fixture "$OFFLINE_FIXTURE" '^0.10.0'
OFFLINE_CHECK="$(mktemp)"
sed 's|npm view|false npm view|' "$CHECK" > "$OFFLINE_CHECK"
offline_out="$( cd "$OFFLINE_FIXTURE" && bash "$OFFLINE_CHECK" 2>&1 )"
if grep -q 'SKIPPED the kernel-range check' <<<"$offline_out" \
   && grep -q 'Not reporting fully clean' <<<"$offline_out" \
   && ! grep -q 'every @intentsolutions/core range resolves' <<<"$offline_out"; then
  echo "  ok    skips loudly and withholds the clean claim"
  PASS=$((PASS + 1))
else
  echo "  FAIL  offline path did not skip loudly" >&2
  printf '        %s\n' "$offline_out" >&2
  FAIL=$((FAIL + 1))
fi
rm -rf "$OFFLINE_FIXTURE" "$OFFLINE_CHECK"

echo "the original detection class still works (no regression):"
SHADOW_FIXTURE="$(mktemp -d)"
mkdir -p "$SHADOW_FIXTURE/src"
( cd "$SHADOW_FIXTURE" && git init -q . )
echo 'export interface GateResultV1 { decision: string }' > "$SHADOW_FIXTURE/src/shadow.ts"
assert_exit "--strict gates a re-declared kernel type" 1 \
  env -C "$SHADOW_FIXTURE" KERNEL_LATEST_VERSION=0.10.0 bash "$CHECK" --strict
rm -rf "$SHADOW_FIXTURE"

echo "──────────────────────────────────"
echo "kernel-shadow-check results: PASS=${PASS}  FAIL=${FAIL}"
[[ "$FAIL" -eq 0 ]] || exit 1
