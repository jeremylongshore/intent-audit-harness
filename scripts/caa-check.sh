#!/usr/bin/env bash
# caa-check.sh — verify a namespace publishes CAA records (and, when configured,
# pins the EXPECTED certificate authority) before a production signed attestation
# is anchored against it.
#
# WHY THIS EXISTS (CISO binding, DR-010 Q5 / ISEDC v1 Q1 2026-05-10):
#   CAA (RFC 8659) records constrain which CAs may issue certificates for a
#   namespace. Pinning the CA on evals.intentsolutions.io closes the mis-issuance
#   path an attacker could otherwise use to obtain a look-alike cert and present
#   forged attestation infrastructure. This must be verified BEFORE the first
#   production attestation. This script is that gate — read-only, fail-closed.
#
# Usage:
#   bash scripts/caa-check.sh [DOMAIN]
#   EXPECTED_CAA_ISSUER=letsencrypt.org bash scripts/caa-check.sh evals.intentsolutions.io
#
# Resolution order for the domain:
#   1. $1 (positional)
#   2. $CAA_CHECK_DOMAIN
#   3. default: evals.intentsolutions.io
#
# Issuer policy:
#   - EXPECTED_CAA_ISSUER (env) — when set, at least one CAA `issue` (or
#     `issuewild`) record MUST name this CA, else the check FAILS (exit 1).
#     Default: letsencrypt.org (the CA the IS public-namespace certs are issued
#     by). Override per-deployment.
#   - EXPECTED_CAA_ISSUER=ANY (case-insensitive) — relax to "any CAA record is
#     acceptable"; presence of ANY CAA record passes, absence fails, and a
#     warning is emitted that no specific CA is being pinned.
#
# Exit codes:
#   0 — CAA verified (present, and matches EXPECTED_CAA_ISSUER when a specific
#       issuer is required)
#   1 — CAA NOT verified (no CAA records, or expected issuer not present)
#   2 — UNKNOWN/UNREACHABLE (no resolver tool, or lookup could not be performed)
#
# Override knobs (for offline self-test):
#   CAA_CHECK_DIG_CMD  — command used in place of `dig` (default: dig)

set -euo pipefail

DOMAIN="${1:-${CAA_CHECK_DOMAIN:-evals.intentsolutions.io}}"
EXPECTED_CAA_ISSUER="${EXPECTED_CAA_ISSUER:-letsencrypt.org}"
DIG_CMD="${CAA_CHECK_DIG_CMD:-dig}"

log() { printf 'caa-check: %s\n' "$1" >&2; }

if [[ "$DOMAIN" == "-h" || "$DOMAIN" == "--help" ]]; then
  sed -n '2,42p' "$0"
  exit 0
fi

have() { command -v "$1" >/dev/null 2>&1; }

if ! have "$DIG_CMD"; then
  log "UNKNOWN/UNREACHABLE — '$DIG_CMD' is not installed; cannot look up CAA for '$DOMAIN'"
  log "  failing closed (production must not sign on UNKNOWN)"
  log "  remediation: install bind9-dnsutils (provides dig) on the signing host"
  exit 2
fi

log "looking up CAA records for '$DOMAIN' via $DIG_CMD"
# `dig +short CAA` prints one line per record, e.g.:
#   0 issue "letsencrypt.org"
#   0 issuewild ";"
caa_out="$("$DIG_CMD" +short CAA "$DOMAIN" 2>/dev/null || true)"

# Strip blank lines. CAA can be inherited up the tree per RFC 8659 §3, but for a
# pinning gate we assert the records resolvable at the queried name; absence here
# is treated as "not pinned at this name" -> fail-closed.
if [[ -z "${caa_out//[$' \t\r\n']/}" ]]; then
  log "NOT VERIFIED — no CAA records found for '$DOMAIN'"
  log "  remediation: publish a CAA record pinning the issuing CA, e.g.:"
  log "    $DOMAIN. CAA 0 issue \"$EXPECTED_CAA_ISSUER\""
  exit 1
fi

# --- ANY-issuer relaxation ---
shopt -s nocasematch
if [[ "$EXPECTED_CAA_ISSUER" == "ANY" ]]; then
  shopt -u nocasematch
  log "VERIFIED (presence only) — CAA records exist for '$DOMAIN'"
  log "  WARNING: EXPECTED_CAA_ISSUER=ANY — no specific CA is being pinned."
  log "  Records found:"
  printf '%s\n' "$caa_out" | sed 's/^/    /' >&2
  exit 0
fi
shopt -u nocasematch

# --- Specific-issuer pinning ---
# Match any `issue` or `issuewild` property whose value contains the expected CA.
# CAA values are quoted; we match case-insensitively on the issuer substring.
if printf '%s\n' "$caa_out" \
   | grep -iE '[[:space:]]issue(wild)?[[:space:]]' \
   | grep -iqF "$EXPECTED_CAA_ISSUER"; then
  log "VERIFIED — '$DOMAIN' pins issuance to '$EXPECTED_CAA_ISSUER'"
  exit 0
fi

log "NOT VERIFIED — CAA records exist for '$DOMAIN' but none pin '$EXPECTED_CAA_ISSUER'"
log "  Records found:"
printf '%s\n' "$caa_out" | sed 's/^/    /' >&2
log "  remediation: add a CAA record pinning the expected CA, or set"
log "  EXPECTED_CAA_ISSUER to the CA actually published (or ANY to accept any CAA)."
exit 1
