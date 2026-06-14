#!/usr/bin/env bash
# cred-gate + OTel-decision suite — OFFLINE proof of two epic heads:
#
#   iah-E08 (cred-gate)  — provider credential PASS/FAIL gate (CISO binding
#                          DR-010 S1Q5). Covers E08a (credential-redaction test
#                          fixture), E08b (env-var spillover test fixture), and
#                          E08c (the CI gate that runs both — this file IS the
#                          gate body invoked by .github/workflows/ci.yml).
#
#   iah-E07b (OTel)      — the gate.decision.emitted event in
#                          scripts/emit-evidence.sh fires per the NORMATIVE
#                          runtime event taxonomy (intent-eval-lab 067-AT-SPEC
#                          § 2.2) with the gate.decision enum {pass, fail,
#                          advisory, error} and kernel-pinned attribute spelling
#                          (gate.name / gate.decision / gate.policy_ref).
#
# It mirrors the repo's existing runner style (tests/dns-preflight, tests/semver):
#   bash tests/cred-gate/run-cred-gate-tests.sh
#   exit 0 = all green; exit 1 = at least one assertion failed. ⛔ / ✓ markers.
#
# Fully OFFLINE: no provider is contacted, no real key is read. Secret VALUES are
# synthetic fixtures injected into the local environment for the duration of one
# assertion and never touch argv (passed by env-var NAME via --secret-env).

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CRED_GATE="$ROOT/scripts/cred-gate.sh"
EMIT="$ROOT/scripts/emit-evidence.sh"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

# assert_eq EXPECTED ACTUAL MSG — proper if-then-else (avoids the A && B || C
# footgun where a falsey pass()/fail() return would mis-route).
assert_eq() {
  if [[ "$1" == "$2" ]]; then
    pass "$3"
  else
    fail "$3 (expected '$1', got '$2')"
  fi
}

# ---------------------------------------------------------------------------
# Group 1 — iah-E08a: credential-redaction test fixture
# ---------------------------------------------------------------------------
echo "== iah-E08a: credential redaction =="

# A clean artifact with no secret material must PASS (exit 0).
clean='{"gate_id":"x","result":"PASS","input_hash":"sha256:aa","policy_hash":"sha256:bb"}'
ec=0; printf '%s' "$clean" | bash "$CRED_GATE" >/dev/null 2>&1 || ec=$?
assert_eq "0" "$ec" "clean artifact PASSes (exit 0)"

# A DECLARED secret value appearing verbatim must FAIL (exit 1). The value is
# read by env-var NAME — never on the command line.
export FIXTURE_SECRET="sk-fixture-NOTREAL-0123456789abcdefXYZ"
leak='{"context":"the key is '"$FIXTURE_SECRET"'"}'
ec=0; printf '%s' "$leak" | bash "$CRED_GATE" --secret-env FIXTURE_SECRET >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "declared secret value leak FAILs (exit 1)"
unset FIXTURE_SECRET

# The same declared name with the value NOT present must PASS — proves the gate
# checks the VALUE, not merely the presence of the env-var name.
export FIXTURE_SECRET="sk-fixture-NOTREAL-0123456789abcdefXYZ"
ec=0; printf '%s' "$clean" | bash "$CRED_GATE" --secret-env FIXTURE_SECRET >/dev/null 2>&1 || ec=$?
assert_eq "0" "$ec" "declared name absent from artifact PASSes (value-checked, not name-checked)"
unset FIXTURE_SECRET

# An UNDECLARED provider-key SHAPE embedded in the artifact must FAIL — catches
# leaks even when the secret was not passed via --secret-env.
shape='{"note":"embedded AKIAIOSFODNN7EXAMPLE here"}'
ec=0; printf '%s' "$shape" | bash "$CRED_GATE" >/dev/null 2>&1 || ec=$?
assert_eq "1" "$ec" "undeclared provider-key SHAPE FAILs (exit 1)"

# Full provider-key-shape catalog: every shape in scripts/cred-gate.sh's
# SHAPE_PATTERNS must have a FAILing fixture, so a regression in any single
# regex cannot ship silently green. Each value is SYNTHETIC and NON-REAL —
# constructed only to satisfy the shape, never a live credential.
#   label format  shape-name:fixture-value
for label in \
  'anthropic-key:sk-ant-NOTREAL00abcdef0123456789XYZ' \
  'openai-key:sk-proj-NOTREAL00abcdef0123456789XYZ' \
  'groq-key:gsk_NOTREAL00abcdef0123456789ABCDEFG0' \
  'nvidia-key:nvapi-NOTREAL00abcdef0123456789XYZ0' \
  'aws-access-key-id:AKIANOTREAL0EXAMPLE0' \
  'google-api-key:AIzaNOTREAL0000000000000000000000000000' \
  'github-token:ghp_NOTREAL00abcdefghijklmnopqrstuvwxyz0123' \
  'slack-token:xoxb-NOTREAL-000000000000-abcdefABCDEF' \
  'private-key-block:-----BEGIN RSA PRIVATE KEY-----' \
; do
  shape_name="${label%%:*}"
  shape_val="${label#*:}"
  # Embed the synthetic value inside an otherwise-clean JSON string field.
  shape_artifact=$(printf '{"note":"embedded %s here"}' "$shape_val")
  ec=0; printf '%s' "$shape_artifact" | bash "$CRED_GATE" >/dev/null 2>&1 || ec=$?
  assert_eq "1" "$ec" "provider-key shape ($shape_name) FAILs (exit 1)"
done

# A synthetic value that does NOT match any catalogued shape must PASS — proves
# the catalog is shape-specific, not a blanket "looks-keyish" heuristic.
nonkey='{"note":"this build ref is release-1.1.8-rc and is not a key"}'
ec=0; printf '%s' "$nonkey" | bash "$CRED_GATE" >/dev/null 2>&1 || ec=$?
assert_eq "0" "$ec" "non-matching value PASSes (catalog is shape-specific, not keyish-heuristic)"

# The FAIL finding must NOT echo the secret value back (no re-leak). We assert the
# finding text reports a length + fingerprint, never the raw value.
export FIXTURE_SECRET="sk-fixture-NOTREAL-0123456789abcdefXYZ"
out=$(printf '%s' "$leak" | bash "$CRED_GATE" --secret-env FIXTURE_SECRET 2>&1 || true)
if printf '%s' "$out" | grep -qF "$FIXTURE_SECRET"; then
  fail "FAIL output RE-LEAKED the secret value (must report fingerprint only)"
else
  pass "FAIL output redacts the secret value (fingerprint only, no re-leak)"
fi
unset FIXTURE_SECRET

# ---------------------------------------------------------------------------
# Group 2 — iah-E08b: env-var spillover test fixture
# ---------------------------------------------------------------------------
echo "== iah-E08b: env-var spillover =="

# An artifact serializing the whole environment must FAIL even with no named key.
# One fixture per spillover pattern in scripts/cred-gate.sh's SPILLOVER_PATTERNS
# so a regression in any single heuristic cannot ship silently green.
for label in \
  'process-env-spread:{"ctx":{...process.env}}' \
  'os-environ-dump:{"ctx":{"all":dict(os.environ)}}' \
  'env-block-key:{"debug":{"environment":{"HOME":"/x"}}}' \
  'printenv-capture:{"cmd":"printenv > dump.txt"}' \
; do
  name="${label%%:*}"
  artifact="${label#*:}"
  ec=0; printf '%s' "$artifact" | bash "$CRED_GATE" >/dev/null 2>&1 || ec=$?
  assert_eq "1" "$ec" "env spillover ($name) FAILs (exit 1)"
done

# A benign artifact that merely MENTIONS the word "environment" in prose without
# the structural spillover shape must still PASS (FP guard).
benign='{"gate_id":"x","result":"PASS","input_hash":"sha256:aa","policy_hash":"sha256:bb","description":"runs in the test environment"}'
ec=0; printf '%s' "$benign" | bash "$CRED_GATE" >/dev/null 2>&1 || ec=$?
assert_eq "0" "$ec" "benign 'environment' prose PASSes (no false positive)"

# ---------------------------------------------------------------------------
# Group 3 — iah-E08: --json envelope shape (pipe-ready for emit-evidence)
# ---------------------------------------------------------------------------
echo "== iah-E08: gate-result/v1 envelope =="

env_json=$(printf '%s' "$shape" | bash "$CRED_GATE" --json 2>/dev/null || true)
keys_ok=$(printf '%s' "$env_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
need = {'gate_id', 'result', 'input_hash', 'policy_hash'}
ok = need.issubset(d) and d['result'] == 'FAIL' and d['input_hash'].startswith('sha256:')
print('ok' if ok else 'bad')
" 2>/dev/null || echo "bad")
assert_eq "ok" "$keys_ok" "--json emits a well-formed gate-result/v1 envelope (result=FAIL)"

# The envelope must round-trip through emit-evidence into an in-toto Statement.
stmt=$(printf '%s' "$shape" | bash "$CRED_GATE" --json 2>/dev/null  | bash "$EMIT" 2>/dev/null || true)
stmt_ok=$(printf '%s' "$stmt" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('ok' if d.get('predicateType','').endswith('/gate-result/v1') else 'bad')
" 2>/dev/null || echo "bad")
assert_eq "ok" "$stmt_ok" "cred-gate --json | emit-evidence -> valid in-toto Statement"

# ---------------------------------------------------------------------------
# Group 4 — iah-E07b: gate.decision.emitted OTel event (067-AT-SPEC § 2.2)
# ---------------------------------------------------------------------------
echo "== iah-E07b: OTel gate.decision.emitted event =="

# PASS gate -> gate.decision "pass"; event name is gate.decision.emitted, payload
# carries gate.name + gate.policy_ref per 067-AT-SPEC § 2.2.
otel_pass=$(echo '{"gate_id":"g1","gate_name":"escape-scan","result":"PASS","input_hash":"sha256:aa","policy_hash":"sha256:bb","policy_ref":"sha256:bb:tests/TESTING.md"}'  | AUDIT_HARNESS_OTEL=1 bash "$EMIT" 2>&1 >/dev/null | grep '"name":"gate.decision.emitted"' || true)
pass_ok=$(printf '%s' "$otel_pass" | sed 's/^\[OTEL\] //' | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('bad'); sys.exit()
a = d.get('attributes', {})
print('ok' if (a.get('gate.decision') == 'pass'
    and a.get('gate.name') == 'escape-scan'
    and a.get('gate.policy_ref') == 'sha256:bb:tests/TESTING.md'
    and 'gate.reasons' in a) else 'bad')
" 2>/dev/null || echo "bad")
assert_eq "ok" "$pass_ok" "PASS gate emits gate.decision.emitted with gate.decision=pass + gate.name + gate.policy_ref"

# FAIL gate -> gate.decision "fail" with a non-empty reasons array.
otel_fail=$(echo '{"gate_id":"g2","result":"FAIL","input_hash":"sha256:aa","policy_hash":"sha256:bb","failure_mode":"below_threshold"}'  | AUDIT_HARNESS_OTEL=1 bash "$EMIT" 2>&1 >/dev/null | grep '"name":"gate.decision.emitted"' || true)
fail_ok=$(printf '%s' "$otel_fail" | sed 's/^\[OTEL\] //' | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('bad'); sys.exit()
a = d.get('attributes', {})
print('ok' if a.get('gate.decision') == 'fail' and len(a.get('gate.reasons', [])) >= 1 else 'bad')
" 2>/dev/null || echo "bad")
assert_eq "ok" "$fail_ok" "FAIL gate emits gate.decision=fail + reasons"

# Canonical lowercase gate_decision field passes straight through (advisory).
# Carries `result` too so the (un-migrated) Statement composer still accepts the
# envelope; the OTel block reads gate_decision first, so advisory wins over result.
otel_adv=$(echo '{"gate_id":"g5","result":"PASS","gate_decision":"advisory","input_hash":"sha256:aa","policy_hash":"sha256:bb","advisory_severity":"warn"}'  | AUDIT_HARNESS_OTEL=1 bash "$EMIT" 2>&1 >/dev/null | grep '"name":"gate.decision.emitted"' || true)
adv_ok=$(printf '%s' "$otel_adv" | sed 's/^\[OTEL\] //' | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('bad'); sys.exit()
a = d.get('attributes', {})
print('ok' if a.get('gate.decision') == 'advisory' else 'bad')
" 2>/dev/null || echo "bad")
assert_eq "ok" "$adv_ok" "advisory gate_decision passes through to gate.decision=advisory"

# Both events fire from one evaluation (evaluated + decision).
both=$(echo '{"gate_id":"g3","result":"PASS","input_hash":"sha256:aa","policy_hash":"sha256:bb"}'  | AUDIT_HARNESS_OTEL=1 bash "$EMIT" 2>&1 >/dev/null | grep -c '\[OTEL\]' || true)
assert_eq "2" "$both" "exactly two OTel events fire (evaluated + gate.decision.emitted)"

# OTel is best-effort: with no collector signal the path is a silent no-op.
none=$(echo '{"gate_id":"g4","result":"PASS","input_hash":"sha256:aa","policy_hash":"sha256:bb"}'  | bash "$EMIT" 2>&1 >/dev/null | grep -c '\[OTEL\]' || true)
assert_eq "0" "$none" "collector-absent path is a silent no-op (iah-E07c)"

# ---------------------------------------------------------------------------
echo
echo "cred-gate + OTel-decision suite: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
