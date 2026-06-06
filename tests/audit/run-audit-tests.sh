#!/usr/bin/env bash
# Golden test suite for `audit-harness audit` (testing-depth gate-runner, gate-result/v1).
#
# Verifies:
#   1. has-tests fixture --fast -> the `unit` gate is PASS; every row schema-valid
#   2. no-tests  fixture --fast -> the `unit` gate is ADVISORY(warn) gap, exit 0
#   3. no-tests  fixture --strict -> the `unit` gate is FAIL, exit 1
#   4. --fast leaves crap-score as ADVISORY(info, deep-only); --deep emits a crap row
#   5. kill-switch (AUDIT_HARNESS_DISABLE=1) -> empty [] row set, exit 0
#
# Run from the repository root:
#   bash tests/audit/run-audit-tests.sh
# Exit 0 = all green; exit 1 = at least one failure.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AUDIT="$ROOT/scripts/audit.py"
GR_SCHEMA="$ROOT/tests/fixtures/gate-result.schema.json"
FIX="$ROOT/tests/fixtures/audit"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

HAVE_JSONSCHEMA=0
if python3 -c "import jsonschema" 2>/dev/null; then HAVE_JSONSCHEMA=1; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

validate_rows() { # $1 = rows json file
  [ "$HAVE_JSONSCHEMA" -eq 1 ] || return 0
  python3 - "$GR_SCHEMA" "$1" <<'PY'
import json, sys, jsonschema
schema = json.load(open(sys.argv[1]))
rows = json.load(open(sys.argv[2]))
assert isinstance(rows, list), "audit output is not a JSON array"
for r in rows:
    jsonschema.validate(r, schema)
PY
}

assert_row() { # $1=file $2=gate_substr $3=want_result [$4=key $5=val]
  python3 - "$@" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
sub, want = sys.argv[2], sys.argv[3]
m = [r for r in rows if sub in r["gate_id"]]
assert m, f"no row matching gate '{sub}'"
r = m[0]
assert r["result"] == want, f"{sub}: result {r['result']!r} != {want!r}"
if len(sys.argv) > 5:
    k, v = sys.argv[4], sys.argv[5]
    assert str(r.get(k)) == v, f"{sub}: {k}={r.get(k)!r} != {v!r}"
PY
}

echo "audit golden suite (jsonschema=$HAVE_JSONSCHEMA)"

# ---- 1: has-tests --fast -> unit PASS + schema-valid ----
out="$TMP/has.json"
if python3 "$AUDIT" "$FIX/has-tests" >"$out" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 0 ] || fail "has-tests --fast: exit $ec (expected 0)"
if assert_row "$out" "ci:unit" PASS 2>"$TMP/e"; then pass "has-tests: unit -> PASS"
else fail "has-tests unit: $(cat "$TMP/e")"; fi
if validate_rows "$out" 2>"$TMP/e"; then pass "has-tests: rows validate against gate-result/v1"
else fail "has-tests row schema: $(cat "$TMP/e")"; fi

# ---- 4a: --fast leaves crap-score ADVISORY(info) deep-only ----
if assert_row "$out" "crap-score" ADVISORY advisory_severity info 2>"$TMP/e"; then
  pass "has-tests --fast: crap-score -> ADVISORY(info) deep-only"
else fail "crap-score fast: $(cat "$TMP/e")"; fi

# ---- 2: no-tests --fast -> unit gap ADVISORY(warn), exit 0 ----
out2="$TMP/no.json"
if python3 "$AUDIT" "$FIX/no-tests" >"$out2" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 0 ] || fail "no-tests --fast: exit $ec (expected 0, advisory-first)"
if assert_row "$out2" "ci:unit" ADVISORY advisory_severity warn 2>"$TMP/e"; then
  pass "no-tests: unit -> ADVISORY(warn) gap, exit 0"
else fail "no-tests unit gap: $(cat "$TMP/e")"; fi

# ---- 3: no-tests --strict -> unit FAIL, exit 1 ----
out3="$TMP/no-strict.json"
if python3 "$AUDIT" --strict "$FIX/no-tests" >"$out3" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "no-tests --strict: exit $ec (expected 1)"
if assert_row "$out3" "ci:unit" FAIL failure_mode "testing-depth:unit-gap" 2>"$TMP/e"; then
  pass "no-tests --strict: unit -> FAIL(testing-depth:unit-gap), exit 1"
else fail "no-tests strict: $(cat "$TMP/e")"; fi

# ---- 4b: --deep emits a crap-score row (PASS or INDETERMINATE per radon availability) ----
outd="$TMP/has-deep.json"
python3 "$AUDIT" --deep "$FIX/has-tests" >"$outd" 2>/dev/null
if python3 - "$outd" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
c = [r for r in rows if "crap-score" in r["gate_id"]]
assert c, "no crap-score row in --deep"
assert c[0]["metadata"].get("method") == "crap-static", "crap row not crap-static method"
assert "skipped" not in c[0].get("metadata", {}), "crap-score still skipped in --deep"
PY
then pass "has-tests --deep: crap-score row emitted (not skipped)"
else fail "crap-score deep row missing/wrong"; fi

# ---- 5: kill-switch ----
ks="$TMP/ks.json"
if AUDIT_HARNESS_DISABLE=1 python3 "$AUDIT" "$FIX/has-tests" >"$ks" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && [ "$(tr -d '[:space:]' <"$ks")" = "[]" ]; then
  pass "kill-switch: empty [] emitted, exit 0"
else fail "kill-switch: expected [] exit 0, got exit $ec / $(cat "$ks")"; fi

echo ""
echo "audit suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
