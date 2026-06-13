#!/usr/bin/env bash
# DNS pre-flight LIVE suite — proves the DNSSEC + CAA production-signing gate
# (iah-E06, CISO binding DR-010 Q5) against REAL DNS using a trusted validating
# resolver, AND proves it stays fail-closed on known-bad inputs.
#
# WHY THIS EXISTS (the bug this suite guards against):
#   scripts/dnssec-check.sh + scripts/caa-check.sh used to query the LOCAL STUB
#   RESOLVER (plain `dig`, no `@server`). On hosts whose stub resolver strips
#   DNSSEC records or lags CAA (systemd-resolved, most CI runners, this dev box)
#   they FALSE-NEGATIVE on a correctly-configured zone — refusing a legitimate
#   production sign. The fix queries a TRUSTED VALIDATING/PUBLIC resolver
#   (1.1.1.1 / 8.8.8.8) and requires positive validation. This suite proves both
#   that the fix passes a genuinely-signed+pinned zone AND that fail-closed is
#   preserved against unsigned / wrong-issuer / unreachable / no-tool inputs.
#
# It complements (does NOT replace) the OFFLINE hermetic suite
# run-dns-preflight-tests.sh, which stubs the resolver and runs in CI with no
# network. THIS suite needs outbound DNS to 1.1.1.1/8.8.8.8 (UDP/TCP 53). If the
# network is unavailable it SKIPS (exit 0) rather than producing a false FAIL —
# it is a live confidence check, not a hermetic gate.
#
#   bash tests/dns-preflight/run-dns-preflight-live-tests.sh
#   exit 0 = all green (or skipped, no network); exit 1 = an assertion failed.
#
# Override knobs:
#   DNS_LIVE_SIGNED_DOMAIN   — a genuinely DNSSEC-signed + LE-CAA-pinned zone
#                              (default: evals.intentsolutions.io)
#   DNS_LIVE_UNSIGNED_DOMAIN — a zone with NO DNSSEC (default: neverssl.com)
#   DNS_LIVE_WRONGCAA_DOMAIN — a zone with CAA that does NOT pin letsencrypt
#                              (default: google.com — pins pki.goog only)

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$ROOT/scripts"

SIGNED_DOMAIN="${DNS_LIVE_SIGNED_DOMAIN:-evals.intentsolutions.io}"
UNSIGNED_DOMAIN="${DNS_LIVE_UNSIGNED_DOMAIN:-neverssl.com}"
WRONGCAA_DOMAIN="${DNS_LIVE_WRONGCAA_DOMAIN:-google.com}"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

run_ec() { # runs "$@", echoes its exit code, swallows output
  local ec=0
  "$@" >/dev/null 2>&1 || ec=$?
  echo "$ec"
}

assert_eq() { if [[ "$2" -eq "$1" ]]; then pass "$3"; else fail "$3 (expected $1, got $2)"; fi; }
assert_ne() { if [[ "$2" -ne "$1" ]]; then pass "$3"; else fail "$3 (got the forbidden value $1)"; fi; }

# --- Preconditions: need dig + outbound DNS to a public resolver ---
if ! command -v dig >/dev/null 2>&1; then
  echo "▶ DNS pre-flight LIVE suite — SKIPPED (no \`dig\`; offline suite covers the logic)"
  exit 0
fi
if ! dig +time=3 +tries=1 +short A "$SIGNED_DOMAIN" @1.1.1.1 >/dev/null 2>&1; then
  echo "▶ DNS pre-flight LIVE suite — SKIPPED (no outbound DNS to 1.1.1.1; offline suite covers the logic)"
  exit 0
fi

echo "▶ DNS pre-flight LIVE suite (real DNS via trusted resolvers 1.1.1.1 / 8.8.8.8)"
echo "  signed+pinned: $SIGNED_DOMAIN | unsigned: $UNSIGNED_DOMAIN | wrong-CAA: $WRONGCAA_DOMAIN"

# 1. PASS — genuinely DNSSEC-signed zone validates -> exit 0
ec=$(run_ec bash "$SCRIPTS/dnssec-check.sh" "$SIGNED_DOMAIN")
assert_eq 0 "$ec" "dnssec: signed zone '$SIGNED_DOMAIN' validates via trusted resolver -> exit 0"

# 2. PASS — CAA present + pins letsencrypt.org -> exit 0
ec=$(EXPECTED_CAA_ISSUER="letsencrypt.org" run_ec bash "$SCRIPTS/caa-check.sh" "$SIGNED_DOMAIN")
assert_eq 0 "$ec" "caa: '$SIGNED_DOMAIN' pins letsencrypt.org via trusted resolver -> exit 0"

# 3a. FAIL-CLOSED — unsigned zone -> exit 1 (NOT a false pass)
ec=$(run_ec bash "$SCRIPTS/dnssec-check.sh" "$UNSIGNED_DOMAIN")
assert_eq 1 "$ec" "dnssec: unsigned zone '$UNSIGNED_DOMAIN' -> exit 1 (fail-closed)"

# 3b. FAIL-CLOSED — CAA exists but does NOT pin letsencrypt.org -> exit 1
ec=$(EXPECTED_CAA_ISSUER="letsencrypt.org" run_ec bash "$SCRIPTS/caa-check.sh" "$WRONGCAA_DOMAIN")
assert_eq 1 "$ec" "caa: '$WRONGCAA_DOMAIN' CAA present but not LE, expect LE -> exit 1 (fail-closed)"

# 3c. FAIL-CLOSED — no reachable resolver (unroutable TEST-NET-1 192.0.2.1) -> exit 1
ec=$(DNSSEC_CHECK_RESOLVERS="192.0.2.1" run_ec bash "$SCRIPTS/dnssec-check.sh" "$SIGNED_DOMAIN")
assert_eq 1 "$ec" "dnssec: no reachable resolver -> exit 1 (fail-closed, not a silent pass)"
ec=$(CAA_CHECK_RESOLVERS="192.0.2.1" run_ec bash "$SCRIPTS/caa-check.sh" "$SIGNED_DOMAIN")
assert_eq 1 "$ec" "caa: no reachable resolver -> exit 1 (fail-closed, not a silent pass)"

# 3d. FAIL-CLOSED — no resolver tool installed at all -> exit 2 (UNKNOWN)
ec=$(DNSSEC_CHECK_DELV_CMD="/nonexistent/delv" DNSSEC_CHECK_DIG_CMD="/nonexistent/dig" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" "$SIGNED_DOMAIN")
assert_eq 2 "$ec" "dnssec: no resolver tool -> exit 2 (UNKNOWN, fail-closed)"
ec=$(CAA_CHECK_DIG_CMD="/nonexistent/dig" \
     run_ec bash "$SCRIPTS/caa-check.sh" "$SIGNED_DOMAIN")
assert_eq 2 "$ec" "caa: no resolver tool -> exit 2 (UNKNOWN, fail-closed)"

# 4. SPOOF-RESISTANCE — an answer with RRSIG but NO AD flag (a non-validating /
#    lying resolver) must NOT pass dnssec-check. Stub dig to emit exactly that.
STUB_TMP="$(mktemp -d)"
trap 'rm -rf "$STUB_TMP"' EXIT
cat > "$STUB_TMP/dig-rrsig-no-ad" <<'STUB'
#!/usr/bin/env bash
cat <<'OUT'
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 4242
;; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1
;; ANSWER SECTION:
example.test. 300 IN A 203.0.113.10
example.test. 300 IN RRSIG A 13 3 300 20990101 20200101 1234 example.test. abcd==
OUT
STUB
chmod +x "$STUB_TMP/dig-rrsig-no-ad"
ec=$(DNSSEC_CHECK_DELV_CMD="/nonexistent/delv" \
     DNSSEC_CHECK_DIG_CMD="$STUB_TMP/dig-rrsig-no-ad" \
     DNSSEC_CHECK_RESOLVERS="1.1.1.1" \
     run_ec bash "$SCRIPTS/dnssec-check.sh" example.test)
assert_ne 0 "$ec" "dnssec: RRSIG present but AD flag UNSET -> does NOT pass (got exit $ec, spoof-resistant)"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "DNS pre-flight LIVE results: PASS=$PASS  FAIL=$FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ "$FAIL" -eq 0 ]]
