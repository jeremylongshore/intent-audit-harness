#!/usr/bin/env bash
# Golden test suite for `audit-harness classify` (audit-profile/v1).
#
# Verifies:
#   1. Each fixture repo classifies to its expected UNION of (kind, confidence) + unresolved
#   2. Every emitted profile validates against schemas/audit-profile/v1.schema.json
#   3. Kill-switch (AUDIT_HARNESS_DISABLE=1) disables every gate + sets overrides.kill_switch
#   4. An unrecognizable repo yields classification=unknown/unresolved + a non-empty unresolved[]
#   5. .audit-harness.yml override pins a classification and disables a gate
#
# Run from the repository root:
#   bash tests/classify/run-classify-tests.sh
# Exit 0 = all green; exit 1 = at least one failure.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CLASSIFY="$ROOT/scripts/classify.py"
SCHEMA="$ROOT/schemas/audit-profile/v1.schema.json"
FIXROOT="$ROOT/tests/fixtures/classify"
EXPECTED="$FIXROOT/expected"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

HAVE_JSONSCHEMA=0
if python3 -c "import jsonschema" 2>/dev/null; then HAVE_JSONSCHEMA=1; fi

validate_schema() { # $1 = profile json file
  [ "$HAVE_JSONSCHEMA" -eq 1 ] || return 0
  python3 - "$SCHEMA" "$1" <<'PY'
import json, sys
import jsonschema
schema = json.load(open(sys.argv[1]))
inst = json.load(open(sys.argv[2]))
jsonschema.validate(inst, schema)
PY
}

cmp_classifications() { # $1 = actual profile json, $2 = expected json
  python3 - "$1" "$2" <<'PY'
import json, sys
act = json.load(open(sys.argv[1]))
exp = json.load(open(sys.argv[2]))
a = sorted((c["kind"], c["confidence"]) for c in act["classifications"])
e = sorted((c["kind"], c["confidence"]) for c in exp["classifications"])
au = sorted(u["kind"] for u in act.get("unresolved", []))
eu = sorted(u["kind"] for u in exp.get("unresolved", []))
if a != e:
    print(f"classification mismatch:\n  expected {e}\n  actual   {a}", file=sys.stderr); sys.exit(1)
if au != eu:
    print(f"unresolved mismatch: expected {eu} actual {au}", file=sys.stderr); sys.exit(1)
PY
}

echo "classify golden suite (jsonschema=$HAVE_JSONSCHEMA)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---- 1+2: golden fixtures ----
for dir in "$FIXROOT"/*/; do
  name="$(basename "$dir")"
  [ "$name" = "expected" ] && continue
  expfile="$EXPECTED/$name.expected.json"
  if [ ! -f "$expfile" ]; then fail "$name: no expected file"; continue; fi
  out="$TMP/$name.json"
  if ! python3 "$CLASSIFY" "$dir" >"$out" 2>"$TMP/$name.err"; then
    fail "$name: classify exited non-zero"; cat "$TMP/$name.err" >&2; continue
  fi
  if cmp_classifications "$out" "$expfile" 2>"$TMP/$name.cmp"; then
    pass "$name: classifications match golden"
  else
    fail "$name: $(cat "$TMP/$name.cmp")"
  fi
  if validate_schema "$out" 2>"$TMP/$name.val"; then
    pass "$name: profile validates against audit-profile/v1 schema"
  else
    fail "$name: schema validation: $(cat "$TMP/$name.val")"
  fi
done

# ---- 3: kill-switch ----
ks="$TMP/killswitch.json"
AUDIT_HARNESS_DISABLE=1 python3 "$CLASSIFY" "$FIXROOT/external-partner-monorepo" >"$ks" 2>/dev/null
if python3 - "$ks" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
assert p.get("overrides", {}).get("kill_switch") is True, "kill_switch flag not set"
assert all(g["enforcement"] == "disabled" for g in p["gates"]), "a gate survived the kill-switch"
PY
then pass "kill-switch: all gates disabled + overrides.kill_switch=true"
else fail "kill-switch did not disable all gates"; fi

# ---- 4: unknown / unresolved ----
mkdir -p "$TMP/empty-repo"
echo "just some notes" > "$TMP/empty-repo/notes.txt"
unk="$TMP/unknown.json"
python3 "$CLASSIFY" "$TMP/empty-repo" >"$unk" 2>/dev/null
if python3 - "$unk" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
kinds = [c["kind"] for c in p["classifications"]]
assert kinds == ["unknown"], f"expected [unknown], got {kinds}"
assert p["classifications"][0]["confidence"] == "unresolved"
assert len(p["unresolved"]) >= 1, "unresolved[] should be non-empty"
PY
then pass "unknown repo: classification=unknown/unresolved + non-empty unresolved[]"
else fail "unknown repo not handled correctly"; fi
validate_schema "$unk" 2>/dev/null && pass "unknown profile validates against schema" || fail "unknown profile failed schema"

# ---- 5: .audit-harness.yml override (pin + disable a gate) ----
ovrepo="$TMP/override-repo"
mkdir -p "$ovrepo"
printf -- '---\nname: x\ndescription: y\n---\n' > "$ovrepo/SKILL.md"
cat > "$ovrepo/.audit-harness.yml" <<'YML'
classify_pins:
  - cli
disable_gates:
  - audit-harness:server:skill-behavioral
YML
ov="$TMP/override.json"
python3 "$CLASSIFY" "$ovrepo" >"$ov" 2>/dev/null
if python3 - "$ov" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
kinds = {c["kind"]: c["confidence"] for c in p["classifications"]}
assert kinds.get("cli") == "declared", f"cli pin not declared: {kinds}"
assert kinds.get("skill") == "detected", "skill should still be detected"
g = {x["gate_id"]: x for x in p["gates"]}
sb = g.get("audit-harness:server:skill-behavioral")
assert sb and sb["enforcement"] == "disabled", "override disable_gates did not apply"
assert p.get("overrides", {}).get("source") == ".audit-harness.yml"
PY
then pass "override: classify_pin=declared + disable_gates applied"
else fail "override file not honored"; fi

echo ""
echo "classify suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
