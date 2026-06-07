#!/usr/bin/env bash
# Golden suite for `audit-harness currency` (advisory upstream-currency report).
#
# Verifies:
#   1. A pin past its window -> status=stale; within window -> current; bad date -> unknown
#   2. currency has NO exit-code authority — exit 0 even when everything is stale
#   3. --json report shape (advisory:true, stale_count) is well-formed
#   4. the shipped pins relation (schemas/currency/pins.v1.json) parses + reports
#
# Run from repo root:  bash tests/currency/run-currency-tests.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CUR="$ROOT/scripts/currency.py"
FIXPINS="$ROOT/tests/fixtures/currency/test-pins.json"
SHIPPED="$ROOT/schemas/currency/pins.v1.json"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "currency golden suite"

# ---- 1+2+3: deterministic report over the fixture, fixed today ----
o="$TMP/report.json"
if python3 "$CUR" --pins "$FIXPINS" --today 2026-06-06 --json >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -ne 0 ]; then fail "currency exited $ec (must be 0 — advisory, no exit authority)"; fi

if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("advisory") is True, "report must be marked advisory"
by = {p["identity"]: p for p in d["pins"]}
assert by["old-one"]["status"] == "stale", f"old-one: {by['old-one']['status']}"
assert by["fresh-one"]["status"] == "current", f"fresh-one: {by['fresh-one']['status']}"
assert by["bad-date"]["status"] == "unknown-checked_at", f"bad-date: {by['bad-date']['status']}"
assert d["stale_count"] >= 1, "stale_count should count old-one"
PY
then pass "stale/current/unknown classified correctly + advisory:true + stale_count"
else fail "report classification wrong"; fi

# explicit exit-code-authority check: everything stale -> still exit 0
if python3 "$CUR" --pins "$FIXPINS" --today 2099-06-06 >/dev/null 2>&1; then
  pass "no exit-code authority: exit 0 even when all pins are stale"
else fail "currency returned non-zero — it must never gate a build"; fi

# ---- 4: the shipped pin relation parses + reports + exits 0 ----
if python3 "$CUR" --pins "$SHIPPED" --json >"$TMP/shipped.json" 2>/dev/null \
   && python3 -c "import json,sys; d=json.load(open('$TMP/shipped.json')); assert d['report']=='currency/v1'; assert len(d['pins'])>=4"; then
  pass "shipped pins.v1.json parses + reports >=4 upstream identities"
else fail "shipped pins relation did not report cleanly"; fi

echo ""
echo "currency suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
