#!/usr/bin/env bash
# Golden test suite for `audit-harness scan` (security/hygiene/skill-quality, gate-result/v1).
#
# Deterministic paths are tested via pinned profiles (so shell-out tool availability
# never makes the suite flaky); shell-out + classify paths are smoke-checked for
# schema-valid, non-crashing output.
#
# Verifies:
#   1. hygiene-readme: README present -> PASS ; absent -> ADVISORY(warn) ; absent+--strict -> FAIL(exit1)
#   2. skill-behavioral (j-rig): verdict PASS consumed -> PASS ; verdict FAIL+--strict -> FAIL ; no verdict -> indeterminate
#   3. every emitted row validates against gate-result/v1
#   4. kill-switch -> [] ; a real classify run emits only schema-valid rows and does not crash
#
# Run from repo root:  bash tests/scan/run-scan-tests.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCAN="$ROOT/scripts/scan.py"
GR_SCHEMA="$ROOT/tests/fixtures/gate-result.schema.json"
FIX="$ROOT/tests/fixtures/scan"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

HAVE_JSONSCHEMA=0
if python3 -c "import jsonschema" 2>/dev/null; then HAVE_JSONSCHEMA=1; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

validate_rows() {
  [ "$HAVE_JSONSCHEMA" -eq 1 ] || return 0
  python3 - "$GR_SCHEMA" "$1" <<'PY'
import json, sys, jsonschema
schema = json.load(open(sys.argv[1]))
rows = json.load(open(sys.argv[2]))
assert isinstance(rows, list), "scan output is not a JSON array"
for r in rows:
    jsonschema.validate(r, schema)
PY
}

assert_row() {
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

# pinned profiles isolate one gate so shell-out availability can't make the suite flaky
readme_profile() { cat <<'JSON'
{"schema_version":"audit-profile/v1","subject":{"name":"t","commit_sha":"0000000","root":"."},
 "classifier":"test","registry_hash":"sha256:0","timestamp":"2026-06-06T00:00:00Z",
 "classifications":[],"gates":[
   {"gate_id":"audit-harness:local:hygiene-readme","dimension":"hygiene","applicability":"recommended","enforcement":"advisory"}
 ],"unresolved":[]}
JSON
}
jrig_profile() { cat <<'JSON'
{"schema_version":"audit-profile/v1","subject":{"name":"t","commit_sha":"0000000","root":"."},
 "classifier":"test","registry_hash":"sha256:0","timestamp":"2026-06-06T00:00:00Z",
 "classifications":[],"gates":[
   {"gate_id":"audit-harness:server:skill-behavioral","dimension":"skill-quality","applicability":"recommended","enforcement":"advisory","tool":"j-rig"}
 ],"unresolved":[]}
JSON
}

echo "scan golden suite (jsonschema=$HAVE_JSONSCHEMA)"

# ---- 1: hygiene-readme ----
readme_profile > "$TMP/readme.profile.json"
o="$TMP/readme-present.json"
python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/readme.profile.json" >"$o" 2>/dev/null
assert_row "$o" "hygiene-readme" PASS 2>"$TMP/e" && pass "hygiene-readme: README present -> PASS" || fail "$(cat "$TMP/e")"
validate_rows "$o" 2>"$TMP/e" && pass "readme-present rows schema-valid" || fail "schema: $(cat "$TMP/e")"

o="$TMP/readme-absent.json"
if python3 "$SCAN" "$FIX/no-readme" --profile "$TMP/readme.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 0 ] || fail "no-readme default: exit $ec (expected 0)"
assert_row "$o" "hygiene-readme" ADVISORY advisory_severity warn 2>"$TMP/e" && pass "hygiene-readme: absent -> ADVISORY(warn), exit 0" || fail "$(cat "$TMP/e")"

o="$TMP/readme-strict.json"
if python3 "$SCAN" --strict "$FIX/no-readme" --profile "$TMP/readme.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "no-readme --strict: exit $ec (expected 1)"
assert_row "$o" "hygiene-readme" FAIL failure_mode "hygiene:readme-missing" 2>"$TMP/e" && pass "hygiene-readme: absent+--strict -> FAIL, exit 1" || fail "$(cat "$TMP/e")"

# ---- 2: skill-behavioral j-rig consumption ----
jrig_profile > "$TMP/jrig.profile.json"
o="$TMP/jrig-pass.json"
python3 "$SCAN" "$FIX/jrig-pass" --profile "$TMP/jrig.profile.json" >"$o" 2>/dev/null
assert_row "$o" "skill-behavioral" PASS 2>"$TMP/e" && pass "skill-behavioral: consumes j-rig PASS verdict -> PASS" || fail "$(cat "$TMP/e")"

o="$TMP/jrig-fail.json"
if python3 "$SCAN" --strict "$FIX/jrig-fail" --profile "$TMP/jrig.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "jrig-fail --strict: exit $ec (expected 1)"
assert_row "$o" "skill-behavioral" FAIL failure_mode "skill-quality:jrig-fail" 2>"$TMP/e" && pass "skill-behavioral: j-rig FAIL verdict+--strict -> FAIL" || fail "$(cat "$TMP/e")"

o="$TMP/jrig-none.json"
python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/jrig.profile.json" >"$o" 2>/dev/null
python3 - "$o" <<'PY' && pass "skill-behavioral: no verdict -> ADVISORY indeterminate (judgment not reimplemented)" || fail "j-rig no-verdict path"
import json, sys
r = [x for x in json.load(open(sys.argv[1])) if "skill-behavioral" in x["gate_id"]][0]
assert r["result"] == "ADVISORY" and r.get("metadata", {}).get("indeterminate") is True
PY

# ---- explicit --jrig-verdict path ----
o="$TMP/jrig-explicit.json"
python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/jrig.profile.json" --jrig-verdict "$FIX/jrig-pass/.j-rig/verdict.json" >"$o" 2>/dev/null
assert_row "$o" "skill-behavioral" PASS 2>"$TMP/e" && pass "skill-behavioral: --jrig-verdict PATH consumed -> PASS" || fail "$(cat "$TMP/e")"

# ---- 3: kill-switch ----
ks="$TMP/ks.json"
if AUDIT_HARNESS_DISABLE=1 python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/readme.profile.json" >"$ks" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 0 ] && [ "$(tr -d '[:space:]' <"$ks")" = "[]" ] && pass "kill-switch: empty [] exit 0" || fail "kill-switch: exit $ec / $(cat "$ks")"

# ---- 4: real classify run emits only schema-valid rows, never crashes (shell-out paths) ----
o="$TMP/real.json"
python3 "$SCAN" "$FIX/with-readme" >"$o" 2>/dev/null
if validate_rows "$o" 2>"$TMP/e"; then pass "real classify run: all rows schema-valid (shell-out paths graceful)"
else fail "real run schema: $(cat "$TMP/e")"; fi

echo ""
echo "scan suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
