#!/usr/bin/env bash
# Golden test suite for `audit-harness scan` (security/hygiene/skill-quality, gate-result/v1).
#
# Deterministic paths are tested via pinned profiles and fake external scanners;
# shell-out + classify paths are smoke-checked for schema-valid, non-crashing output.
#
# Verifies:
#   1. hygiene-readme: README present -> PASS ; absent -> ADVISORY(warn) ; absent+--strict -> FAIL(exit1)
#   2. skill-behavioral (j-rig): verdict PASS consumed -> PASS ; verdict FAIL+--strict -> FAIL ; no verdict -> indeterminate
#   3. OSV: no input -> NOT_APPLICABLE; clean -> PASS; missing/crash/invalid ->
#      FAIL in fail-closed mode; production/unknown high -> FAIL; dev-only -> ADVISORY
#   4. every emitted row validates against gate-result/v1
#   5. kill-switch -> [] ; a real classify run emits only schema-valid rows and does not crash
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

check_row() {
  local label="$1"
  shift
  if assert_row "$@" 2>"$TMP/e"; then
    pass "$label"
  else
    fail "$(cat "$TMP/e")"
  fi
}

check_schema() {
  local label="$1"
  local file="$2"
  if validate_rows "$file" 2>"$TMP/e"; then
    pass "$label"
  else
    fail "schema: $(cat "$TMP/e")"
  fi
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
osv_profile() { cat <<'JSON'
{"schema_version":"audit-profile/v1","subject":{"name":"t","commit_sha":"0000000","root":"."},
 "classifier":"test","registry_hash":"sha256:0","timestamp":"2026-06-06T00:00:00Z",
 "classifications":[],"gates":[
   {"gate_id":"audit-harness:ci:cve-osv","dimension":"security","applicability":"required","enforcement":"advisory","tool":"osv-scanner"}
 ],"unresolved":[]}
JSON
}

echo "scan golden suite (jsonschema=$HAVE_JSONSCHEMA)"

# ---- 1: hygiene-readme ----
readme_profile > "$TMP/readme.profile.json"
o="$TMP/readme-present.json"
python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/readme.profile.json" >"$o" 2>/dev/null
check_row "hygiene-readme: README present -> PASS" "$o" "hygiene-readme" PASS
check_schema "readme-present rows schema-valid" "$o"

o="$TMP/readme-absent.json"
if python3 "$SCAN" "$FIX/no-readme" --profile "$TMP/readme.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 0 ] || fail "no-readme default: exit $ec (expected 0)"
check_row "hygiene-readme: absent -> ADVISORY(warn), exit 0" "$o" "hygiene-readme" ADVISORY advisory_severity warn

o="$TMP/readme-strict.json"
if python3 "$SCAN" --strict "$FIX/no-readme" --profile "$TMP/readme.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "no-readme --strict: exit $ec (expected 1)"
check_row "hygiene-readme: absent+--strict -> FAIL, exit 1" "$o" "hygiene-readme" FAIL failure_mode "hygiene:readme-missing"

# ---- 2: skill-behavioral j-rig consumption ----
jrig_profile > "$TMP/jrig.profile.json"
o="$TMP/jrig-pass.json"
python3 "$SCAN" "$FIX/jrig-pass" --profile "$TMP/jrig.profile.json" >"$o" 2>/dev/null
check_row "skill-behavioral: consumes j-rig PASS verdict -> PASS" "$o" "skill-behavioral" PASS

o="$TMP/jrig-fail.json"
if python3 "$SCAN" --strict "$FIX/jrig-fail" --profile "$TMP/jrig.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "jrig-fail --strict: exit $ec (expected 1)"
check_row "skill-behavioral: j-rig FAIL verdict+--strict -> FAIL" "$o" "skill-behavioral" FAIL failure_mode "skill-quality:jrig-fail"

o="$TMP/jrig-none.json"
python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/jrig.profile.json" >"$o" 2>/dev/null
if python3 - "$o" <<'PY'
import json, sys
r = [x for x in json.load(open(sys.argv[1])) if "skill-behavioral" in x["gate_id"]][0]
assert r["result"] == "ADVISORY" and r.get("metadata", {}).get("indeterminate") is True
PY
then
  pass "skill-behavioral: no verdict -> ADVISORY indeterminate (judgment not reimplemented)"
else
  fail "j-rig no-verdict path"
fi

# ---- explicit --jrig-verdict path ----
o="$TMP/jrig-explicit.json"
python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/jrig.profile.json" --jrig-verdict "$FIX/jrig-pass/.j-rig/verdict.json" >"$o" 2>/dev/null
check_row "skill-behavioral: --jrig-verdict PATH consumed -> PASS" "$o" "skill-behavioral" PASS

# ---- 3: OSV dependency contract ----
osv_profile > "$TMP/osv.profile.json"
mkdir -p "$TMP/no-deps" "$TMP/unlocked-deps" "$TMP/with-deps" "$TMP/fake-bin"
printf '%s\n' '{"name":"no-deps"}' > "$TMP/no-deps/package.json"
printf '%s\n' '{"name":"unlocked","dependencies":{"left-pad":"1.3.0"}}' > "$TMP/unlocked-deps/package.json"
printf '%s\n' '{"name":"with-deps","lockfileVersion":3,"packages":{}}' > "$TMP/with-deps/package-lock.json"

cat > "$TMP/fake-bin/osv-scanner" <<'SH'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
  [ "${FAKE_OSV_MODE:-}" != "version-error" ] || exit 2
  echo "osv-scanner version 2.5.1"
  exit 0
fi
[ "$*" = "scan source --format=json --verbosity=error --recursive ." ] || {
  echo "unexpected argv: $*" >&2
  exit 127
}
case "${FAKE_OSV_MODE:-clean}" in
  clean)
    printf '%s\n' '{"results":[{"source":{"path":"package-lock.json","type":"lockfile"},"packages":[]}]}'
    exit 0 ;;
  production-high)
    printf '%s\n' '{"results":[{"source":{"path":"package-lock.json","type":"lockfile"},"packages":[{"package":{"name":"prod-lib","version":"1.0.0","ecosystem":"npm"},"groups":[{"ids":["GHSA-prod-high"],"aliases":[],"max_severity":"8.2"}],"vulnerabilities":[{"id":"GHSA-prod-high"}]}]}]}'
    exit 1 ;;
  production-medium)
    printf '%s\n' '{"results":[{"source":{"path":"package-lock.json","type":"lockfile"},"packages":[{"package":{"name":"prod-lib","version":"1.0.0","ecosystem":"npm"},"groups":[{"ids":["GHSA-prod-medium"],"aliases":[],"max_severity":"5.5"}],"vulnerabilities":[{"id":"GHSA-prod-medium"}]}]}]}'
    exit 1 ;;
  development-critical)
    printf '%s\n' '{"results":[{"source":{"path":"package-lock.json","type":"lockfile"},"packages":[{"package":{"name":"dev-lib","version":"1.0.0","ecosystem":"npm"},"dependency_groups":["dev"],"groups":[{"ids":["GHSA-dev-critical"],"aliases":[],"max_severity":"9.8"}],"vulnerabilities":[{"id":"GHSA-dev-critical"}]}]}]}'
    exit 1 ;;
  unknown-high)
    printf '%s\n' '{"results":[{"source":{"path":"Cargo.lock","type":"lockfile"},"packages":[{"package":{"name":"rust-lib","version":"1.0.0","ecosystem":"crates.io"},"groups":[{"ids":["RUSTSEC-high"],"aliases":[],"max_severity":"7.5"}],"vulnerabilities":[{"id":"RUSTSEC-high"}]}]}]}'
    exit 1 ;;
  invalid-json)
    echo 'not-json'; exit 0 ;;
  result-error)
    printf '%s\n' '{"results":[]}'; exit 1 ;;
  no-packages)
    echo 'no packages' >&2; exit 128 ;;
  crash)
    echo 'scanner crashed' >&2; exit 127 ;;
esac
SH
chmod +x "$TMP/fake-bin/osv-scanner"

o="$TMP/osv-na.json"
PATH="/usr/bin:/bin" /usr/bin/python3 "$SCAN" --fail-closed "$TMP/no-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null
check_row "OSV: no dependency input -> NOT_APPLICABLE" "$o" "cve-osv" NOT_APPLICABLE
check_schema "OSV NOT_APPLICABLE row schema-valid" "$o"

o="$TMP/osv-unlocked.json"
if PATH="/usr/bin:/bin" /usr/bin/python3 "$SCAN" --fail-closed "$TMP/unlocked-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "OSV unlocked dependency graph: exit $ec (expected 1)"
check_row "OSV: declared dependencies without lockfile -> FAIL closed" "$o" "cve-osv" FAIL failure_mode "scan:osv-lockfile-missing"

o="$TMP/osv-missing-advisory.json"
PATH="/usr/bin:/bin" /usr/bin/python3 "$SCAN" "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null
check_row "OSV: missing scanner stays advisory by default" "$o" "cve-osv" ADVISORY

o="$TMP/osv-missing-closed.json"
if PATH="/usr/bin:/bin" /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "OSV missing fail-closed: exit $ec (expected 1)"
check_row "OSV: missing scanner + input -> FAIL closed" "$o" "cve-osv" FAIL failure_mode "scan:osv-scanner-unavailable"

o="$TMP/osv-clean.json"
PATH="$TMP/fake-bin:/usr/bin:/bin" FAKE_OSV_MODE=clean /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null
check_row "OSV: measured clean input -> PASS" "$o" "cve-osv" PASS
if python3 - "$o" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))[0]
m = r["metadata"]
assert m["tool_version"] == "osv-scanner version 2.5.1"
assert m["supported_inputs"] == ["package-lock.json"]
assert r["input_hash"] != "sha256:" + "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
PY
then
  pass "OSV: evidence records version, input hash, and scanned paths"
else
  fail "OSV evidence metadata"
fi

o="$TMP/osv-prod-high.json"
if PATH="$TMP/fake-bin:/usr/bin:/bin" FAKE_OSV_MODE=production-high /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "OSV production high: exit $ec (expected 1)"
check_row "OSV: production HIGH finding -> FAIL" "$o" "cve-osv" FAIL failure_mode "scan:osv-scanner-policy-findings"

o="$TMP/osv-prod-medium.json"
PATH="$TMP/fake-bin:/usr/bin:/bin" FAKE_OSV_MODE=production-medium /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null
check_row "OSV: production MEDIUM below HIGH threshold -> ADVISORY" "$o" "cve-osv" ADVISORY advisory_severity warn

o="$TMP/osv-dev.json"
PATH="$TMP/fake-bin:/usr/bin:/bin" FAKE_OSV_MODE=development-critical /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null
check_row "OSV: proven dev-only CRITICAL -> triage ADVISORY" "$o" "cve-osv" ADVISORY advisory_severity error

o="$TMP/osv-unknown.json"
if PATH="$TMP/fake-bin:/usr/bin:/bin" FAKE_OSV_MODE=unknown-high /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
[ "$ec" -eq 1 ] || fail "OSV unknown exposure: exit $ec (expected 1)"
check_row "OSV: unknown production exposure fails conservatively" "$o" "cve-osv" FAIL

for mode in crash no-packages invalid-json result-error version-error; do
  o="$TMP/osv-$mode.json"
  if PATH="$TMP/fake-bin:/usr/bin:/bin" FAKE_OSV_MODE="$mode" /usr/bin/python3 "$SCAN" --fail-closed "$TMP/with-deps" --profile "$TMP/osv.profile.json" >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
  [ "$ec" -eq 1 ] || fail "OSV $mode: exit $ec (expected 1)"
  check_row "OSV: $mode -> FAIL closed" "$o" "cve-osv" FAIL
  validate_rows "$o" 2>"$TMP/e" || fail "OSV $mode schema: $(cat "$TMP/e")"
done

# ---- 4: kill-switch ----
ks="$TMP/ks.json"
if AUDIT_HARNESS_DISABLE=1 python3 "$SCAN" "$FIX/with-readme" --profile "$TMP/readme.profile.json" >"$ks" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && [ "$(tr -d '[:space:]' <"$ks")" = "[]" ]; then
  pass "kill-switch: empty [] exit 0"
else
  fail "kill-switch: exit $ec / $(cat "$ks")"
fi

# ---- 5: real classify run emits only schema-valid rows, never crashes (shell-out paths) ----
o="$TMP/real.json"
python3 "$SCAN" "$FIX/with-readme" >"$o" 2>/dev/null
if validate_rows "$o" 2>"$TMP/e"; then pass "real classify run: all rows schema-valid (shell-out paths graceful)"
else fail "real run schema: $(cat "$TMP/e")"; fi

echo ""
echo "scan suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
