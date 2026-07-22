#!/usr/bin/env bash
# tests/kernel-shadow/run-kernel-shadow-tests.sh
#
# Offline contract tests for both kernel-shadow classes:
#   1. local re-declarations of kernel-owned contracts;
#   2. dependency ranges that cannot resolve to the current kernel.
#
# Usage: bash tests/kernel-shadow/run-kernel-shadow-tests.sh
# Exit:  0 all pass, 1 any failure

# shellcheck disable=SC2016
# Fixture strings intentionally contain literal `$id`, `$ref`, and TypeScript.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CHECK="${REPO_ROOT}/scripts/kernel-shadow-check.sh"
KERNEL_VERSION="0.10.0"
PASS=0
FAIL=0

make_source_fixture() {
  local rel="$1" content="$2" dir
  dir="$(mktemp -d)"
  mkdir -p "$dir/$(dirname "$rel")"
  printf '%s\n' "$content" > "$dir/$rel"
  ( cd "$dir" && git init -q . )
  echo "$dir"
}

make_range_fixture() {
  local dir="$1" range="$2"
  mkdir -p "$dir/pkg"
  ( cd "$dir" && git init -q . )
  printf '{"name":"fixture","dependencies":{"@intentsolutions/core":"%s"}}\n' "$range" \
    > "$dir/pkg/package.json"
}

assert_source() {
  local desc="$1" rel="$2" content="$3" expected="$4"
  local dir out verdict
  dir="$(make_source_fixture "$rel" "$content")"
  out="$(cd "$dir" && KERNEL_LATEST_VERSION="$KERNEL_VERSION" bash "$CHECK" 2>&1)"
  rm -rf "$dir"

  if grep -q 'potential kernel shadow' <<<"$out"; then
    verdict="shadow"
  else
    verdict="clean"
  fi

  if [[ "$verdict" == "$expected" ]]; then
    echo "  ok    ${desc} -> ${expected}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${desc}: got ${verdict}, want ${expected}" >&2
    printf '        %s\n' "$out" >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_range() {
  local range="$1" latest="$2" expected="$3"
  local dir out verdict
  dir="$(mktemp -d)"
  make_range_fixture "$dir" "$range"
  out="$(cd "$dir" && KERNEL_LATEST_VERSION="$latest" bash "$CHECK" 2>&1)"
  rm -rf "$dir"

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
    printf '        %s\n' "$out" >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_exit() {
  local desc="$1" expected="$2"
  shift 2
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

echo "kernel references are clean; local re-declarations are shadows:"
assert_source "multi-line kernel re-export" 'src/index.ts' \
'export {
  EvidenceBundleSchema,
  type EvidenceBundle,
  type GateResultV1,
} from "@intentsolutions/core/validators/v1/evidence-bundle.js";' 'clean'
assert_source "single-line kernel re-export" 'src/reexport.ts' \
'export { type GateResultV1 } from "@intentsolutions/core";' 'clean'
assert_source "inline kernel type import" 'src/consume.ts' \
'import { type EvidenceBundle, GateResultV1Schema } from "@intentsolutions/core";' 'clean'
assert_source "plain type-only import" 'src/consume2.ts' \
'import type { GateResultV1 } from "@intentsolutions/core";' 'clean'
assert_source "kernel z.infer derivation" 'src/derive.ts' \
'import { EvidenceBundlePayloadSchema } from "@intentsolutions/core/validators/v1/evidence-statement";
export type EvidenceBundle = z.infer<typeof EvidenceBundlePayloadSchema>;' 'clean'
assert_source "z.infer over a multiline kernel re-export" 'src/derive-multiline.ts' \
'export {
  EvidenceBundlePayloadSchema,
  type EvidenceBundlePayload,
} from "@intentsolutions/core/validators/v1/evidence-statement";
export type EvidenceBundle = z.infer<typeof EvidenceBundlePayloadSchema>;' 'clean'
assert_source "bare alias to a kernel-imported type" 'src/derive-bare.ts' \
'import type { GateResultV1 as KernelGateResult } from "@intentsolutions/core";
export type GateResultV1 = KernelGateResult;' 'clean'
assert_source "comment/string mention" 'src/prose.ts' \
'// emits a GateResultV1 row
const uri = "https://evals.intentsolutions.io/gate-result/v1";' 'clean'
assert_source "local interface" 'src/shadow.ts' \
'export interface GateResultV1 { decision: string }' 'shadow'
assert_source "local generic interface" 'src/shadow-generic.ts' \
'interface EvidenceBundle<T> { rows: T[] }' 'shadow'
assert_source "interface extending another" 'src/shadow-extends.ts' \
'export interface EvidenceBundlePayload extends Base { rows: unknown[] }' 'shadow'
assert_source "local generic type" 'src/shadow-type.ts' \
'export type EvidenceBundlePayload<T> = { rows: T[] };' 'shadow'
assert_source "local class" 'src/shadow-class.ts' \
'export class EvidenceBundle { constructor(public rows: unknown[]) {} }' 'shadow'
assert_source "class implementing an interface" 'src/shadow-impl.ts' \
'class GateResultV1 implements Predicate { decision = "PASS" }' 'shadow'
assert_source "declare-d ambient interface" 'src/shadow-declare.d.ts' \
'declare interface GateResultV1 { decision: string }' 'shadow'
assert_source "generic type alias" 'src/alias-generic.ts' \
'export type EvidenceBundlePayload<T> = { rows: T[] };' 'shadow'
assert_source "local Python class" 'models.py' \
'class GateResultV1:\n    pass' 'shadow'
assert_source "local Pydantic model" 'models_pydantic.py' \
'class EvidenceBundlePayload(BaseModel):
    rows: list[dict]' 'shadow'
assert_source "Python kernel import" 'consume.py' \
'from intent_eval_core.v1 import GateResultV1, EvidenceBundle' 'clean'
assert_source "local schema canonical id" 'schemas/mine.json' \
'{"$id": "https://evals.intentsolutions.io/gate-result/v1/schema.json"}' 'shadow'
assert_source "own conform namespace" 'schemas/own.json' \
'{"$id": "https://evals.intentsolutions.io/conform/v1/skill.json"}' 'clean'
assert_source "redirect stub" 'specs/gate-result.schema.json' \
'{
  "$id": "https://evals.intentsolutions.io/gate-result/v1.schema.json",
  "$ref": "https://raw.githubusercontent.com/jeremylongshore/intent-eval-core/main/schemas/v1/gate-result.schema.json",
  "x-redirect": { "kernel-npm": "@intentsolutions/core/schemas/v1/gate-result.schema.json" }
}' 'clean'
assert_source "local z.infer is not kernel-derived" 'src/derive-local.ts' \
'const MyOwnSchema = z.object({ decision: z.string() });
export type GateResultV1 = z.infer<typeof MyOwnSchema>;' 'shadow'
assert_source "structural type mentioning kernel symbol" 'src/derive-structural.ts' \
'import { EvidenceBundlePayloadSchema } from "@intentsolutions/core";
export type EvidenceBundle = { rows: EvidenceBundlePayloadSchema[] };' 'shadow'
assert_source "union mentioning kernel symbol" 'src/derive-union.ts' \
'import { GateResultV1Schema } from "@intentsolutions/core";
export type GateResultV1 = z.infer<typeof GateResultV1Schema> | { legacy: true };' 'shadow'
assert_source "derivation alongside real declaration" 'src/mixed.ts' \
'import { EvidenceBundlePayloadSchema } from "@intentsolutions/core";
export type EvidenceBundlePayload = z.infer<typeof EvidenceBundlePayloadSchema>;
export interface GateResultV1 { decision: string }' 'shadow'
assert_source "allowlisted fixture path" 'tests/fixtures/frozen.ts' \
'export interface GateResultV1 { decision: string }' 'clean'
assert_source "allowlisted CI emitter" 'ci/emit.ts' \
'export interface GateResultV1 { decision: string }' 'clean'
assert_source "allowlisted conform schema" 'schemas/conform/v1/x.json' \
'{"$id": "https://evals.intentsolutions.io/gate-result/v1/schema.json"}' 'clean'
assert_source "allowlisted dist output" 'packages/core/dist/index.d.ts' \
'type EvidenceBundle = z.infer<typeof EvidenceBundlePayloadSchema>;' 'clean'
assert_source "allowlisted build output" 'build/bundle.ts' \
'export interface GateResultV1 { decision: string }' 'clean'

echo "range admission — the 0.x caret trap:"
assert_range '^0.1.1'  '0.10.0' 'stale'
assert_range '^0.9.0'  '0.10.0' 'stale'
assert_range '^0.10.0' '0.10.0' 'admits'
assert_range '^0.1.1'  '0.1.9'  'admits'

echo "range admission — tilde, caret, exact, open, and links:"
assert_range '~0.10.1'    '0.10.0' 'stale'
assert_range '~0.10.0'    '0.10.1' 'admits'
assert_range '~0.9.1'     '0.10.0' 'stale'
assert_range '^1.2.3'     '1.9.0'  'admits'
assert_range '^1.2.3'     '2.0.0'  'stale'
assert_range '^0.0.3'     '0.0.2'  'stale'
assert_range '^0.0.3'     '0.0.3'  'admits'
assert_range '>0.10.0'    '0.10.0' 'stale'
assert_range '>0.9.0'     '0.10.0' 'admits'
assert_range '0.10.0'     '0.10.0' 'admits'
assert_range '0.9.0'      '0.10.0' 'stale'
assert_range '>=0.9.0'    '0.10.0' 'admits'
assert_range '*'           '0.10.0' 'admits'
assert_range 'workspace:^' '0.10.0' 'admits'

echo "unknown ranges are surfaced, never assumed current:"
assert_range 'not-a-range'     '0.10.0' 'unknown'
assert_range '0.1.x || ^0.2.0' '0.10.0' 'unknown'

echo "exit-code policy:"
STALE_FIXTURE="$(mktemp -d)"
make_range_fixture "$STALE_FIXTURE" '^0.1.1'
assert_exit "advisory mode does not fail a stale finding" 0 \
  env -C "$STALE_FIXTURE" KERNEL_LATEST_VERSION="$KERNEL_VERSION" bash "$CHECK"
assert_exit "strict mode gates a stale range" 1 \
  env -C "$STALE_FIXTURE" KERNEL_LATEST_VERSION="$KERNEL_VERSION" bash "$CHECK" --strict
rm -rf "$STALE_FIXTURE"

CLEAN_FIXTURE="$(mktemp -d)"
make_range_fixture "$CLEAN_FIXTURE" '^0.10.0'
assert_exit "strict mode accepts a current range" 0 \
  env -C "$CLEAN_FIXTURE" KERNEL_LATEST_VERSION="$KERNEL_VERSION" bash "$CHECK" --strict
rm -rf "$CLEAN_FIXTURE"

SHADOW_FIXTURE="$(mktemp -d)"
mkdir -p "$SHADOW_FIXTURE/src"
printf '%s\n' 'export interface GateResultV1 { decision: string }' > "$SHADOW_FIXTURE/src/shadow.ts"
( cd "$SHADOW_FIXTURE" && git init -q . )
assert_exit "strict mode gates a local declaration" 1 \
  env -C "$SHADOW_FIXTURE" KERNEL_LATEST_VERSION="$KERNEL_VERSION" bash "$CHECK" --strict
rm -rf "$SHADOW_FIXTURE"

REFERENCE_FIXTURE="$(mktemp -d)"
mkdir -p "$REFERENCE_FIXTURE/src"
printf '%s\n' 'export { type GateResultV1 } from "@intentsolutions/core";' > "$REFERENCE_FIXTURE/src/index.ts"
( cd "$REFERENCE_FIXTURE" && git init -q . )
assert_exit "strict mode accepts a kernel reference" 0 \
  env -C "$REFERENCE_FIXTURE" KERNEL_LATEST_VERSION="$KERNEL_VERSION" bash "$CHECK" --strict
rm -rf "$REFERENCE_FIXTURE"

echo "unresolvable lookup withholds the clean claim:"
OFFLINE_FIXTURE="$(mktemp -d)"
make_range_fixture "$OFFLINE_FIXTURE" '^0.10.0'
OFFLINE_CHECK="$(mktemp)"
sed 's|npm view|false npm view|' "$CHECK" > "$OFFLINE_CHECK"
offline_out="$(cd "$OFFLINE_FIXTURE" && env -u KERNEL_LATEST_VERSION bash "$OFFLINE_CHECK" 2>&1)"
if grep -q 'SKIPPED the kernel-range check' <<<"$offline_out" \
  && grep -q 'Not reporting fully clean' <<<"$offline_out" \
  && ! grep -q 'every @intentsolutions/core range resolves' <<<"$offline_out"; then
  echo "  ok    lookup failure skips loudly"
  PASS=$((PASS + 1))
else
  echo "  FAIL  lookup failure did not withhold clean claim" >&2
  printf '        %s\n' "$offline_out" >&2
  FAIL=$((FAIL + 1))
fi
rm -rf "$OFFLINE_FIXTURE" "$OFFLINE_CHECK"

echo "──────────────────────────────────"
echo "kernel-shadow-check results: PASS=${PASS}  FAIL=${FAIL}"
[[ "$FAIL" -eq 0 ]] || exit 1
