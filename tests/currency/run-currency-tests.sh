#!/usr/bin/env bash
# Golden suite for `audit-harness currency` (advisory poll-freshness report).
#
# Verifies:
#   1. A pin past its poll-freshness SLA -> status=stale; within SLA -> current;
#      bad date -> unknown
#   2. currency has NO exit-code authority — exit 0 even when everything is stale
#      (the SLA gates nothing but human attention)
#   3. --json report shape (advisory:true, stale_count, by_class) is well-formed
#   4. class-based SLA resolution: explicit per-pin window > class SLA > default,
#      with exact fresh/stale boundary semantics (age == SLA -> current; age > SLA -> stale)
#   5. the terminology rename: report says "poll-freshness SLA", never "bounded-staleness"
#   6. the shipped pins relation (schemas/currency/pins.v1.json) parses + reports and
#      carries one pin per lab-registry surface (16) + the 3 internal-contract pins
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

# ---- 4: class SLA resolution + fresh/stale boundary cases (today=2026-06-06) ----
if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
by = {p["identity"]: p for p in d["pins"]}
# class SLA inherited when pin carries no explicit window
assert by["spec-on-boundary"]["window_days"] == 7,  "spec-page class SLA must resolve to 7"
assert by["feed-on-boundary"]["window_days"] == 3,  "release-feed class SLA must resolve to 3"
# boundary: age == SLA -> current; age == SLA+1 -> stale
assert by["spec-on-boundary"]["age_days"] == 7 and by["spec-on-boundary"]["status"] == "current", \
    f"spec-on-boundary: {by['spec-on-boundary']}"
assert by["spec-just-stale"]["age_days"] == 8 and by["spec-just-stale"]["status"] == "stale", \
    f"spec-just-stale: {by['spec-just-stale']}"
assert by["feed-on-boundary"]["age_days"] == 3 and by["feed-on-boundary"]["status"] == "current", \
    f"feed-on-boundary: {by['feed-on-boundary']}"
assert by["feed-just-stale"]["age_days"] == 4 and by["feed-just-stale"]["status"] == "stale", \
    f"feed-just-stale: {by['feed-just-stale']}"
# explicit per-pin window beats the class SLA (release-feed would say stale at 36d)
assert by["explicit-beats-class"]["window_days"] == 90 and by["explicit-beats-class"]["status"] == "current", \
    f"explicit-beats-class: {by['explicit-beats-class']}"
# internal-contract class has no shared SLA; pin's own window applies
assert by["internal-own-window"]["window_days"] == 180 and by["internal-own-window"]["status"] == "current", \
    f"internal-own-window: {by['internal-own-window']}"
# by_class grouping present + counts add up
bc = d["by_class"]
assert bc["spec-page"]["total"] == 2 and bc["spec-page"]["stale"] == 1, f"by_class[spec-page]: {bc['spec-page']}"
assert bc["release-feed"]["total"] == 3 and bc["release-feed"]["stale"] == 1, f"by_class[release-feed]: {bc['release-feed']}"
assert bc["(unclassed)"]["total"] == 3, f"by_class[(unclassed)]: {bc['(unclassed)']}"
PY
then pass "class SLA resolution (explicit > class > default) + exact boundary semantics + by_class grouping"
else fail "class SLA resolution / boundary / grouping wrong"; fi

# explicit exit-code-authority check: everything stale -> still exit 0
if python3 "$CUR" --pins "$FIXPINS" --today 2099-06-06 >/dev/null 2>&1; then
  pass "no exit-code authority: exit 0 even when all pins are stale"
else fail "currency returned non-zero — it must never gate a build"; fi

# ---- 5: terminology rename — poll-freshness SLA, grouped text report ----
t="$TMP/report.txt"
python3 "$CUR" --pins "$FIXPINS" --today 2026-06-06 >"$t" 2>/dev/null
if grep -q "poll-freshness SLA" "$t" && ! grep -qi "bounded.staleness" "$t"; then
  pass "text report uses 'poll-freshness SLA' wording (no bounded-staleness framing)"
else fail "text report wording not renamed to poll-freshness SLA"; fi
if grep -q "^\[spec-page\]" "$t" && grep -q "^\[release-feed\]" "$t" && grep -q "^\[(unclassed)\]" "$t"; then
  pass "text report groups pins by class"
else fail "text report missing per-class grouping headers"; fi

# ---- 6: the shipped pin relation parses + reports + exits 0 + covers the registry ----
if python3 "$CUR" --pins "$SHIPPED" --today 2026-06-12 --json >"$TMP/shipped.json" 2>/dev/null \
   && python3 - "$TMP/shipped.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["report"] == "currency/v1"
assert d.get("advisory") is True
by = {p["identity"]: p for p in d["pins"]}
# one pin per lab-registry surface (intent-eval-lab specs/upstream-surface-registry.v1.json)
registry = [
    "agentskills-spec", "platform-skills-overview", "skills-releases",
    "mcp-schema-ts", "mcp-spec-docs", "mcp-releases",
    "claude-hooks", "claude-settings", "claude-slash-commands",
    "plugins-reference", "sub-agents", "plugin-marketplaces",
    "claude-code-changelog", "claude-code-npm", "claude-code-releases",
    "anthropic-engineering",
]
missing = [s for s in registry if s not in by]
assert not missing, f"registry surfaces missing a pin: {missing}"
# the 3 internal-contract pins are kept
for internal in ("skill-md-schema", "gate-result-predicate", "anthropic-sdk"):
    assert internal in by, f"internal pin dropped: {internal}"
    assert by[internal]["class"] == "internal-contract", f"{internal} class: {by[internal]['class']}"
assert len(d["pins"]) >= 19, f"expected >=19 pins, got {len(d['pins'])}"
# every pin carries a class; registry classes carry the documented SLAs
assert all(p["class"] != "(unclassed)" for p in d["pins"]), "shipped pins must all carry a class"
assert by["mcp-schema-ts"]["class"] == "schema-file" and by["mcp-schema-ts"]["window_days"] == 7
assert by["claude-hooks"]["class"] == "spec-page" and by["claude-hooks"]["window_days"] == 7
assert by["claude-code-releases"]["class"] == "release-feed" and by["claude-code-releases"]["window_days"] == 3
# renamed pins: old identities gone, registry ids in place
assert "mcp-spec" not in by and "claude-code" not in by, "renamed pins must not keep old identities"
PY
then
  pass "shipped pins.v1.json parses + covers all 16 registry surfaces + 3 internal-contract pins"
else fail "shipped pins relation did not report cleanly / registry coverage incomplete"; fi

echo ""
echo "currency suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
