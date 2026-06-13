#!/usr/bin/env bash
# dnssec-check.sh — verify a namespace is DNSSEC-signed before a production
# signed attestation is anchored against it.
#
# WHY THIS EXISTS (CISO binding, DR-010 Q5 / ISEDC v1 Q1 2026-05-10):
#   Predicate URIs for the Evidence Bundle live ONLY at evals.intentsolutions.io.
#   Pushing a signed in-toto Statement to a PUBLIC transparency log (Rekor)
#   against an unsigned namespace is irreversible and lets an attacker who can
#   spoof the zone mint look-alike attestations. DNSSEC must be verified on the
#   namespace BEFORE the first production attestation. This script is that gate.
#   It anchors NOTHING — it is a read-only verification that can only make
#   signing MORE conservative (fail-closed).
#
# Usage:
#   bash scripts/dnssec-check.sh [DOMAIN]
#   DNSSEC_CHECK_DOMAIN=evals.intentsolutions.io bash scripts/dnssec-check.sh
#
# Resolution order for the domain:
#   1. $1 (positional)
#   2. $DNSSEC_CHECK_DOMAIN
#   3. default: evals.intentsolutions.io
#
# Behavior:
#   - Prefers `delv` (does full DNSSEC validation against the chain of trust).
#   - Falls back to `dig +dnssec` and inspects the AD (Authenticated Data) bit
#     plus the presence of RRSIG records.
#   - If NEITHER delv NOR dig is installed, emits a typed UNKNOWN/UNREACHABLE
#     result and exits non-zero (fail-closed for production).
#
# Exit codes:
#   0 — DNSSEC verified (delv "fully validated" OR dig AD bit + RRSIG present)
#   1 — DNSSEC NOT verified (zone unsigned / validation failed)
#   2 — UNKNOWN/UNREACHABLE (no resolver tool, or lookup could not be performed)
#
# Override knobs (for offline self-test):
#   DNSSEC_CHECK_DELV_CMD  — command used in place of `delv` (default: delv)
#   DNSSEC_CHECK_DIG_CMD   — command used in place of `dig`  (default: dig)

set -euo pipefail

DOMAIN="${1:-${DNSSEC_CHECK_DOMAIN:-evals.intentsolutions.io}}"
DELV_CMD="${DNSSEC_CHECK_DELV_CMD:-delv}"
DIG_CMD="${DNSSEC_CHECK_DIG_CMD:-dig}"

log() { printf 'dnssec-check: %s\n' "$1" >&2; }

if [[ "$DOMAIN" == "-h" || "$DOMAIN" == "--help" ]]; then
  sed -n '2,40p' "$0"
  exit 0
fi

have() { command -v "$1" >/dev/null 2>&1; }

# --- Path 1: delv (authoritative DNSSEC chain validation) ---
if have "$DELV_CMD"; then
  log "validating DNSSEC for '$DOMAIN' via $DELV_CMD"
  # delv prints "; fully validated" on each validated RRset when the chain of
  # trust holds; "; unsigned answer" / "resolution failed" otherwise.
  delv_out="$("$DELV_CMD" "$DOMAIN" 2>&1 || true)"
  if printf '%s\n' "$delv_out" | grep -q "fully validated"; then
    log "VERIFIED — '$DOMAIN' is DNSSEC-signed (delv: fully validated)"
    exit 0
  fi
  if printf '%s\n' "$delv_out" | grep -qiE "unsigned answer|insecurity proof|chain of trust"; then
    log "NOT VERIFIED — '$DOMAIN' appears unsigned / unvalidated (delv)"
    exit 1
  fi
  # delv ran but gave neither a clear pass nor a clear unsigned answer; fall
  # through to dig for a second opinion rather than silently passing.
  log "delv result inconclusive for '$DOMAIN'; consulting dig"
fi

# --- Path 2: dig +dnssec (AD bit + RRSIG presence) ---
if have "$DIG_CMD"; then
  log "checking DNSSEC for '$DOMAIN' via $DIG_CMD +dnssec"
  # The AD (Authenticated Data) flag in the response header means the validating
  # resolver authenticated the answer. RRSIG records in the answer/authority
  # section confirm the zone publishes signatures. We require BOTH signals.
  dig_out="$("$DIG_CMD" +dnssec +multiline "$DOMAIN" 2>&1 || true)"

  ad_flag=0
  if printf '%s\n' "$dig_out" | grep -qE '^;; flags:[^;]*\bad\b'; then
    ad_flag=1
  fi

  rrsig=0
  if printf '%s\n' "$dig_out" | grep -qE '[[:space:]]RRSIG[[:space:]]'; then
    rrsig=1
  fi

  if [[ "$ad_flag" -eq 1 && "$rrsig" -eq 1 ]]; then
    log "VERIFIED — '$DOMAIN' is DNSSEC-signed (dig: AD bit set + RRSIG present)"
    exit 0
  fi

  if [[ "$rrsig" -eq 1 && "$ad_flag" -eq 0 ]]; then
    log "NOT VERIFIED — RRSIG present but resolver did not set AD bit for '$DOMAIN'"
    log "  (the local resolver may not be validating; query a validating resolver, e.g. +tcp @1.1.1.1)"
    exit 1
  fi

  log "NOT VERIFIED — no DNSSEC signatures found for '$DOMAIN' (zone appears unsigned)"
  exit 1
fi

# --- Path 3: no resolver tool available -> typed UNKNOWN, fail-closed ---
log "UNKNOWN/UNREACHABLE — neither '$DELV_CMD' nor '$DIG_CMD' is installed"
log "  cannot verify DNSSEC for '$DOMAIN'; failing closed (production must not sign on UNKNOWN)"
log "  remediation: install bind9-dnsutils (provides dig + delv) on the signing host"
exit 2
