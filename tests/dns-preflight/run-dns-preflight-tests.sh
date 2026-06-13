#!/usr/bin/env bash
# DNS pre-flight suite — OFFLINE proof of the DNSSEC + CAA production-signing gate
# (iah-E06, CISO binding DR-010 Q5).
#
# WHY THIS EXISTS:
#   Production attestations push a signed in-toto Statement to a PUBLIC
#   transparency log (Rekor) against the predicate namespace
#   evals.intentsolutions.io. Before that irreversible anchor, the namespace MUST
#   be DNSSEC-signed AND CAA-pinned. scripts/dnssec-check.sh + scripts/caa-check.sh
#   verify that; scripts/emit-evidence.sh REFUSES to sign (exit 4) if either fails.
#   This suite proves all three behaviors WITHOUT any network access by stubbing
#   the resolver commands (delv/dig) the checks shell out to.
#
# It mirrors the repo's existing runner style (tests/semver, tests/regression):
#   bash tests/dns-preflight/run-dns-preflight-tests.sh
#   exit 0 = all green; exit 1 = at least one assertion failed. ⛔ / ✓ markers.
#
# NOTE: it never reaches the real DNS — every dig/delv invocation is replaced by a
# fixture stub via the *_CMD override knobs the check scripts expose. emit-evidence
# stops at exit 4 (pre-flight REFUSE) BEFORE cosign is invoked, so no signing tool
# is required either.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$ROOT/scripts"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------------------
# Resolver stubs. Each is a tiny executable that prints canned dig/delv output
# and exits 0, exactly as the real tool would for a signed / unsigned zone.
# ---------------------------------------------------------------------------

# delv: fully validated (DNSSEC OK)
DELV_OK="$TMP/delv-ok"
cat > "$DELV_OK" <<'EOF'
#!/usr/bin/env bash
echo "; fully validated"
echo "evals.intentsolutions.io. 300 IN A 203.0.113.10"
echo "evals.intentsolutions.io. 300 IN RRSIG A 13 3 300 ..."
EOF

# delv: unsigned answer (DNSSEC absent)
DELV_BAD="$TMP/delv-bad"
cat > "$DELV_BAD" <<'EOF'
#!/usr/bin/env bash
echo "; unsigned answer"
echo "unsigned.example. 300 IN A 203.0.113.99"
EOF

# dig +dnssec: AD bit set + RRSIG present (signed + validated)
DIG_DNSSEC_OK="$TMP/dig-dnssec-ok"
cat > "$DIG_DNSSEC_OK" <<'EOF'
#!/usr/bin/env bash
cat <<'OUT'
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 4242
;; flags: qr rd ra ad; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1
;; ANSWER SECTION:
evals.intentsolutions.io. 300 IN A 203.0.113.10
evals.intentsolutions.io. 300 IN RRSIG A 13 3 300 20990101 20200101 1234 evals.intentsolutions.io. abcd==
OUT
EOF

# dig +dnssec: no RRSIG, no AD (unsigned zone)
DIG_DNSSEC_BAD="$TMP/dig-dnssec-bad"
cat > "$DIG_DNSSEC_BAD" <<'EOF'
#!/usr/bin/env bash
cat <<'OUT'
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 4242
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; ANSWER SECTION:
unsigned.example. 300 IN A 203.0.113.99
OUT
EOF

# dig +short CAA: pins letsencrypt.org
DIG_CAA_LE="$TMP/dig-caa-le"
cat > "$DIG_CAA_LE" <<'EOF'
#!/usr/bin/env bash
echo '0 issue "letsencrypt.org"'
echo '0 issuewild ";"'
EOF

# dig +short CAA: pins a DIFFERENT CA (digicert)
DIG_CAA_OTHER="$TMP/dig-caa-other"
cat > "$DIG_CAA_OTHER" <<'EOF'
#!/usr/bin/env bash
echo '0 issue "digicert.com"'
EOF

# dig +short CAA: no records (empty)
DIG_CAA_NONE="$TMP/dig-caa-none"
cat > "$DIG_CAA_NONE" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

# A "missing tool" sentinel: a path that does not exist, to drive the
# UNKNOWN/UNREACHABLE (exit 2) branch deterministically.
NO_SUCH="$TMP/definitely-not-installed-xyz"

# Hermetic cosign stub. emit-evidence shells out to `cosign attest-blob` AFTER a
# passed pre-flight. We must NOT hit the real Fulcio/Rekor network in a unit test
# (it hangs). This stub stands in for cosign so the gate's pass/refuse decision is
# observed in isolation: it writes a dummy signature file and exits 0, mimicking a
# successful sign without any network call. It is placed on a dir we prepend to
# PATH only for the emit-evidence production-path tests.
STUB_BIN="$TMP/stubbin"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/cosign" <<'EOF'
#!/usr/bin/env bash
# Minimal hermetic cosign stub: honor --output-signature by writing a dummy
# DSSE-ish blob, never touch the network, always succeed.
out=""
prev=""
for a in "$@"; do
  if [[ "$prev" == "--output-signature" ]]; then out="$a"; fi
  prev="$a"
done
[[ -n "$out" ]] && printf '{"stub":"signature"}\n' > "$out"
exit 0
EOF
chmod +x "$STUB_BIN/cosign"

chmod +x "$DELV_OK" "$DELV_BAD" "$DIG_DNSSEC_OK" "$DIG_DNSSEC_BAD" \
         "$DIG_CAA_LE" "$DIG_CAA_OTHER" "$DIG_CAA_NONE"

run_ec() { # runs "$@", echoes its exit code, swallows output
  local ec=0
  "$@" >/dev/null 2>&1 || ec=$?
  echo "$ec"
}

# assert_eq EXPECTED ACTUAL "label"  — explicit if/else (avoids the A && B || C
# foot-gun shellcheck SC2015 flags) so a mistyped label can never silently pass.
assert_eq() {
  if [[ "$2" -eq "$1" ]]; then pass "$3"; else fail "$3 (expected $1, got $2)"; fi
}
# assert_ne NOT_EXPECTED ACTUAL "label"
assert_ne() {
  if [[ "$2" -ne "$1" ]]; then pass "$3"; else fail "$3 (got the forbidden value $1)"; fi
}

# ===========================================================================
echo "▶ Section 1 — dnssec-check.sh"
# ===========================================================================

# delv says fully validated -> exit 0
ec=$(DNSSEC_CHECK_DELV_CMD="$DELV_OK" DNSSEC_CHECK_DIG_CMD="$NO_SUCH" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" evals.intentsolutions.io)
assert_eq 0 "$ec" "dnssec: delv fully-validated -> exit 0"

# delv unsigned -> exit 1 (delv falls through to dig; dig also unsigned -> 1)
ec=$(DNSSEC_CHECK_DELV_CMD="$DELV_BAD" DNSSEC_CHECK_DIG_CMD="$DIG_DNSSEC_BAD" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" unsigned.example)
assert_eq 1 "$ec" "dnssec: unsigned answer -> exit 1"

# no delv, dig shows AD bit + RRSIG -> exit 0
ec=$(DNSSEC_CHECK_DELV_CMD="$NO_SUCH" DNSSEC_CHECK_DIG_CMD="$DIG_DNSSEC_OK" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" evals.intentsolutions.io)
assert_eq 0 "$ec" "dnssec: dig AD bit + RRSIG -> exit 0"

# no delv, dig shows unsigned -> exit 1
ec=$(DNSSEC_CHECK_DELV_CMD="$NO_SUCH" DNSSEC_CHECK_DIG_CMD="$DIG_DNSSEC_BAD" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" unsigned.example)
assert_eq 1 "$ec" "dnssec: dig no-RRSIG -> exit 1"

# neither tool installed -> UNKNOWN/UNREACHABLE -> exit 2 (fail-closed)
ec=$(DNSSEC_CHECK_DELV_CMD="$NO_SUCH" DNSSEC_CHECK_DIG_CMD="$NO_SUCH" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" evals.intentsolutions.io)
assert_eq 2 "$ec" "dnssec: no resolver tool -> exit 2 (UNKNOWN, fail-closed)"

# ===========================================================================
echo "▶ Section 2 — caa-check.sh"
# ===========================================================================

# expected issuer present -> exit 0
ec=$(EXPECTED_CAA_ISSUER="letsencrypt.org" CAA_CHECK_DIG_CMD="$DIG_CAA_LE" \
     run_ec bash "$SCRIPTS/caa-check.sh" evals.intentsolutions.io)
assert_eq 0 "$ec" "caa: expected issuer pinned -> exit 0"

# expected issuer NOT present (only digicert published) -> exit 1
ec=$(EXPECTED_CAA_ISSUER="letsencrypt.org" CAA_CHECK_DIG_CMD="$DIG_CAA_OTHER" \
     run_ec bash "$SCRIPTS/caa-check.sh" evals.intentsolutions.io)
assert_eq 1 "$ec" "caa: expected issuer absent -> exit 1"

# no CAA records at all -> exit 1
ec=$(EXPECTED_CAA_ISSUER="letsencrypt.org" CAA_CHECK_DIG_CMD="$DIG_CAA_NONE" \
     run_ec bash "$SCRIPTS/caa-check.sh" evals.intentsolutions.io)
assert_eq 1 "$ec" "caa: no CAA records -> exit 1"

# EXPECTED_CAA_ISSUER=ANY with any record present -> exit 0 (presence-only)
ec=$(EXPECTED_CAA_ISSUER="ANY" CAA_CHECK_DIG_CMD="$DIG_CAA_OTHER" \
     run_ec bash "$SCRIPTS/caa-check.sh" evals.intentsolutions.io)
assert_eq 0 "$ec" "caa: ANY issuer + record present -> exit 0"

# no dig at all -> UNKNOWN/UNREACHABLE -> exit 2 (fail-closed)
ec=$(CAA_CHECK_DIG_CMD="$NO_SUCH" \
     run_ec bash "$SCRIPTS/caa-check.sh" evals.intentsolutions.io)
assert_eq 2 "$ec" "caa: no resolver tool -> exit 2 (UNKNOWN, fail-closed)"

# ===========================================================================
echo "▶ Section 3 — emit-evidence.sh production gate wiring"
# ===========================================================================

GATE_JSON='{"gate_id":"audit-harness:ci:dns-preflight","result":"PASS","input_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000","policy_hash":"sha256:1111111111111111111111111111111111111111111111111111111111111111"}'

# Helper: run emit-evidence with stubbed resolvers + a Rekor push requested
# (production). The pre-flight runs and exits 4 BEFORE cosign on the REFUSE path.
# On the PASS path, cosign IS reached — so we prepend the hermetic cosign stub to
# PATH, keeping the whole test offline (no Fulcio/Rekor network call).
emit_prod() { # $1=delv $2=dig_dnssec $3=dig_caa ; echoes exit code
  local ec=0
  echo "$GATE_JSON" | \
    PATH="$STUB_BIN:$PATH" \
    EVIDENCE_PREDICATE_DOMAIN="evals.intentsolutions.io" \
    DNSSEC_CHECK_DELV_CMD="$1" DNSSEC_CHECK_DIG_CMD="$2" \
    CAA_CHECK_DIG_CMD="$3" EXPECTED_CAA_ISSUER="letsencrypt.org" \
    bash "$SCRIPTS/emit-evidence.sh" --rekor-url "https://rekor.sigstore.dev" \
      --runner-version "audit-harness@dns-preflight" --commit-sha "0000000" \
      >/dev/null 2>&1 || ec=$?
  echo "$ec"
}

# 3a. PASS-when-verified: signed zone + pinned CAA. The pre-flight passes; the run
# proceeds to (stubbed) cosign which succeeds -> exit 0. This proves the gate does
# NOT refuse (exit != 4) AND that the happy path reaches signing.
ec=$(emit_prod "$DELV_OK" "$DIG_DNSSEC_OK" "$DIG_CAA_LE")
assert_eq 0 "$ec" "emit-evidence: verified DNSSEC+CAA -> pre-flight PASSES, proceeds to sign (exit 0)"

# 3b. REFUSE-when-DNSSEC-unverified: unsigned zone -> exit 4, before cosign.
ec=$(emit_prod "$DELV_BAD" "$DIG_DNSSEC_BAD" "$DIG_CAA_LE")
assert_eq 4 "$ec" "emit-evidence: unverified DNSSEC -> REFUSE to sign (exit 4)"

# 3c. REFUSE-when-CAA-unverified: signed zone but CAA missing -> exit 4.
ec=$(emit_prod "$DELV_OK" "$DIG_DNSSEC_OK" "$DIG_CAA_NONE")
assert_eq 4 "$ec" "emit-evidence: unverified CAA -> REFUSE to sign (exit 4)"

# 3d. Production push is NOT silently skippable: even with the staging opt-out
# set, an unverified zone + Rekor push still REFUSES (exit 4).
ec=0
echo "$GATE_JSON" | \
  PATH="$STUB_BIN:$PATH" \
  EVIDENCE_SKIP_DNS_PREFLIGHT=1 EVIDENCE_PREDICATE_DOMAIN="evals.intentsolutions.io" \
  DNSSEC_CHECK_DELV_CMD="$DELV_BAD" DNSSEC_CHECK_DIG_CMD="$DIG_DNSSEC_BAD" \
  CAA_CHECK_DIG_CMD="$DIG_CAA_NONE" \
  bash "$SCRIPTS/emit-evidence.sh" --rekor-url "https://rekor.sigstore.dev" \
    --runner-version "audit-harness@dns-preflight" --commit-sha "0000000" \
    >/dev/null 2>&1 || ec=$?
assert_eq 4 "$ec" "emit-evidence: EVIDENCE_SKIP_DNS_PREFLIGHT=1 CANNOT bypass a Rekor push (still exit 4)"

# ===========================================================================
echo "▶ Section 4 — staging flows are NOT broken"
# ===========================================================================

# 4a. Unsigned emit (no --sign) ignores the gate entirely and prints a Statement.
out="$(echo "$GATE_JSON" | bash "$SCRIPTS/emit-evidence.sh" \
        --runner-version "audit-harness@dns-preflight" --commit-sha "0000000" 2>/dev/null)"
if echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['predicateType']=='https://evals.intentsolutions.io/gate-result/v1'" 2>/dev/null; then
  pass "emit-evidence: unsigned emit unaffected by the gate (valid Statement on stdout)"
else
  fail "emit-evidence: unsigned emit broke — no valid Statement on stdout"
fi

# 4b. Local sign WITHOUT a Rekor push (--tlog-upload=false path): the gate does
# NOT run (no REKOR_URL). With the hermetic cosign stub the sign succeeds (exit 0)
# and — critically — the exit is NEVER 4 (the pre-flight refuse code), proving the
# production DNS gate stayed off for a non-Rekor sign.
ec=0
echo "$GATE_JSON" | \
  PATH="$STUB_BIN:$PATH" \
  bash "$SCRIPTS/emit-evidence.sh" --sign --keyless \
    --runner-version "audit-harness@dns-preflight" --commit-sha "0000000" \
    >/dev/null 2>&1 || ec=$?
assert_ne 4 "$ec" "emit-evidence: local sign (no Rekor push) does NOT trigger the DNS gate (exit $ec != 4)"

# ===========================================================================
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "DNS pre-flight results: PASS=$PASS  FAIL=$FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ "$FAIL" -eq 0 ]]
