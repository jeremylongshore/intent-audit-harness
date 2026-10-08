#!/usr/bin/env bash
# Golden test suite for `audit-harness conform` (emits gate-result/v1 rows).
#
# Verifies:
#   1. Valid fixtures (skill, mcp, plugin, agent) -> the conform gate row is PASS
#   2. Every emitted row validates against the gate-result/v1 schema
#   3. Malformed fixtures -> ADVISORY (severity error) by default, exit 0 (advisory-first)
#   4. The SAME malformed fixtures -> FAIL (failure_mode set) under --strict, exit 1
#   5. Kill-switch (AUDIT_HARNESS_DISABLE=1) -> empty [] row set, exit 0
#   6. A profile gate whose artifact is absent -> NOT_APPLICABLE
#   7. A conformance kind with no bundled schema -> ADVISORY indeterminate (never a false FAIL)
#   8. policy_hash == sha256 of the bundled schema (content-addressed), and is reproducible
#   9. --tier marketplace: a full 8-field SKILL.md -> PASS; policy_hash == sha256(kernel pin.json)
#  10. A SKILL.md missing `version` -> floor PASS (default unchanged), marketplace ADVISORY,
#      marketplace --strict FAIL (the whiteglove gap this tier closes)
#  11. Kernel shape rules: non-semver version, non-string/array allowed-tools, deprecated field
#  12. Pin integrity: a tampered vendored kernel file -> ADVISORY indeterminate, never a verdict
#  13. Parity: the embedded validator agrees with jsonschema+referencing on every SKILL fixture
#
# Run from the repository root:
#   bash tests/conform/run-conform-tests.sh
# Exit 0 = all green; exit 1 = at least one failure.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFORM="$ROOT/scripts/conform.py"
GR_SCHEMA="$ROOT/tests/fixtures/gate-result.schema.json"
FIX="$ROOT/tests/fixtures/conform"
SKILL_SCHEMA="$ROOT/schemas/conform/v1/skillmd-frontmatter.schema.json"

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
assert isinstance(rows, list), "conform output is not a JSON array"
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

echo "conform golden suite (jsonschema=$HAVE_JSONSCHEMA)"

# ---- 1+2: valid fixtures -> PASS + schema-valid ----
declare -A VALID=(
  [skill]=conform-skillmd
  [mcp]=conform-mcp
  [plugin]=conform-plugin
  [agent]=conform-agent
)
for k in "${!VALID[@]}"; do
  out="$TMP/valid-$k.json"
  if python3 "$CONFORM" "$FIX/valid/$k" >"$out" 2>/dev/null; then ec=0; else ec=$?; fi
  if [ "$ec" -ne 0 ]; then fail "valid/$k: conform exited $ec (expected 0)"; continue; fi
  if assert_row "$out" "${VALID[$k]}" PASS 2>"$TMP/e"; then
    pass "valid/$k: ${VALID[$k]} -> PASS"
  else fail "valid/$k: $(cat "$TMP/e")"; fi
  if validate_rows "$out" 2>"$TMP/e"; then
    pass "valid/$k: rows validate against gate-result/v1"
  else fail "valid/$k: row schema: $(cat "$TMP/e")"; fi
done

# ---- 3+4: malformed fixtures -> ADVISORY (default) / FAIL (--strict) ----
# fixture_dir | gate_substr | expected_failure_mode (under --strict)
MALFORMED=(
  "skill-missing-description|conform-skillmd|conform:schema-violation"
  "skill-unterminated|conform-skillmd|conform:parse-error"
  "mcp-no-launch|conform-mcp|conform:schema-violation"
  "mcp-broken-json|conform-mcp|conform:parse-error"
  "plugin-missing-name|conform-plugin|conform:schema-violation"
  "agent-missing-description|conform-agent|conform:schema-violation"
)
for spec in "${MALFORMED[@]}"; do
  IFS='|' read -r d sub fm <<<"$spec"
  # default: ADVISORY severity error, exit 0
  out="$TMP/adv-$d.json"
  if python3 "$CONFORM" "$FIX/malformed/$d" >"$out" 2>/dev/null; then ec=0; else ec=$?; fi
  if [ "$ec" -ne 0 ]; then fail "malformed/$d (default): exit $ec (expected 0, advisory-first)"; fi
  if assert_row "$out" "$sub" ADVISORY advisory_severity error 2>"$TMP/e"; then
    pass "malformed/$d: $sub -> ADVISORY(error) default, exit 0"
  else fail "malformed/$d (default): $(cat "$TMP/e")"; fi
  if validate_rows "$out" 2>"$TMP/e"; then pass "malformed/$d: advisory rows schema-valid"
  else fail "malformed/$d advisory row schema: $(cat "$TMP/e")"; fi
  # --strict: FAIL with failure_mode, exit 1
  outs="$TMP/strict-$d.json"
  if python3 "$CONFORM" --strict "$FIX/malformed/$d" >"$outs" 2>/dev/null; then ecs=0; else ecs=$?; fi
  if [ "$ecs" -ne 1 ]; then fail "malformed/$d (--strict): exit $ecs (expected 1)"; fi
  if assert_row "$outs" "$sub" FAIL failure_mode "$fm" 2>"$TMP/e"; then
    pass "malformed/$d: $sub -> FAIL($fm) --strict, exit 1"
  else fail "malformed/$d (--strict): $(cat "$TMP/e")"; fi
done

# ---- 5: kill-switch ----
ks="$TMP/ks.json"
if AUDIT_HARNESS_DISABLE=1 python3 "$CONFORM" "$FIX/valid/skill" >"$ks" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && [ "$(tr -d '[:space:]' <"$ks")" = "[]" ]; then
  pass "kill-switch: empty [] emitted, exit 0"
else fail "kill-switch: expected [] exit 0, got exit $ec / $(cat "$ks")"; fi

# ---- 6+7: pinned profile -> NOT_APPLICABLE (absent) + ADVISORY indeterminate (no bundled schema) ----
prof="$TMP/profile.json"
cat > "$prof" <<'JSON'
{"schema_version":"audit-profile/v1",
 "subject":{"name":"pinned","commit_sha":"0000000","root":"."},
 "classifier":"test","registry_hash":"sha256:0",
 "timestamp":"2026-06-05T00:00:00Z","classifications":[],"gates":[
   {"gate_id":"audit-harness:local:conform-marketplace","dimension":"conformance","applicability":"required","enforcement":"advisory"},
   {"gate_id":"audit-harness:local:conform-hook","dimension":"conformance","applicability":"required","enforcement":"advisory"}
 ],"unresolved":[]}
JSON
naroot="$TMP/na-repo"; mkdir -p "$naroot"
na="$TMP/na.json"
python3 "$CONFORM" "$naroot" --profile "$prof" >"$na" 2>/dev/null
if assert_row "$na" "conform-marketplace" NOT_APPLICABLE 2>"$TMP/e" \
   && assert_row "$na" "conform-hook" NOT_APPLICABLE 2>>"$TMP/e"; then
  pass "pinned profile, no artifacts: marketplace + hook -> NOT_APPLICABLE"
else fail "NOT_APPLICABLE path: $(cat "$TMP/e")"; fi
if validate_rows "$na" 2>"$TMP/e"; then pass "NOT_APPLICABLE rows schema-valid"
else fail "NOT_APPLICABLE rows schema: $(cat "$TMP/e")"; fi

# add a marketplace.json (kind has no bundled schema) -> ADVISORY indeterminate, never FAIL
printf '{"name":"m","plugins":[]}\n' > "$naroot/marketplace.json"
ind="$TMP/ind.json"
if python3 "$CONFORM" --strict "$naroot" --profile "$prof" >"$ind" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && python3 - "$ind" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
m = [r for r in rows if "conform-marketplace" in r["gate_id"]][0]
assert m["result"] == "ADVISORY", f"expected ADVISORY, got {m['result']}"
assert m.get("metadata", {}).get("indeterminate") is True, "missing indeterminate marker"
PY
then pass "no-bundled-schema kind -> ADVISORY indeterminate even under --strict (no false FAIL)"
else fail "indeterminate path did not hold (exit $ec)"; fi

# ---- 8: policy_hash == sha256 of bundled schema + reproducible ----
r1="$TMP/r1.json"; r2="$TMP/r2.json"
python3 "$CONFORM" "$FIX/valid/skill" >"$r1" 2>/dev/null
python3 "$CONFORM" "$FIX/valid/skill" >"$r2" 2>/dev/null
if python3 - "$r1" "$r2" "$SKILL_SCHEMA" <<'PY'
import json, sys, hashlib
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
want = "sha256:" + hashlib.sha256(open(sys.argv[3], "rb").read()).hexdigest()
ra = [r for r in a if "conform-skillmd" in r["gate_id"]][0]
rb = [r for r in b if "conform-skillmd" in r["gate_id"]][0]
assert ra["policy_hash"] == want, f"policy_hash {ra['policy_hash']} != schema sha {want}"
assert ra["policy_hash"] == rb["policy_hash"], "policy_hash not reproducible"
assert ra["input_hash"] == rb["input_hash"], "input_hash not reproducible"
assert ra["result"] == rb["result"], "result not reproducible"
PY
then pass "policy_hash == bundled schema sha256 + reproducible across runs"
else fail "policy_hash/reproducibility check failed"; fi

# ---- 9: --tier marketplace on a full 8-field skill -> PASS, kernel policy_hash ----
PIN="$ROOT/schemas/conform/kernel/intent-eval-core-0.11.0/pin.json"
mk="$TMP/mk.json"
if python3 "$CONFORM" --tier marketplace --strict "$FIX/valid/skill-marketplace" >"$mk" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && python3 - "$mk" "$PIN" <<'PY'
import json, sys, hashlib
r = [x for x in json.load(open(sys.argv[1])) if "conform-skillmd" in x["gate_id"]][0]
want = "sha256:" + hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
assert r["result"] == "PASS", r
assert r["policy_hash"] == want, f"policy_hash {r['policy_hash']} != pin sha {want}"
md = r["metadata"]
assert md["tier"] == "marketplace" and md["kernel"] == "@intentsolutions/core@0.11.0", md
assert md["schema_id"].endswith("/authoring/v1/skill-frontmatter.schema.json"), md
PY
then pass "--tier marketplace: full 8-field skill -> PASS, policy_hash == sha256(pin.json)"
else fail "--tier marketplace valid fixture (exit $ec): $(cat "$mk")"; fi
if validate_rows "$mk" 2>"$TMP/e"; then pass "--tier marketplace rows schema-valid"
else fail "--tier marketplace row schema: $(cat "$TMP/e")"; fi

# ---- 10: missing version -> floor PASS (default), marketplace ADVISORY / --strict FAIL ----
nv="$FIX/malformed/skill-no-version"
python3 "$CONFORM" "$nv" >"$TMP/nv-floor.json" 2>/dev/null
if assert_row "$TMP/nv-floor.json" conform-skillmd PASS 2>"$TMP/e"; then
  pass "no-version skill: default tier stays floor -> PASS (existing consumers unchanged)"
else fail "no-version default: $(cat "$TMP/e")"; fi
if python3 "$CONFORM" --tier marketplace "$nv" >"$TMP/nv-adv.json" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && assert_row "$TMP/nv-adv.json" conform-skillmd ADVISORY advisory_severity error 2>"$TMP/e" \
   && grep -q "missing required property 'version'" "$TMP/nv-adv.json"; then
  pass "no-version skill: --tier marketplace -> ADVISORY(error) naming 'version', exit 0"
else fail "no-version marketplace advisory (exit $ec): $(cat "$TMP/e" "$TMP/nv-adv.json")"; fi
if python3 "$CONFORM" --tier marketplace --strict "$nv" >"$TMP/nv-strict.json" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 1 ] && assert_row "$TMP/nv-strict.json" conform-skillmd FAIL failure_mode conform:schema-violation 2>"$TMP/e"; then
  pass "no-version skill: --tier marketplace --strict -> FAIL(conform:schema-violation), exit 1"
else fail "no-version marketplace strict (exit $ec): $(cat "$TMP/e")"; fi

# ---- 11: kernel shape rules ----
python3 "$CONFORM" --tier marketplace "$FIX/malformed/skill-bad-kernel-shape" >"$TMP/shape.json" 2>/dev/null
if python3 - "$TMP/shape.json" <<'PY'
import json, sys
r = [x for x in json.load(open(sys.argv[1])) if "conform-skillmd" in x["gate_id"]][0]
errs = " | ".join(r["metadata"]["errors"])
assert r["result"] == "ADVISORY", r["result"]
assert "$.version: does not match pattern" in errs, errs
assert "$.allowed-tools: matches none of anyOf" in errs, errs
assert "when_to_use" in errs, errs
PY
then pass "kernel shape: non-semver version + bad allowed-tools + deprecated when_to_use all reported"
else fail "kernel shape rules: $(cat "$TMP/shape.json")"; fi

# ---- 12: tampered kernel pin -> ADVISORY indeterminate, even under --strict ----
th="$TMP/tampered"; mkdir -p "$th"
cp -R "$ROOT/scripts" "$ROOT/schemas" "$th/"
cp "$ROOT/package.json" "$th/" 2>/dev/null || true
printf ' ' >> "$th/schemas/conform/kernel/intent-eval-core-0.11.0/authoring/v1/is-overlay/skill-frontmatter.v1.json"
if python3 "$th/scripts/conform.py" --tier marketplace --strict "$FIX/valid/skill-marketplace" >"$TMP/tam.json" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && python3 - "$TMP/tam.json" <<'PY'
import json, sys
r = [x for x in json.load(open(sys.argv[1])) if "conform-skillmd" in x["gate_id"]][0]
assert r["result"] == "ADVISORY" and r["metadata"].get("indeterminate") is True, r
assert "hash mismatch" in r["metadata"]["reason"], r["metadata"]
PY
then pass "tampered kernel file -> ADVISORY indeterminate (hash mismatch), no verdict, exit 0"
else fail "tampered kernel (exit $ec): $(cat "$TMP/tam.json")"; fi

# ---- 13: parity with a reference JSON-Schema validator ----
if python3 -c "import jsonschema, referencing" 2>/dev/null; then
  if python3 - "$ROOT" <<'PY'
import glob, os, sys
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "scripts"))
import conform as CF
import jsonschema
from referencing import Registry, Resource
k, reg, _, _, reason = CF.load_kernel("skillmd")
assert k is not None, reason
R = Registry().with_resources([(i, Resource.from_contents(d)) for i, d in reg.items()])
V = jsonschema.Draft202012Validator(k, registry=R)
n = 0
for f in sorted(glob.glob(os.path.join(root, "tests/fixtures/conform/**/SKILL.md"), recursive=True)):
    d, e = CF.extract_frontmatter(f)
    if e:
        continue
    ours = bool(CF.validate_instance(d, k, _ctx={"root": k, "registry": reg}))
    ref = any(True for _ in V.iter_errors(d))
    assert ours == ref, f"{f}: embedded={ours} jsonschema={ref}"
    n += 1
assert n >= 4, n
PY
  then pass "embedded validator == jsonschema on every SKILL fixture (marketplace tier)"
  else fail "embedded vs jsonschema parity"; fi
else
  echo "  - parity check skipped (jsonschema/referencing not installed)"
fi

echo ""
echo "conform suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
