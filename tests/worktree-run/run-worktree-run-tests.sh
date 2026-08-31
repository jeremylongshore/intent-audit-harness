#!/usr/bin/env bash
# Contract suite for scripts/worktree-run.sh — the pre-push worktree gate.
#
# Deterministic + offline: every case runs in a throwaway git repo under mktemp.
# Pins the four behaviours the runner advertises:
#   1. clean range        -> exit 0, gate-result rows written OUTSIDE the repo
#   2. threshold-lowering -> non-zero exit (escape-scan blocks the push)
#   3. kill-switch        -> AUDIT_HARNESS_DISABLE=1 exits 0 without gating
#   4. no side effects    -> working tree untouched, disposable worktree removed
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER="$HARNESS_ROOT/scripts/worktree-run.sh"

PASS=0
FAIL=0
note() { echo "  $*" >&2; }
ok()   { PASS=$((PASS+1)); echo "ok   - $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL - $*"; }

# ---- throwaway repo ---------------------------------------------------------
SANDBOX="$(mktemp -d -t worktree-run-tests.XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT
REPO="$SANDBOX/repo"
mkdir -p "$REPO/tests"
cd "$REPO"
git init -q
git config user.email test@example.invalid
git config user.name "contract-suite"
git config commit.gpgsign false

cat > tests/TESTING.md <<'EOF'
# Testing policy
coverage.line: 80
EOF
mkdir -p features
cat > features/login.feature <<'EOF'
Feature: Login
  Scenario: valid user signs in
    Given a registered user
    When they submit valid credentials
    Then they see the dashboard
EOF
echo "console.log('hello')" > app.js
git add -A && git commit -qm "base: policy + app"
BASE="$(git rev-parse HEAD)"

# ---- case 1: clean commit -> exit 0 + rows file -----------------------------
echo "console.log('feature')" >> app.js
git add -A && git commit -qm "feat: benign change"
CLEAN="$(git rev-parse HEAD)"
ROWS="$SANDBOX/rows.json"
ec=0
bash "$RUNNER" --ref "$CLEAN" --range "$BASE..$CLEAN" --out "$ROWS" 2>"$SANDBOX/case1.log" || ec=$?
if [[ "$ec" -eq 0 ]]; then ok "clean range exits 0"; else bad "clean range exited $ec"; cat "$SANDBOX/case1.log" >&2; fi
if [[ -s "$ROWS" ]] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$ROWS"; then
  ok "gate-result rows written outside the repo"
else
  bad "rows file missing or not valid JSON: $ROWS"
fi

# ---- case 2: wall-lowering commit (.feature mutation) -> non-zero -----------
# .feature files are human-owned; any diff touching one is a deterministic
# escape-scan REFUSE — the canonical "AI lowered a wall" fixture.
sed -i.bak 's/Then they see the dashboard/Then anything goes/' features/login.feature && rm -f features/login.feature.bak
git add -A && git commit -qm "weaken the acceptance wall"
LOWERED="$(git rev-parse HEAD)"
ec=0
bash "$RUNNER" --ref "$LOWERED" --range "$CLEAN..$LOWERED" --out "$SANDBOX/rows2.json" 2>"$SANDBOX/case2.log" || ec=$?
if [[ "$ec" -eq 2 ]]; then
  ok "wall-lowering range blocked with REFUSE (exit 2)"
else
  bad "wall-lowering range was NOT refused (exit $ec)"; cat "$SANDBOX/case2.log" >&2
fi

# ---- case 3: kill-switch -> exit 0, no gating -------------------------------
ec=0
AUDIT_HARNESS_DISABLE=1 bash "$RUNNER" --ref "$LOWERED" --range "$CLEAN..$LOWERED" 2>"$SANDBOX/case3.log" || ec=$?
if [[ "$ec" -eq 0 ]] && /usr/bin/grep -q "AUDIT_HARNESS_DISABLE" "$SANDBOX/case3.log"; then
  ok "kill-switch skips with exit 0"
else
  bad "kill-switch did not skip cleanly (exit $ec)"
fi

# ---- case 4: no side effects ------------------------------------------------
if [[ -z "$(git status --porcelain)" ]]; then
  ok "working tree untouched after runs"
else
  bad "working tree dirtied: $(git status --porcelain | head -3)"
fi
if [[ "$(git worktree list | wc -l)" -eq 1 ]]; then
  ok "disposable worktrees removed"
else
  bad "leftover worktrees: $(git worktree list)"
fi

echo
echo "worktree-run contract suite: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
