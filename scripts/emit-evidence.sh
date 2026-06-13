#!/usr/bin/env bash
# emit-evidence.sh — wrap a gate-result JSON envelope in an in-toto Statement v1.
#
# Reads a gate-result envelope JSON document from stdin (or --input), augments it
# with the fields the runner knows (timestamp, runner version, commit_sha), and
# emits a complete in-toto Statement v1 to stdout. Optionally signs the Statement
# via `cosign sign-blob` and/or pushes to the Rekor transparency log.
#
# Per intent-eval-lab/specs/evidence-bundle/v0.1.0-draft/SPEC.md the emitted
# Statement carries predicateType https://evals.intentsolutions.io/gate-result/v1.
#
# Usage:
#   <gate> --json | bash emit-evidence.sh                          # unsigned, prints Statement
#   bash emit-evidence.sh --input gate.json                        # read from file
#   bash emit-evidence.sh --sign --key cosign.key < gate.json      # cosign key-based sign
#   bash emit-evidence.sh --sign --keyless < gate.json             # cosign keyless (Fulcio OIDC)
#   bash emit-evidence.sh --sign --rekor-url https://rekor.sigstore.dev < gate.json
#   bash emit-evidence.sh --output bundle/row.json < gate.json
#
# Flags:
#   --input PATH       Read gate-result JSON from PATH instead of stdin
#   --output PATH      Write Statement (DSSE envelope if --sign) to PATH instead of stdout
#   --sign             Sign the Statement via cosign. Default: --keyless.
#   --keyless          Force cosign keyless signing (OIDC). Default when --sign and no --key.
#   --key PATH         Cosign keyref. Use instead of --keyless.
#   --rekor-url URL    Push the signed attestation to Rekor at URL. Implies --sign.
#                      Default Rekor URL when present without value: https://rekor.sigstore.dev
#   --no-sign          Explicitly skip signing (default behavior; documents the choice)
#   --runner-version V Override the runner version string (default: from package.json)
#   --commit-sha SHA   Override the commit SHA (default: git rev-parse HEAD)
#   --help, -h         Print help
#
# Exit codes:
#   0 — Statement emitted successfully
#   1 — input JSON malformed or missing required fields
#   2 — signing requested but cosign not available
#   3 — Rekor push requested but failed
#   4 — production DNSSEC/CAA pre-flight FAILED (fail-closed; nothing was signed)
#
# CISO gate (per DR-010 Q5 / ISEDC v1 Q1, 2026-05-10): pushing to a PUBLIC
# transparency log (Rekor) against the predicate URI
# https://evals.intentsolutions.io/gate-result/v1 is BLOCKED until DNSSEC + CAA
# records are verified on the namespace. This script ENFORCES that: when a
# production Rekor push is requested (--rekor-url / non-empty REKOR_URL), it runs
# scripts/dnssec-check.sh then scripts/caa-check.sh against the predicate
# namespace and REFUSES to sign (exit 4) if either fails. The gate is read-only —
# it anchors nothing and can only make signing MORE conservative.
#
# Opt-out (NON-PRODUCTION / staging ONLY): EVIDENCE_SKIP_DNS_PREFLIGHT=1 skips the
# pre-flight. It is honored ONLY when no production Rekor push is requested; a
# real Rekor push can NEVER be silently skipped.

set -euo pipefail

# Bash version floor: these gates rely on bash 4+ features. Refuse early with a
# clear message on bash 3.x (e.g. macOS system bash) instead of failing later
# with a cryptic syntax error (jcgw).
[ "${BASH_VERSINFO:-0}" -ge 4 ] || { echo 'audit-harness requires bash >= 4' >&2; exit 3; }

INPUT="-"
OUTPUT=""
SIGN=0
KEYLESS=0
KEYREF=""
REKOR_URL=""
RUNNER_VERSION_OVERRIDE=""
COMMIT_SHA_OVERRIDE=""
PREDICATE_URI="https://evals.intentsolutions.io/gate-result/v1"
STATEMENT_TYPE="https://in-toto.io/Statement/v1"
# The namespace whose DNSSEC + CAA posture gates production attestations. Derived
# from the predicate URI host; overridable for testing via EVIDENCE_PREDICATE_DOMAIN.
PREDICATE_DOMAIN="${EVIDENCE_PREDICATE_DOMAIN:-evals.intentsolutions.io}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)       INPUT="$2"; shift 2 ;;
    --output)      OUTPUT="$2"; shift 2 ;;
    --sign)        SIGN=1; shift ;;
    --keyless)     SIGN=1; KEYLESS=1; shift ;;
    --key)         SIGN=1; KEYREF="$2"; shift 2 ;;
    --rekor-url)
                   SIGN=1
                   if [[ "${2:-}" =~ ^-- ]] || [[ -z "${2:-}" ]]; then
                     REKOR_URL="https://rekor.sigstore.dev"
                     shift
                   else
                     REKOR_URL="$2"
                     shift 2
                   fi
                   ;;
    --no-sign)     SIGN=0; shift ;;
    --runner-version) RUNNER_VERSION_OVERRIDE="$2"; shift 2 ;;
    --commit-sha)  COMMIT_SHA_OVERRIDE="$2"; shift 2 ;;
    --help|-h)     sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "emit-evidence: unknown flag $1" >&2; exit 1 ;;
  esac
done

# --- Read input ---
if [[ "$INPUT" == "-" ]]; then
  GATE_JSON=$(cat)
else
  if [[ ! -r "$INPUT" ]]; then
    echo "emit-evidence: cannot read $INPUT" >&2
    exit 1
  fi
  GATE_JSON=$(cat "$INPUT")
fi

if [[ -z "$GATE_JSON" ]]; then
  echo "emit-evidence: empty input" >&2
  exit 1
fi

# --- Resolve runner + commit metadata ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_JSON="${SCRIPT_DIR}/../package.json"

if [[ -n "$RUNNER_VERSION_OVERRIDE" ]]; then
  RUNNER="$RUNNER_VERSION_OVERRIDE"
elif [[ -f "$PKG_JSON" ]]; then
  # Pass PKG_JSON via argv so paths with quotes/spaces/specials don't break the python source.
  VER=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['version'])" "$PKG_JSON" 2>/dev/null || echo "unknown")
  RUNNER="audit-harness@${VER}"
else
  RUNNER="audit-harness@unknown"
fi

if [[ -n "$COMMIT_SHA_OVERRIDE" ]]; then
  COMMIT_SHA="$COMMIT_SHA_OVERRIDE"
else
  COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "0000000")
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# --- Compose the Statement via python (deterministic JSON shape, escaping handled) ---
STATEMENT=$(GATE_JSON="$GATE_JSON" PREDICATE_URI="$PREDICATE_URI" STATEMENT_TYPE="$STATEMENT_TYPE" \
  RUNNER="$RUNNER" COMMIT_SHA="$COMMIT_SHA" TIMESTAMP="$TIMESTAMP" \
  python3 - <<'PY'
import json, os, sys

gate = json.loads(os.environ["GATE_JSON"])

required = ["gate_id", "result", "input_hash", "policy_hash"]
missing = [k for k in required if k not in gate]
if missing:
    sys.stderr.write(f"emit-evidence: gate-result missing required keys: {missing}\n")
    sys.exit(1)

# Augment predicate with runner-supplied fields
predicate = {
    "gate_id":     gate["gate_id"],
    "result":      gate["result"],
    "policy_hash": gate["policy_hash"],
    "input_hash":  gate["input_hash"],
    "timestamp":   os.environ["TIMESTAMP"],
    "runner":      os.environ["RUNNER"],
    "commit_sha":  os.environ["COMMIT_SHA"],
}

# Carry forward optional fields if present
for opt in ("metadata", "failure_mode", "advisory_severity"):
    if opt in gate:
        predicate[opt] = gate[opt]

# Subject naming: subject.name MUST equal predicate.gate_id (SPEC § 6 R8)
# Subject digest: subject.digest.sha256 MUST equal predicate.input_hash (SPEC § 6 R9)
input_hash = gate["input_hash"]
if not input_hash.startswith("sha256:"):
    sys.stderr.write(f"emit-evidence: input_hash must be sha256:-prefixed, got: {input_hash}\n")
    sys.exit(1)
digest_hex = input_hash[len("sha256:"):]

statement = {
    "_type":         os.environ["STATEMENT_TYPE"],
    "subject":       [{
        "name":   gate["gate_id"],
        "digest": {"sha256": digest_hex},
    }],
    "predicateType": os.environ["PREDICATE_URI"],
    "predicate":     predicate,
}

print(json.dumps(statement))
PY
)

if [[ -z "$STATEMENT" ]]; then
  echo "emit-evidence: failed to compose Statement" >&2
  exit 1
fi

# --- OTel events (best-effort no-op if collector absent) ---
# Two events fire under the agent.rollout.gate.* namespace per the OTel RFC draft
# intent-eval-lab/000-docs/001-DR-RFC-otel-agent-rollout-gate-signals-draft.md § Events:
#
#   1. agent.rollout.gate.evaluated  (iah-E07a) — fired at the start/observation
#      of a gate evaluation. Carries the raw gate identity + result.
#   2. agent.rollout.gate.decision   (iah-E07b) — fired at the END of the gate
#      evaluation. Carries the ship/no-ship terminal decision the gate-result
#      maps to, plus the reasons array. This is the second OTel event the RFC
#      enumerates and the one a ship-gate dashboard actually alerts on.
#
# ATTRIBUTE-SPELLING AUTHORITY (do NOT redefine here): the canonical attribute
# names are pinned by the kernel at
# intent-eval-core/schemas/v1/otel-attributes.yaml — OTel-idiomatic dotted
# lowercase (e.g. gate.decision). We spell every attribute to match that file;
# the RFC draft above is the EVENT-NAME authority (agent.rollout.gate.decision)
# and supplies the closed decision enum {ship, no-ship} + the reasons array.
#
# We emit OTLP-shaped JSON lines to stderr when AUDIT_HARNESS_OTEL=1 OR an
# OTEL_EXPORTER_OTLP_ENDPOINT is set. Real exporter wiring is consumer-side; we
# emit a structured signal any collector can scrape via stderr capture. The path
# is fully best-effort: a collector being absent is the no-op default, and a
# python failure (||) degrades to an empty line that is simply not printed —
# the gate's own exit status is never affected by OTel emission (iah-E07c).
if [[ "${AUDIT_HARNESS_OTEL:-0}" == "1" ]] || [[ -n "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ]]; then
  # Compose the JSON via python so every attribute value is JSON-escaped.
  # printf-interpolating gate_id/result/runner into a JSON format string
  # emitted structurally invalid JSON whenever a value carried a double quote
  # (e.g. AUDIT_HARNESS_SIDE='ci"injection' flowing into gate_id).
  OTEL_LINES=$(GATE_JSON="$GATE_JSON" RUNNER="$RUNNER" COMMIT_SHA="$COMMIT_SHA" TIMESTAMP="$TIMESTAMP" \
    python3 - <<'PY' 2>/dev/null || echo ""
import json, os
try:
    gate = json.loads(os.environ["GATE_JSON"])
except (json.JSONDecodeError, ValueError):
    gate = {}

runner = os.environ["RUNNER"]
commit_sha = os.environ["COMMIT_SHA"]
timestamp = os.environ["TIMESTAMP"]
gate_id = str(gate.get("gate_id", ""))
gate_result = str(gate.get("result", ""))

# Event 1: agent.rollout.gate.evaluated (iah-E07a, unchanged shape).
evaluated = {
    "name": "agent.rollout.gate.evaluated",
    "attributes": {
        "gate.id": gate_id,
        "gate.result": gate_result,
        "gate.runner": runner,
        "gate.commit_sha": commit_sha,
    },
    "timestamp": timestamp,
}

# Event 2: agent.rollout.gate.decision (iah-E07b). Map the gate-result enum to
# the RFC's closed {ship, no-ship} decision enum. A single gate emitting its own
# row maps PASS -> ship and anything else -> no-ship; INDETERMINATE rows are a
# no-ship from a hard ship-gate's perspective (the gate did not affirm ship).
# The attribute is spelled gate.decision per the kernel otel-attributes.yaml
# pin; the RFC supplies the enum + the reasons array.
result_upper = gate_result.upper()
decision = "ship" if result_upper == "PASS" else "no-ship"
reasons = []
if decision == "ship":
    reasons.append(f"gate '{gate_id}' returned PASS")
else:
    reasons.append(
        f"gate '{gate_id}' returned {gate_result or 'NO_RESULT'} (not PASS)"
    )
fm = gate.get("failure_mode")
if fm:
    reasons.append(f"failure_mode: {fm}")

decision_event = {
    "name": "agent.rollout.gate.decision",
    "attributes": {
        "gate.id": gate_id,
        "gate.decision": decision,
        "gate.reasons": reasons,
        "gate.runner": runner,
        "gate.commit_sha": commit_sha,
    },
    "timestamp": timestamp,
}

for ev in (evaluated, decision_event):
    print(json.dumps(ev, separators=(",", ":")))
PY
)
  # Print each emitted OTLP line with the [OTEL] marker the collector scrapes.
  if [[ -n "$OTEL_LINES" ]]; then
    while IFS= read -r _otel_line; do
      [[ -n "$_otel_line" ]] && printf '[OTEL] %s\n' "$_otel_line" >&2
    done <<< "$OTEL_LINES"
  fi
fi

# --- Sign + emit ---
emit() {
  local content="$1"
  if [[ -n "$OUTPUT" ]]; then
    mkdir -p "$(dirname "$OUTPUT")"
    printf '%s\n' "$content" > "$OUTPUT"
    echo "emit-evidence: wrote $OUTPUT" >&2
  else
    printf '%s\n' "$content"
  fi
}

if [[ "$SIGN" -eq 0 ]]; then
  emit "$STATEMENT"
  exit 0
fi

# Signing requires cosign. We use `cosign attest-blob` if available (canonical
# in-toto signing), falling back to `cosign sign-blob` with the Statement as the
# blob (less canonical but functional for verification round-trip).
if ! command -v cosign >/dev/null 2>&1; then
  echo "emit-evidence: --sign requested but cosign is not installed (https://docs.sigstore.dev/cosign/installation/)" >&2
  exit 2
fi

# --- Production DNSSEC + CAA pre-flight gate (CISO binding DR-010 Q5) ----------
# A "production" signing event is one that pushes a signed Statement to a PUBLIC
# transparency log (Rekor) — i.e. REKOR_URL is non-empty. Before that irreversible
# anchor, the predicate namespace MUST be DNSSEC-signed AND CAA-pinned. We run the
# two read-only checks; if EITHER fails we REFUSE to sign and exit 4.
#
# The opt-out EVIDENCE_SKIP_DNS_PREFLIGHT=1 is honored ONLY for non-production
# (no Rekor push). A real Rekor push can never be silently skipped.
if [[ -n "$REKOR_URL" ]]; then
  PREFLIGHT_DIR="$(cd "$(dirname "$0")" && pwd)"
  if [[ "${EVIDENCE_SKIP_DNS_PREFLIGHT:-0}" == "1" ]]; then
    echo "emit-evidence: IGNORING EVIDENCE_SKIP_DNS_PREFLIGHT=1 — a Rekor push (REKOR_URL=$REKOR_URL) is a production attestation and CANNOT skip the DNSSEC/CAA pre-flight." >&2
  fi
  echo "emit-evidence: production Rekor push requested — running DNSSEC + CAA pre-flight on '$PREDICATE_DOMAIN'" >&2

  if ! bash "$PREFLIGHT_DIR/dnssec-check.sh" "$PREDICATE_DOMAIN" >&2; then
    echo "emit-evidence: REFUSING TO SIGN — DNSSEC pre-flight FAILED for '$PREDICATE_DOMAIN'." >&2
    echo "emit-evidence: remediation: pin DNSSEC + CAA on $PREDICATE_DOMAIN before any production attestation." >&2
    echo "emit-evidence:   see intent-eval-platform/intent-eval-lab/000-docs (DR-010 Q5 CISO binding) + the iah-E06 runbook." >&2
    exit 4
  fi
  if ! bash "$PREFLIGHT_DIR/caa-check.sh" "$PREDICATE_DOMAIN" >&2; then
    echo "emit-evidence: REFUSING TO SIGN — CAA pre-flight FAILED for '$PREDICATE_DOMAIN'." >&2
    echo "emit-evidence: remediation: pin DNSSEC + CAA on $PREDICATE_DOMAIN before any production attestation." >&2
    echo "emit-evidence:   set EXPECTED_CAA_ISSUER to the published CA, then publish a CAA record pinning it." >&2
    exit 4
  fi
  echo "emit-evidence: DNSSEC + CAA pre-flight PASSED for '$PREDICATE_DOMAIN' — proceeding to sign." >&2
elif [[ "${EVIDENCE_SKIP_DNS_PREFLIGHT:-0}" == "1" ]]; then
  # Non-production sign (no Rekor push) with the explicit opt-out set: keep
  # existing staging flows green without running the network-bound checks.
  echo "emit-evidence: non-production sign (no Rekor push); DNSSEC/CAA pre-flight skipped per EVIDENCE_SKIP_DNS_PREFLIGHT=1." >&2
fi

# Stage the Statement to a temp file for cosign to consume
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
STATEMENT_FILE="$TMP/statement.json"
printf '%s\n' "$STATEMENT" > "$STATEMENT_FILE"
ENVELOPE_FILE="$TMP/envelope.dsse.json"

COSIGN_ARGS=("attest-blob" "--predicate" "$STATEMENT_FILE" "--type" "$PREDICATE_URI")
if [[ -n "$KEYREF" ]]; then
  COSIGN_ARGS+=("--key" "$KEYREF")
elif [[ "$KEYLESS" -eq 1 ]] || [[ -z "$KEYREF" ]]; then
  COSIGN_ARGS+=("--yes")   # accept Fulcio OIDC keyless
fi
if [[ -n "$REKOR_URL" ]]; then
  COSIGN_ARGS+=("--rekor-url" "$REKOR_URL")
  COSIGN_ARGS+=("--tlog-upload=true")
else
  COSIGN_ARGS+=("--tlog-upload=false")
fi
COSIGN_ARGS+=("--output-signature" "$ENVELOPE_FILE")
# `cosign attest-blob` needs a "blob" — the input the predicate attests to.
# Per SPEC subject naming, that's the input_hash; we use a virtual artifact name.
ARTIFACT_NAME="$(echo "$STATEMENT" | python3 -c "import json,sys; print(json.load(sys.stdin)['subject'][0]['name'])")"

# Write a placeholder blob whose sha256 == the declared input_hash. This makes
# the DSSE envelope's subject coherent with the predicate.
# (Cosign re-hashes the blob; we trust the gate's input_hash to be the canonical
# subject. For v0.x we accept this round-trip-by-construction.)
BLOB_FILE="$TMP/$ARTIFACT_NAME.blob"
# A real subject artifact would be the file the gate evaluated; for the envelope
# we use the in-band predicate as the blob. Verification only needs the DSSE
# wrap + the predicate, not the original artifact bytes.
cp "$STATEMENT_FILE" "$BLOB_FILE"

if ! cosign "${COSIGN_ARGS[@]}" "$BLOB_FILE" >&2; then
  echo "emit-evidence: cosign signing failed" >&2
  exit 3
fi

emit "$(cat "$ENVELOPE_FILE")"
echo "emit-evidence: signed envelope emitted${REKOR_URL:+ (Rekor: $REKOR_URL)}" >&2
exit 0
