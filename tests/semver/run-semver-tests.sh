#!/usr/bin/env bash
# SemVer contract suite — pins the public CLI / output contract declared in
# SEMVER.md so a MAJOR-worthy change shipped as MINOR/PATCH fails CI.
#
# WHY THIS EXISTS (and how it differs from the other suites):
#   - tests/regression/run-regression.sh pins BEHAVIORAL parity for specific
#     inputs (text vs --json, emit-evidence invariants) — it answers "does this
#     input still behave the same?"
#   - tests/golden/run-golden.sh pins the raw STDOUT SHAPE of two scorers
#     (gherkin-lint text + crap-score --json) — it answers "did this stdout
#     reshape?"
#   - THIS suite pins the declared SemVer SURFACE from SEMVER.md as live
#     assertions — it answers "did a MAJOR-worthy change ship as MINOR/PATCH?"
#     i.e. did a subcommand get removed/renamed, did a frozen exit code change,
#     did the --json flag stop being accepted, did the predicate URI mutate?
#
# Every assertion below maps to an explicit row in SEMVER.md. When SEMVER.md
# says a change is "major", the corresponding assertion here is the wire that
# trips: ship that change and this suite goes red, forcing the contributor to
# either revert it or cut a major version (and update SEMVER.md + this suite in
# the same PR, reviewed as a deliberate contract change).
#
# Run from the repository root:
#   bash tests/semver/run-semver-tests.sh
# Exit 0 = contract intact; exit 1 = at least one SemVer-frozen surface drifted.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$ROOT/scripts"
BIN="$ROOT/bin/audit-harness.js"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A clean unified diff that escape-scan classifies as PASS (exit 0).
CLEAN_DIFF="$TMP/clean.diff"
cat > "$CLEAN_DIFF" <<'EOF'
diff --git a/foo.py b/foo.py
index 0000001..0000002 100644
--- a/foo.py
+++ b/foo.py
@@ -1 +1 @@
-x = 1
+x = 2
EOF

# A diff that lowers the coverage floor below the policy minimum -> REFUSE (exit 2).
REFUSE_DIFF="$TMP/refuse.diff"
cat > "$REFUSE_DIFF" <<'EOF'
diff --git a/pytest.ini b/pytest.ini
index 0000001..0000002 100644
--- a/pytest.ini
+++ b/pytest.ini
@@ -1 +1,2 @@
 [pytest]
+addopts = --cov-fail-under=10
EOF

# ===========================================================================
# Section 1 — subcommand roster (SEMVER.md: "Remove or rename a subcommand
# or flag" = MAJOR). Every command frozen with a "Stable since" row in
# SEMVER.md's exit-code table MUST still be dispatchable. A removed/renamed
# command surfaces here as a missing dispatch, not a silent minor bump.
# ===========================================================================

echo "▶ Section 1 — frozen subcommand roster (removal/rename = MAJOR)"

# Commands that carry a "Stable since" guarantee in SEMVER.md.
#   escape-scan/verify/crap/arch/gherkin-lint/bias : stable since v0.1.0
#   emit-evidence                                  : stable since v0.3.0
FROZEN_COMMANDS=(escape-scan verify crap arch gherkin-lint bias emit-evidence)

# A command is "present" if the dispatcher routes it to an existing script
# (i.e. does NOT print "unknown command" + exit 2). We probe via --help-like
# no-op-safe paths where possible, but the authoritative signal is that the
# dispatcher knows the command. We assert against the dispatcher's own routing
# table by invoking with a guaranteed-no-op argument set and checking that the
# error is NOT the "unknown command" exit-2 path.
help_out="$(node "$BIN" --help 2>/dev/null)"
for c in "${FROZEN_COMMANDS[@]}"; do
  # The dispatcher prints "unknown command '<c>'" + exits 2 for a missing
  # command. We detect presence by confirming the command does NOT trigger that
  # exact unknown-command path. Use a bogus subflag that every script tolerates
  # by either erroring on its own terms (non-2-unknown) or printing usage.
  err="$(node "$BIN" "$c" --audit-harness-semver-probe-nonexistent-flag 2>&1 1>/dev/null)"
  if echo "$err" | grep -q "unknown command '$c'"; then
    fail "subcommand '$c' is GONE from the dispatcher (SEMVER.md: removal/rename = MAJOR)"
  else
    pass "subcommand '$c' still dispatchable"
  fi
  # Belt-and-suspenders: the command must also appear in --help text so the
  # documented surface and the routed surface can't drift apart silently.
  if echo "$help_out" | grep -qE "^\s+$c\b"; then
    pass "subcommand '$c' documented in --help"
  else
    fail "subcommand '$c' missing from --help text (documented surface drifted)"
  fi
done

# ===========================================================================
# Section 2 — frozen exit codes (SEMVER.md: "Change existing exit code for the
# same input" = MAJOR). Each assertion is a row from the SEMVER.md exit-code
# table, evaluated against live behavior.
# ===========================================================================

echo "▶ Section 2 — frozen exit codes (changing an exit code for same input = MAJOR)"

assert_exit() { # $1=label  $2=expected  shift 2; rest = command
  local label="$1" expected="$2"; shift 2
  local ec=0
  "$@" >/dev/null 2>&1 || ec=$?
  if [[ "$ec" -eq "$expected" ]]; then
    pass "$label: exit $expected (frozen)"
  else
    fail "$label: exit $ec, SEMVER.md freezes this at $expected"
  fi
}

# escape-scan: 0 clean / 2 REFUSE  (v0.1.0)
assert_exit "escape-scan clean diff"  0 bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF"
assert_exit "escape-scan REFUSE diff" 2 bash "$SCRIPTS/escape-scan.sh" --no-hash "$REFUSE_DIFF"

# verify (harness-hash): 0 OK (manifest present, untampered) / 3 no manifest  (v0.1.0)
assert_exit "verify (manifest present, clean)" 0 bash "$SCRIPTS/harness-hash.sh" --verify
( cd "$TMP" && assert_exit "verify (no manifest)" 3 bash "$SCRIPTS/harness-hash.sh" --verify )

# crap: 2 unsupported language  (v0.1.0)
assert_exit "crap unsupported language" 2 python3 "$SCRIPTS/crap-score.py" --root "$TMP" --lang cobol

# gherkin-lint: 2 path not found  (v0.1.0)
assert_exit "gherkin-lint missing path" 2 bash "$SCRIPTS/gherkin-lint.sh" --path "$TMP/nope-xyz"

# bias: 1 test directory not found  (v0.1.0)
assert_exit "bias missing test dir" 1 bash "$SCRIPTS/bias-count.sh" "$TMP/nope-xyz"

# emit-evidence: 1 input malformed  (v0.3.0)
ec=0
echo '{"gate_id":"audit-harness:ci:probe"}' | bash "$SCRIPTS/emit-evidence.sh" >/dev/null 2>&1 || ec=$?
if [[ "$ec" -eq 1 ]]; then
  pass "emit-evidence malformed input: exit 1 (frozen)"
else
  fail "emit-evidence malformed input: exit $ec, SEMVER.md freezes this at 1"
fi

# dispatcher unknown command: exit 2 (the unknown-command contract used by
# Section 1's presence probe — pin it so the probe itself stays meaningful).
ec=0
node "$BIN" audit-harness-semver-no-such-command >/dev/null 2>&1 || ec=$?
if [[ "$ec" -eq 2 ]]; then
  pass "dispatcher unknown command: exit 2 (frozen)"
else
  fail "dispatcher unknown command: exit $ec (expected 2)"
fi

# --version contract: exit 0, prints the package.json version verbatim.
pkg_version="$(node -p "require('$ROOT/package.json').version")"
ver_out="$(node "$BIN" --version 2>/dev/null)"
ver_ec=$?
if [[ "$ver_ec" -eq 0 && "$ver_out" == "$pkg_version" ]]; then
  pass "--version: exit 0, prints package.json version ($pkg_version)"
else
  fail "--version: exit $ver_ec / output '$ver_out' (expected exit 0 + '$pkg_version')"
fi

# ===========================================================================
# Section 3 — --json flag is a frozen ADDITIVE surface (SEMVER.md: "Remove or
# rename a ... flag" = MAJOR; "Move output between stdout/stderr for the same
# flag combination" = MAJOR). For each gate that ships --json, assert that:
#   (a) --json is still ACCEPTED (not rejected as an unknown flag), and
#   (b) the stream contract holds: stdout carries a single JSON object,
#       stderr carries the human-readable text it always did.
# ===========================================================================

echo "▶ Section 3 — --json flag + stream contract (flag removal / stream move = MAJOR)"

# escape-scan --json: stdout must be exactly one JSON object; stderr keeps the
# human-readable summary (SEMVER.md "Stream contracts" table).
stdout_json="$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" --json 2>/dev/null)"
if echo "$stdout_json" | python3 -c "import sys,json; json.loads(sys.stdin.read())" 2>/dev/null; then
  pass "escape-scan --json: stdout is a single valid JSON object"
else
  fail "escape-scan --json: stdout is NOT valid JSON (flag dropped or stream moved?) — got: $stdout_json"
fi
stderr_text="$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" --json 2>&1 >/dev/null)"
if echo "$stderr_text" | grep -q "escape-scan: REFUSE=0"; then
  pass "escape-scan --json: stderr preserves human-readable summary (no stdout/stderr swap)"
else
  fail "escape-scan --json: stderr lost the human-readable summary (stream contract broken)"
fi

# arch + gherkin-lint --json: each emits a single gate-result JSON object on
# stdout for the no-op (NOT_APPLICABLE) case. This confirms the flag is wired
# on these gates; their full envelope shape is pinned elsewhere.
arch_json="$(bash "$SCRIPTS/arch-check.sh" --json 2>/dev/null)"
if echo "$arch_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); assert d.get('gate_id'),'no gate_id'" 2>/dev/null; then
  pass "arch --json: stdout is a gate-result JSON object"
else
  fail "arch --json: stdout not a gate-result JSON object — got: $arch_json"
fi
gherkin_json="$(bash "$SCRIPTS/gherkin-lint.sh" --json 2>/dev/null)"
if echo "$gherkin_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); assert d.get('gate_id'),'no gate_id'" 2>/dev/null; then
  pass "gherkin-lint --json: stdout is a gate-result JSON object"
else
  fail "gherkin-lint --json: stdout not a gate-result JSON object — got: $gherkin_json"
fi

# bias --json on a missing dir: emits a NOT_APPLICABLE gate-result JSON object
# on stdout (the documented exit-1 path keeps the --json contract).
bias_json="$(bash "$SCRIPTS/bias-count.sh" "$TMP/nope-xyz" --json 2>/dev/null)"
if echo "$bias_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); assert d.get('gate_id'),'no gate_id'" 2>/dev/null; then
  pass "bias --json: stdout is a gate-result JSON object even on the not-found path"
else
  fail "bias --json: stdout not a gate-result JSON object — got: $bias_json"
fi

# ===========================================================================
# Section 4 — frozen emit-evidence predicate URI (SEMVER.md: "Change the
# predicateType URI referenced by emit-evidence" = MAJOR; URI is frozen once a
# signed Statement is pushed to Rekor). Mutating the URI body or path under the
# same version is the highest-cost silent break — pin both _type and
# predicateType exactly.
# ===========================================================================

echo "▶ Section 4 — frozen emit-evidence predicate URI (URI change = MAJOR)"

FROZEN_TYPE="https://in-toto.io/Statement/v1"
FROZEN_PREDICATE="https://evals.intentsolutions.io/gate-result/v1"

statement="$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" --json 2>/dev/null \
  | bash "$SCRIPTS/emit-evidence.sh" --runner-version "audit-harness@semver-suite" --commit-sha "0000000" 2>/dev/null)"

if echo "$statement" | python3 -c "
import sys, json
s = json.loads(sys.stdin.read())
assert s['_type'] == '$FROZEN_TYPE', '_type drifted to ' + repr(s.get('_type'))
assert s['predicateType'] == '$FROZEN_PREDICATE', 'predicateType drifted to ' + repr(s.get('predicateType'))
" 2>/dev/null; then
  pass "emit-evidence: _type frozen at $FROZEN_TYPE"
  pass "emit-evidence: predicateType frozen at $FROZEN_PREDICATE"
else
  fail "emit-evidence: in-toto _type or predicateType URI drifted (SEMVER.md freezes both — a body change MUST mint gate-result/v2, never mutate v1)"
fi

# Cross-check the SEMVER.md doc still declares the same frozen URI, so the doc
# and the wire can't drift apart silently.
if grep -q "gate-result/v1" "$ROOT/SEMVER.md"; then
  pass "SEMVER.md still declares the gate-result/v1 predicate URI"
else
  fail "SEMVER.md no longer declares gate-result/v1 — doc/wire predicate URI drift"
fi

# ===========================================================================
# Summary
# ===========================================================================

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SemVer contract results: PASS=$PASS  FAIL=$FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ "$FAIL" -eq 0 ]]
