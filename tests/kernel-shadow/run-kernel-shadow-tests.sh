#!/usr/bin/env bash
# tests/kernel-shadow/run-kernel-shadow-tests.sh
#
# Contract tests for scripts/kernel-shadow-check.sh.
#
# The detector shipped with NO tests, and the gap showed: its TS/Python class
# matched on the KEYWORD (`type EvidenceBundle`) rather than on declaration
# syntax, so it flagged three j-rig-skill-binary-eval files whose only offence
# was re-exporting the kernel's own types — the exact single-source-of-truth
# pattern the detector exists to encourage. These tests pin the distinction:
# what a definition looks like, what a re-export looks like, and that only the
# first is a shadow.
#
# Every fixture is a throwaway git repo built from literal source text, so the
# suite is deterministic and offline — no npm lookup, no network, no dependence
# on what any sibling repo happens to contain today.
#
# Usage: bash tests/kernel-shadow/run-kernel-shadow-tests.sh
# Exit:  0 all pass, 1 any failure

# shellcheck disable=SC2016
#   Every `$` in this file is inside a JSON-Schema fixture (`"$id"`) or a TS
#   fixture. Single quotes are load-bearing: the fixture text must reach the
#   detector byte-for-byte, un-expanded. There is no shell expansion intended
#   anywhere in this file.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CHECK="${REPO_ROOT}/scripts/kernel-shadow-check.sh"

PASS=0
FAIL=0

# Build a throwaway repo containing one file at REL_PATH with CONTENT.
# Echoes the temp dir.
make_fixture() {
  local rel="$1" content="$2" dir
  dir="$(mktemp -d)"
  mkdir -p "$dir/$(dirname "$rel")"
  printf '%s\n' "$content" > "$dir/$rel"
  ( cd "$dir" && git init -q . )
  echo "$dir"
}

# assert_source DESC REL_PATH CONTENT EXPECTED("shadow"|"clean")
assert_source() {
  local desc="$1" rel="$2" content="$3" expected="$4"
  local dir out verdict
  dir="$(make_fixture "$rel" "$content")"
  out="$( cd "$dir" && bash "$CHECK" 2>&1 )"
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

echo "referencing the kernel is NOT a shadow (the false positives that shipped):"
# The three shapes that flagged j-rig. Each names a kernel-owned type in order to
# FORWARD it; none of them declares anything.
assert_source "multi-line re-export block from the kernel" 'src/index.ts' \
'export {
  EvidenceBundleSchema,
  type EvidenceBundle,
  type GateResultV1,
  type EvidenceBundlePayload,
} from "@intentsolutions/core/validators/v1/evidence-bundle.js";' 'clean'

assert_source "single-line re-export from the kernel" 'src/reexport.ts' \
'export { type GateResultV1 } from "@intentsolutions/core";' 'clean'

assert_source "inline type import" 'src/consume.ts' \
'import { type EvidenceBundle, GateResultV1Schema } from "@intentsolutions/core";' 'clean'

assert_source "plain type-only import" 'src/consume2.ts' \
'import type { GateResultV1 } from "@intentsolutions/core";' 'clean'

assert_source "the identifier in a comment or a string" 'src/prose.ts' \
'// this module emits a GateResultV1 row per gate
const uri = "https://evals.intentsolutions.io/gate-result/v1";' 'clean'

echo "re-declaring the kernel contract IS a shadow (true positives kept):"
assert_source "local interface" 'src/shadow.ts' \
'export interface GateResultV1 { decision: string }' 'shadow'

assert_source "local generic interface" 'src/shadow-generic.ts' \
'interface EvidenceBundle<T> { rows: T[] }' 'shadow'

assert_source "interface extending another" 'src/shadow-extends.ts' \
'export interface EvidenceBundlePayload extends Base { rows: unknown[] }' 'shadow'

assert_source "local class" 'src/shadow-class.ts' \
'export class EvidenceBundle { constructor(public rows: unknown[]) {} }' 'shadow'

assert_source "class implementing an interface" 'src/shadow-impl.ts' \
'class GateResultV1 implements Predicate { decision = "PASS" }' 'shadow'

assert_source "declare-d ambient interface" 'src/shadow-declare.d.ts' \
'declare interface GateResultV1 { decision: string }' 'shadow'

assert_source "generic type alias" 'src/alias-generic.ts' \
'export type EvidenceBundlePayload<T> = { rows: T[] };' 'shadow'

echo "deriving FROM the kernel is NOT a shadow — but the exemption is narrow:"
# A z.infer over a kernel-imported schema has no independent shape. It is defined
# BY the kernel and changes when the kernel changes, so it cannot drift — which is
# the whole harm this detector guards against. This is the shape j-rig carries at
# packages/core/src/schemas/evidence-bundle.ts:192.
assert_source "z.infer over a kernel-imported schema" 'src/derive.ts' \
'import { EvidenceBundlePayloadSchema } from "@intentsolutions/core/validators/v1/evidence-statement";
export type EvidenceBundle = z.infer<typeof EvidenceBundlePayloadSchema>;' 'clean'

assert_source "z.infer over a schema pulled in by a multi-line re-export" 'src/derive-multiline.ts' \
'export {
  EvidenceBundlePayloadSchema,
  type EvidenceBundlePayload,
} from "@intentsolutions/core/validators/v1/evidence-statement";
export type EvidenceBundle = z.infer<typeof EvidenceBundlePayloadSchema>;' 'clean'

assert_source "bare alias to a kernel-imported type" 'src/derive-bare.ts' \
'import type { GateResultV1 as KernelGateResult } from "@intentsolutions/core";
export type GateResultV1 = KernelGateResult;' 'clean'

# The three cases the exemption must NOT swallow.
assert_source "z.infer over a LOCAL schema — not kernel-derived" 'src/derive-local.ts' \
'const MyOwnSchema = z.object({ decision: z.string() });
export type GateResultV1 = z.infer<typeof MyOwnSchema>;' 'shadow'

assert_source "structural literal that merely mentions a kernel symbol" 'src/derive-structural.ts' \
'import { EvidenceBundlePayloadSchema } from "@intentsolutions/core";
export type EvidenceBundle = { rows: EvidenceBundlePayloadSchema[] };' 'shadow'

assert_source "union that mentions a kernel symbol" 'src/derive-union.ts' \
'import { GateResultV1Schema } from "@intentsolutions/core";
export type GateResultV1 = z.infer<typeof GateResultV1Schema> | { legacy: true };' 'shadow'

# A file with BOTH a derivation and a real declaration must still report — the
# per-line triage must not let one exempt line clear the whole file.
assert_source "exempt derivation alongside a real declaration" 'src/mixed.ts' \
'import { EvidenceBundlePayloadSchema } from "@intentsolutions/core";
export type EvidenceBundlePayload = z.infer<typeof EvidenceBundlePayloadSchema>;
export interface GateResultV1 { decision: string }' 'shadow'

echo "python declaration forms:"
assert_source "pydantic model" 'models.py' \
'class EvidenceBundlePayload(BaseModel):
    rows: list[dict]' 'shadow'

assert_source "bare class" 'models_bare.py' \
'class GateResultV1:
    pass' 'shadow'

assert_source "python import of the kernel mirror" 'consume.py' \
'from intent_eval_core.v1 import GateResultV1, EvidenceBundle' 'clean'

echo "the JSON Schema \$id class is unchanged:"
assert_source "schema claiming a kernel-owned canonical id" 'schemas/mine.json' \
'{"$id": "https://evals.intentsolutions.io/gate-result/v1/schema.json"}' 'shadow'

assert_source "schema under the harness own conform namespace" 'schemas/own.json' \
'{"$id": "https://evals.intentsolutions.io/conform/v1/skill.json"}' 'clean'

# The ratified discoverability stub (Blueprint B § 7.0, DR-018 § 6.4 α-minus):
# it claims the kernel id in order to $ref the kernel. The lab CI gate
# schema-drift.yml allowlists this same marker.
assert_source "redirect stub carrying x-redirect" 'specs/gate-result.schema.json' \
'{
  "$id": "https://evals.intentsolutions.io/gate-result/v1.schema.json",
  "$ref": "https://raw.githubusercontent.com/jeremylongshore/intent-eval-core/main/schemas/v1/gate-result.schema.json",
  "x-redirect": { "kernel-npm": "@intentsolutions/core/schemas/v1/gate-result.schema.json" }
}' 'clean'

echo "allowlisted paths stay allowlisted:"
assert_source "tests/fixtures — a deliberate offline pin" 'tests/fixtures/frozen.ts' \
'export interface GateResultV1 { decision: string }' 'clean'

assert_source "ci/ — the CI-only emitter" 'ci/emit.ts' \
'export interface GateResultV1 { decision: string }' 'clean'

assert_source "schemas/conform/ — the harness own structural floor" 'schemas/conform/v1/x.json' \
'{"$id": "https://evals.intentsolutions.io/gate-result/v1/schema.json"}' 'clean'

assert_source "dist/ — compiler output restating checked source" 'packages/core/dist/index.d.ts' \
'type EvidenceBundle = z.infer<typeof EvidenceBundlePayloadSchema>;' 'clean'

assert_source "build/ — compiler output restating checked source" 'build/bundle.ts' \
'export interface GateResultV1 { decision: string }' 'clean'

echo "exit codes:"
SHADOW_FIXTURE="$(make_fixture 'src/shadow.ts' 'export interface GateResultV1 { decision: string }')"
assert_exit "advisory mode does not fail the build" 0 \
  env -C "$SHADOW_FIXTURE" bash "$CHECK"
assert_exit "--strict gates a re-declared kernel type" 1 \
  env -C "$SHADOW_FIXTURE" bash "$CHECK" --strict
rm -rf "$SHADOW_FIXTURE"

CLEAN_FIXTURE="$(make_fixture 'src/index.ts' 'export { type GateResultV1 } from "@intentsolutions/core";')"
assert_exit "--strict passes a repo that only references the kernel" 0 \
  env -C "$CLEAN_FIXTURE" bash "$CHECK" --strict
rm -rf "$CLEAN_FIXTURE"

echo "──────────────────────────────────"
echo "kernel-shadow-check results: PASS=${PASS}  FAIL=${FAIL}"
[[ "$FAIL" -eq 0 ]] || exit 1
