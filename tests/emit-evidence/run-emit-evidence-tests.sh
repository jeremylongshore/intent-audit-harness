#!/usr/bin/env bash
# emit-evidence bundle-assembly contract suite.
#
# Pins the two consumer-facing promises of scripts/emit-evidence.sh that the
# rollout gate depends on:
#
#   1. --append-to PATH builds the plain-array Evidence Bundle that
#      intent-rollout-gate's bundle-path consumes: create-on-first-row, append,
#      refuse a duplicate row id, refuse an invalid bundle or row, refuse flag
#      conflicts, and leave the bundle byte-identical on every refusal.
#   2. --output is the documented file flag; --out still works but warns.
#
# Deterministic + offline: every case runs under mktemp, no network, no cosign.
# Requires python3 jsonschema: every appended row is cross-checked against the
# kernel gate-result/v1 fixture (self-contained, local $refs only), and the
# shipped snapshot must be byte-identical to that fixture.
#
# Run from anywhere:  bash tests/emit-evidence/run-emit-evidence-tests.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EMIT="$ROOT/scripts/emit-evidence.sh"
SCHEMA="$ROOT/tests/fixtures/gate-result-v1.schema.json"
SNAPSHOT="$ROOT/schemas/kernel-snapshot/gate-result-v1.schema.json"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS+1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL+1)); }
# check "description" cmd... — pass when the command succeeds.
check() { local d="$1"; shift; if "$@"; then pass "$d"; else fail "$d"; fi; }
assert_eq() { if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3 (expected '$1', got '$2')"; fi; }

H64() { printf '%064d' 0 | tr 0 "$1"; }
# A gate's minimal --json envelope. emit-evidence.sh synthesizes the rest of the
# kernel body (gate_name from gate_id, gate_version, gate_decision, gate_reasons,
# coverage, policy_ref, evaluated_at, runner, commit_sha) before appending, which
# is why the appended predicates validate against the 12-field kernel schema.
envelope() { # gate_id result [extra-json-fields]
  printf '{"gate_id":"%s","result":"%s","input_hash":"sha256:%s","policy_hash":"sha256:%s"%s}' \
    "$1" "$2" "$(H64 a)" "$(H64 b)" "${3:-}"
}
emit() { bash "$EMIT" --runner-version "audit-harness@9.9.9" --commit-sha "abcdef1" "$@"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

echo "== --append-to: build the bundle the rollout gate consumes =="

B="$WORK/out/bundle.json"
ec=0; envelope "audit-harness:ci:escape-scan" PASS | emit --append-to "$B" 2>/dev/null || ec=$?
assert_eq "0" "$ec" "first append exits 0"
assert_eq "1" "$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$B" 2>/dev/null)" \
  "first append creates a one-row JSON array (and its parent dir)"

ec=0; envelope "audit-harness:ci:arch" FAIL ',"failure_mode":"layer-violation"' | emit --append-to "$B" 2>/dev/null || ec=$?
assert_eq "0" "$ec" "second append (different row id) exits 0"
shape=$(python3 - "$B" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
ids = [r["predicate"]["gate_id"] for r in rows]
ok = (ids == ["audit-harness:ci:escape-scan", "audit-harness:ci:arch"]
      and all(r["_type"] == "https://in-toto.io/Statement/v1" for r in rows)
      and all(r["predicateType"] == "https://evals.intentsolutions.io/gate-result/v1" for r in rows)
      and all(r["subject"][0]["name"] == r["predicate"]["gate_id"] for r in rows)
      and rows[1]["predicate"]["gate_decision"] == "fail")
print("ok" if ok else f"bad {ids}")
PY
)
assert_eq "ok" "$shape" "bundle holds both Statements in append order, subject == gate_id"

# The cross-check is mandatory: a missing fixture or jsonschema is a FAIL, never
# a skip, so the snapshot-driven validator cannot drift from the kernel quietly.
check "kernel fixture is present" test -f "$SCHEMA"
check "shipped kernel snapshot is byte-identical to the kernel fixture" cmp -s "$SNAPSHOT" "$SCHEMA"
kernel=$(python3 - "$B" "$SCHEMA" 2>&1 <<'PY'
import json, sys
import jsonschema
rows = json.load(open(sys.argv[1]))
schema = json.load(open(sys.argv[2]))
for r in rows:
    jsonschema.validate(r["predicate"], schema)
print("ok")
PY
)
assert_eq "ok" "$kernel" "every appended predicate validates against the kernel gate-result/v1 schema (jsonschema)"

before=$(sha "$B")
ec=0; err=$(envelope "audit-harness:ci:escape-scan" PASS | emit --append-to "$B" 2>&1 >/dev/null) || ec=$?
assert_eq "1" "$ec" "duplicate row id is refused with exit 1"
assert_eq "$before" "$(sha "$B")" "refused duplicate leaves the bundle byte-identical"
check "duplicate refusal names the row id" \
  grep -q "already holds a row with id audit-harness:ci:escape-scan" <<<"$err"

ec=0; envelope "not a subject name" PASS | emit --append-to "$B" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "a row whose gate_id breaks the kernel subject pattern is refused"
assert_eq "$before" "$(sha "$B")" "refused invalid row leaves the bundle byte-identical"

ec=0; envelope "audit-harness:ci:bias" ADVISORY | emit --append-to "$B" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "an advisory row without advisory_severity is refused (kernel if/then rule)"

ec=0; envelope "audit-harness:ci:bias" ADVISORY ',"advisory_severity":"warn"' | emit --append-to "$B" >/dev/null 2>&1 || ec=$?
assert_eq "0" "$ec" "an advisory row with advisory_severity is accepted"

echo "== --append-to: refuse a bundle that is not the consumable array =="

C="$WORK/container.json"
printf '{"bundle_format":"json-array","rows":[]}\n' > "$C"
cb=$(sha "$C")
ec=0; envelope "audit-harness:ci:arch" PASS | emit --append-to "$C" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "v1 container form is refused (append writes the v2 plain array only)"
assert_eq "$cb" "$(sha "$C")" "refused container is untouched"

G="$WORK/garbage.json"
printf '[{"_type":"https://in-toto.io/Statement/v1"}]\n' > "$G"
ec=0; envelope "audit-harness:ci:arch" PASS | emit --append-to "$G" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "a bundle holding an invalid existing row is refused"

N="$WORK/notjson.json"
printf 'not json' > "$N"
ec=0; envelope "audit-harness:ci:arch" PASS | emit --append-to "$N" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "a bundle that is not JSON is refused"

echo "== --append-to: flag conflicts and missing values =="

ec=0; envelope "audit-harness:ci:arch" PASS | emit --append-to "$WORK/x.json" --output "$WORK/y.json" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "--append-to with --output is refused"
ec=0; envelope "audit-harness:ci:arch" PASS | emit --append-to "$WORK/x.json" --sign >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "--append-to with --sign is refused (a DSSE envelope is not a bundle row)"
check "conflicting flags write nothing" test ! -e "$WORK/x.json"
ec=0; envelope "audit-harness:ci:arch" PASS | emit --append-to >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "--append-to without a PATH exits 1 (frozen malformed-input code)"
ec=0; bash "$EMIT" --input >/dev/null 2>&1 </dev/null || ec=$?
assert_eq "1" "$ec" "--input without a PATH exits 1 (no unbound-variable abort)"

echo "== --append-to: the validator refuses a snapshot it cannot interpret =="

# Copy the package layout, plant an unimplemented keyword in the snapshot, and
# confirm the append fails closed instead of under-validating.
PKG="$WORK/pkg"
mkdir -p "$PKG/scripts" "$PKG/schemas/kernel-snapshot"
cp "$ROOT/scripts/emit-evidence.sh" "$ROOT/scripts/bundle-append.py" "$PKG/scripts/"
python3 - "$SNAPSHOT" "$PKG/schemas/kernel-snapshot/gate-result-v1.schema.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["properties"]["gate_name"]["maxLength"] = 64
json.dump(s, open(sys.argv[2], "w"))
PY
ec=0; err=$(envelope "audit-harness:ci:arch" PASS | bash "$PKG/scripts/emit-evidence.sh" --runner-version "audit-harness@9.9.9" --commit-sha "abcdef1" --append-to "$WORK/planted.json" 2>&1 >/dev/null) || ec=$?
assert_eq "1" "$ec" "an unimplemented schema keyword makes --append-to refuse (fail closed)"
check "the refusal names the unsupported keyword" grep -q "maxLength" <<<"$err"
check "nothing was written" test ! -e "$WORK/planted.json"
python3 - "$SNAPSHOT" "$PKG/schemas/kernel-snapshot/gate-result-v1.schema.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["properties"]["gate_name"]["format"] = "hostname"
json.dump(s, open(sys.argv[2], "w"))
PY
ec=0; envelope "audit-harness:ci:arch" PASS | bash "$PKG/scripts/emit-evidence.sh" --runner-version "audit-harness@9.9.9" --commit-sha "abcdef1" --append-to "$WORK/planted.json" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "an unimplemented format makes --append-to refuse (fail closed)"

echo "== --output is documented; --out is a deprecated alias =="

ec=0; err=$(envelope "audit-harness:ci:arch" PASS | emit --output "$WORK/o1.json" 2>&1 >/dev/null) || ec=$?
assert_eq "0" "$ec" "--output writes the Statement"
if grep -q deprecated <<<"$err"; then fail "--output warned: $err"; else pass "--output does not warn"; fi

ec=0; err=$(envelope "audit-harness:ci:arch" PASS | emit --out "$WORK/o2.json" 2>&1 >/dev/null) || ec=$?
assert_eq "0" "$ec" "--out still writes the Statement"
check "--out warns on stderr" grep -q -- "--out is deprecated; use --output" <<<"$err"
same=$(python3 - "$WORK/o1.json" "$WORK/o2.json" <<'PY'
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
for d in (a, b):
    d["predicate"].pop("evaluated_at")
print("ok" if a == b else "bad")
PY
)
assert_eq "ok" "$same" "--out and --output produce the same Statement"

check "--help documents --append-to" grep -q -- "--append-to PATH" <<<"$(bash "$EMIT" --help)"

echo ""
echo "emit-evidence contract suite: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
