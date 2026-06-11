#!/usr/bin/env bash
# Golden-master suite for the stdout shapes of the two scorers that emit
# free-form / path-bearing output: `gherkin-lint.sh` (text rubric) and
# `crap-score.py --json` (gate-result envelope).
#
# WHY a golden-master here: these two scripts' stdout is the contract that
# downstream tooling (emit-evidence pipeline, dashboards, the audit-tests
# skill) reads. A silent reshape of that stdout — a renamed field, a dropped
# WARN line, a changed summary wording — is a backward-compat break that the
# per-row schema gate does NOT catch (the schema validates the AUGMENTED
# predicate, not the raw scorer stdout). This suite pins the raw stdout.
#
# DETERMINISM: both scorers carry environment-volatile bytes that are
# normalized out before the diff, so the golden is byte-stable across boxes:
#   - gherkin-lint's first line reports whether the official `gherkin-lint`
#     npm tool is installed (awk-fallback vs installed-linter). CI never
#     installs it; we normalize that line so a dev box with it installed still
#     matches the awk-fallback golden on the rest of the body.
#   - crap-score's `summary_path` is an absolute path under the fixture root;
#     normalized to a <OUT> token. Its `input_hash` is content-derived (stable
#     for a fixed fixture) and `policy_hash` is threshold-derived (stable).
#
# Regenerate the golden files after an INTENTIONAL stdout change:
#   bash tests/golden/run-golden.sh --update
# Review the golden diff in the PR exactly like any other source change.
#
# Run (assert) from the repository root:
#   bash tests/golden/run-golden.sh
# Exit 0 = all green; exit 1 = stdout drifted from a checked-in golden.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GHERKIN="$ROOT/scripts/gherkin-lint.sh"
CRAP="$ROOT/scripts/crap-score.py"
FIX="$ROOT/tests/fixtures/deliberate-failure"
GOLDEN_DIR="$ROOT/tests/golden"

UPDATE=0
[[ "${1:-}" == "--update" ]] && UPDATE=1

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- gherkin-lint normalization ---------------------------------------------
# The deliberate-failure .feature corpus is WRITTEN AT RUNTIME into a tmp dir
# rather than committed: the harness's own escape-scan gate REFUSES any commit
# that touches a `.feature` file (human-owned artifact, scripts/escape-scan.sh
# line ~162), so a checked-in fixture .feature would block the harness
# self-test. Generating it here keeps the corpus deterministic (the heredoc
# below is the source of truth) without tripping that guard. Run from the
# generated features root so WARN/ERROR paths are relative + stable; normalize
# line 1 (installed-vs-awk-fallback) so the golden is environment-independent.
capture_gherkin() {
  local feat_dir="$TMP/features"
  mkdir -p "$feat_dir"
  cat > "$feat_dir/bad.feature" <<'FEATURE'
Feature: Login

  Scenario: User signs in
    And the user clicks the #submit button
    When I type my password into .password-field
    Then I should see the dashboard

  Scenario: Repeated givens without a Background
    Given a user exists
    Given a user exists
    Given a user exists
    When they log in
    Then it works
FEATURE
  ( cd "$TMP" && bash "$GHERKIN" --path features/ 2>/dev/null ) \
    | sed -E 's/^gherkin-lint: (using installed linter|falling back to awk rubric.*)$/gherkin-lint: <LINTER-MODE-NORMALIZED>/'
}

# --- crap-score normalization -----------------------------------------------
# Capture --json stdout against the crap-target fixture with language forced
# (auto-detect would still resolve python via the fixture pyproject, but
# forcing it keeps the golden robust if detection heuristics change). Normalize
# the absolute summary_path to a <OUT> token. crap writes report files under
# --out; point that at a throwaway tmp dir so the suite never dirties the repo.
capture_crap() {
  python3 "$CRAP" --root "$FIX/crap-target" --lang python \
    --out "$TMP/crap-out" --json 2>/dev/null \
    | python3 -c '
import json, sys
d = json.load(sys.stdin)
# Absolute, machine-specific path -> stable token.
d["metadata"]["summary_path"] = "<OUT>/summary.json"
print(json.dumps(d, indent=2, sort_keys=True))
'
}

check() { # $1=name  $2=golden-basename  $3=capture-fn
  local name="$1" golden="$GOLDEN_DIR/$2" fn="$3"
  local live
  live="$($fn)"
  if [[ "$UPDATE" -eq 1 ]]; then
    printf '%s\n' "$live" > "$golden"
    pass "$name: golden regenerated → $2"
    return
  fi
  if [[ ! -f "$golden" ]]; then
    fail "$name: golden file missing ($2) — run with --update to create it"
    return
  fi
  if diff -u "$golden" <(printf '%s\n' "$live") > "$TMP/diff.$2" 2>&1; then
    pass "$name: stdout matches golden"
  else
    fail "$name: stdout DRIFTED from golden ($2)"
    sed 's/^/    /' "$TMP/diff.$2" >&2
  fi
}

echo "golden-master suite (update=$UPDATE)"
echo "▶ gherkin-lint text rubric"
check "gherkin-lint" "gherkin-lint.golden" capture_gherkin
echo "▶ crap-score --json envelope"
check "crap-score" "crap-score.golden" capture_crap

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Golden results: PASS=$PASS  FAIL=$FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ "$FAIL" -eq 0 ]]
