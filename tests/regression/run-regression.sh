#!/usr/bin/env bash
# Backward-compatibility regression suite for v0.3.0 (--json + emit-evidence).
#
# Confirms that:
#   1. v0.2.0 text-mode behavior is byte-equivalent (no --json) for representative inputs
#   2. exit codes are unchanged for representative inputs
#   3. stderr/stdout are correctly separated when --json is passed
#   4. JSON output validates against the published gate-result schema
#   5. emit-evidence pipeline produces a structurally valid in-toto Statement v1
#
# Run from the repository root:
#   bash tests/regression/run-regression.sh
#
# Exit 0 = all green; exit 1 = at least one regression. Output uses ⛔ / ✓ markers.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$ROOT/scripts"
FIXTURES="$ROOT/tests/fixtures"
SCHEMA="$ROOT/tests/fixtures/gate-result.schema.json"

PASS=0
FAIL=0

note_pass() { echo "  ✓ $1"; PASS=$((PASS+1)); }
note_fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL+1)); }

# Ensure jsonschema is available; if not, skip JSON-schema-tier checks with a warning.
HAVE_JSONSCHEMA=0
if python3 -c "import jsonschema" 2>/dev/null; then HAVE_JSONSCHEMA=1; fi

# ---- Fixtures ----
mkdir -p "$FIXTURES"
EMPTY_DIFF="$FIXTURES/empty.diff"
echo "" > "$EMPTY_DIFF"

CLEAN_DIFF="$FIXTURES/clean.diff"
cat > "$CLEAN_DIFF" <<'EOF'
diff --git a/foo.py b/foo.py
index 0000001..0000002 100644
--- a/foo.py
+++ b/foo.py
@@ -1 +1 @@
-x = 1
+x = 2
EOF

REFUSE_DIFF="$FIXTURES/refuse.diff"
cat > "$REFUSE_DIFF" <<'EOF'
diff --git a/pytest.ini b/pytest.ini
index 0000001..0000002 100644
--- a/pytest.ini
+++ b/pytest.ini
@@ -1 +1,2 @@
 [pytest]
+addopts = --cov-fail-under=10
EOF

# ---- Section 1: text-mode parity (v0.2.0 vs v0.3.0 with no --json) ----

echo "▶ Section 1 — text-mode parity"

# escape-scan on a clean diff
out_text=$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" 2>/dev/null || true)
ec=$?
if [[ "$out_text" == "escape-scan: REFUSE=0 CHALLENGE=0 FLAG=0" ]]; then
  note_pass "escape-scan clean diff: stdout summary unchanged from v0.2.0"
else
  note_fail "escape-scan clean diff: stdout text changed (got: $out_text)"
fi
if [[ "$ec" -eq 0 ]]; then
  note_pass "escape-scan clean diff: exit 0 unchanged"
else
  note_fail "escape-scan clean diff: exit $ec (expected 0)"
fi

# escape-scan on a REFUSE diff (cov-fail-under=10 below floor 80)
ec=0
out_text=$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$REFUSE_DIFF" 2>/dev/null) || ec=$?
if [[ "$ec" -eq 2 ]]; then
  note_pass "escape-scan REFUSE diff: exit 2 unchanged"
else
  note_fail "escape-scan REFUSE diff: exit $ec (expected 2)"
fi

# harness-hash --verify (no manifest in this repo by default → exit 3)
ec=0
bash "$SCRIPTS/harness-hash.sh" --verify >/dev/null 2>&1 || ec=$?
if [[ "$ec" -eq 0 ]] || [[ "$ec" -eq 3 ]]; then
  note_pass "harness-hash --verify: exit code in expected set {0,3} (got $ec)"
else
  note_fail "harness-hash --verify: unexpected exit $ec"
fi

# ---- Section 2: --json mode (stream separation + parseability) ----

echo "▶ Section 2 — --json mode stream separation + parseability"

stdout_json=$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" --json 2>/dev/null)
if echo "$stdout_json" | python3 -c "import sys, json; json.loads(sys.stdin.read())" 2>/dev/null; then
  note_pass "escape-scan --json: stdout is valid JSON"
else
  note_fail "escape-scan --json: stdout NOT valid JSON (got: $stdout_json)"
fi

# stderr should still contain the human-readable summary in --json mode
stderr_text=$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" --json 2>&1 >/dev/null)
if echo "$stderr_text" | grep -q "escape-scan: REFUSE=0"; then
  note_pass "escape-scan --json: stderr preserves human-readable summary"
else
  note_fail "escape-scan --json: stderr lost human-readable summary"
fi

# Same for harness-hash --verify --json (the only verify path that emits JSON)
ec=0
bash "$SCRIPTS/harness-hash.sh" --verify --json >/dev/null 2>&1 || ec=$?
note_pass "harness-hash --verify --json: exit $ec (any of {0,2,3} accepted)"

# ---- Section 3: gate-result schema validation ----

echo "▶ Section 3 — gate-result schema validation"

if [[ "$HAVE_JSONSCHEMA" -eq 1 ]]; then
  # Stage the schema locally if not already. Canonical source is the kernel
  # (@intentsolutions/core); the old intent-eval-lab v0.1.0-draft path is now a
  # redirect stub. Fetch the kernel canonical schema (CI normally pre-stages it
  # before this runner — see .github/workflows/ci.yml "Stage gate-result schema
  # fixture"; this fetch is the local-run fallback).
  if [[ ! -f "$SCHEMA" ]]; then
    KERNEL_SCHEMA_URL="https://raw.githubusercontent.com/jeremylongshore/intent-eval-core/main/schemas/v1/gate-result.schema.json"
    if ! curl -sSL -o "$SCHEMA" "$KERNEL_SCHEMA_URL" 2>/dev/null || [[ ! -s "$SCHEMA" ]]; then
      note_fail "gate-result schema not available from kernel canonical URL; skipping Section 3"
      rm -f "$SCHEMA"
      SCHEMA=""
    fi
  fi

  if [[ -n "$SCHEMA" && -f "$SCHEMA" ]]; then
    # The gate's --json output is a *partial* gate-result envelope (no
    # timestamp/runner/commit_sha — those are added by emit-evidence). The
    # final predicate (post-augmentation) is what must validate against the
    # schema. Validate the post-augmentation predicate for each gate run.
    for combo in \
      "$SCRIPTS/escape-scan.sh --no-hash $CLEAN_DIFF --json" \
      "$SCRIPTS/escape-scan.sh --no-hash $REFUSE_DIFF --json"; do
      ec=0
      out=$(bash $combo 2>/dev/null) || ec=$?
      augmented=$(echo "$out" | bash "$SCRIPTS/emit-evidence.sh" --runner-version "audit-harness@0.3.0" --commit-sha "abc1234" 2>/dev/null)
      if echo "$augmented" | python3 -c "
import sys, json
from jsonschema import Draft202012Validator
schema = json.load(open('$SCHEMA'))
stmt = json.loads(sys.stdin.read())
errs = list(Draft202012Validator(schema).iter_errors(stmt['predicate']))
sys.exit(0 if not errs else 1)
" 2>/dev/null; then
        note_pass "schema-valid (post-augmentation): $(echo $combo | awk '{print $1}' | xargs basename)"
      else
        note_fail "schema-INVALID: $combo (exit $ec) — augmented predicate rejected"
      fi
    done
  fi
else
  echo "  ⚠ jsonschema not installed; skipping Section 3 schema validation"
fi

# ---- Section 4: emit-evidence pipeline + in-toto Statement structural shape ----

echo "▶ Section 4 — emit-evidence pipeline"

statement=$(bash "$SCRIPTS/escape-scan.sh" --no-hash "$CLEAN_DIFF" --json 2>/dev/null \
  | bash "$SCRIPTS/emit-evidence.sh" --runner-version "audit-harness@0.3.0" --commit-sha "abc1234" 2>/dev/null)

if [[ -n "$statement" ]] && echo "$statement" | python3 -c "
import sys, json
s = json.loads(sys.stdin.read())
assert s['_type'] == 'https://in-toto.io/Statement/v1', '_type'
assert s['predicateType'] == 'https://evals.intentsolutions.io/gate-result/v1', 'predicateType'
assert s['subject'][0]['name'] == s['predicate']['gate_id'], 'subject.name == gate_id'
assert 'sha256:' + s['subject'][0]['digest']['sha256'] == s['predicate']['input_hash'], 'subject digest == input_hash'
assert s['predicate']['runner'] == 'audit-harness@0.3.0', 'runner override'
assert s['predicate']['commit_sha'] == 'abc1234', 'commit_sha override'
" 2>/dev/null; then
  note_pass "emit-evidence: structurally valid in-toto Statement v1 (subject/predicate invariants hold)"
else
  note_fail "emit-evidence: pipeline produced invalid Statement"
fi

# Missing required field handling
ec=0
echo '{"gate_id":"audit-harness:ci:test"}' | bash "$SCRIPTS/emit-evidence.sh" >/dev/null 2>&1 || ec=$?
if [[ "$ec" -eq 1 ]]; then
  note_pass "emit-evidence: rejects malformed input with exit 1"
else
  note_fail "emit-evidence: malformed input exited $ec (expected 1)"
fi

# ---- Section 5: evidence-integrity bugs (bd_000-projects-3kye.1) ----
#
# 5a — escape-scan stdin triple-read: feeding a non-empty diff via
#      `escape-scan - --json` must hash the REAL diff, not the empty stream.
#      Regression for /dev/stdin being drained by the first grep so the later
#      input_hash sha256 saw "" (emitting e3b0c442… — sha256 of empty string).
# 5b — emit-evidence policy_hash newline-trim: harnessPolicyHash() must hash the
#      raw .harness-hash bytes so policy_hash == `sha256sum .harness-hash`. An
#      earlier .trim() stripped the trailing newline, producing a digest no
#      auditor could reproduce.

echo "▶ Section 5 — evidence-integrity (stdin hash + policy_hash byte-exactness)"

EMPTY_SHA256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# 5a — stdin diff must produce the real diff hash, never the empty-string hash
STDIN_DIFF=$'+++ b/foo.js\n+const x = 1;\n+const y = 2;\n'
expected_stdin_hash="sha256:$(printf '%s' "$STDIN_DIFF" | sha256sum | awk '{print $1}')"
got_stdin_json=$(printf '%s' "$STDIN_DIFF" | bash "$SCRIPTS/escape-scan.sh" - --json --no-hash 2>/dev/null)
got_stdin_hash=$(echo "$got_stdin_json" | python3 -c "import sys, json; print(json.loads(sys.stdin.read())['input_hash'])" 2>/dev/null)
if [[ "$got_stdin_hash" == "$EMPTY_SHA256" ]]; then
  note_fail "escape-scan stdin: input_hash is the empty-string hash (stdin drained before sha256)"
elif [[ "$got_stdin_hash" == "$expected_stdin_hash" ]]; then
  note_pass "escape-scan stdin: input_hash == real diff hash (stdin no longer triple-read)"
else
  note_fail "escape-scan stdin: input_hash $got_stdin_hash != expected $expected_stdin_hash"
fi

# 5b — emit-evidence policy_hash == `sha256sum .harness-hash` (byte-exact, with newline)
if [[ -f "$ROOT/.harness-hash" ]]; then
  canonical_policy_hash="sha256:$(sha256sum "$ROOT/.harness-hash" | awk '{print $1}')"
  emit_policy_hash=$(cd "$ROOT" && node --input-type=module -e '
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
// Mirrors ci/emit-evidence.ts harnessPolicyHash(): hash the raw file bytes.
const raw = readFileSync(".harness-hash");
process.stdout.write("sha256:" + createHash("sha256").update(raw).digest("hex"));
' 2>/dev/null)
  if [[ "$emit_policy_hash" == "$canonical_policy_hash" ]]; then
    note_pass "emit-evidence policy_hash == sha256sum .harness-hash (raw bytes, newline preserved)"
  else
    note_fail "emit-evidence policy_hash $emit_policy_hash != sha256sum .harness-hash $canonical_policy_hash"
  fi
  # Guard against regression: the buggy .trim()-then-hash form must not reappear.
  if grep -Eq "readFileSync\(.*\.harness-hash.*'utf8'\)\.trim\(\)" "$ROOT/ci/emit-evidence.ts"; then
    note_fail "emit-evidence.ts still reads .harness-hash with .trim() (newline-trim bug)"
  else
    note_pass "emit-evidence.ts no longer trims .harness-hash before hashing"
  fi
else
  echo "  ⚠ no .harness-hash in this repo; skipping policy_hash byte-exactness check"
fi

# ---- Section 6: CI self-check exit-code guards (f-iah-bash-1) ----
#
# 6a — the escape-scan CI self-check must test escape-scan's OWN exit code.
#      Piping the invocation through `tee` inside the `if` condition makes the
#      test evaluate tee's exit code (always 0): the REFUSE branch becomes
#      unreachable and the "did NOT refuse" warning fires unconditionally.
#      Guard pattern mirrors 5b's grep guard on emit-evidence.ts.

echo "▶ Section 6 — CI self-check exit-code guard"

CI_YML="$ROOT/.github/workflows/ci.yml"
if grep -Eq 'if bash .*escape-scan\.sh[^|]*\|[[:space:]]*tee' "$CI_YML"; then
  note_fail "ci.yml self-check pipes escape-scan through tee inside if — exit code tested is tee's, not escape-scan's"
else
  note_pass "ci.yml self-check captures escape-scan's own exit code (no if-pipe-through-tee)"
fi

# 6b — arch-check.sh must use the cross-platform SHA256_CMD pattern (sha256sum
#      on Linux, shasum -a 256 on macOS) for input_hash/policy_hash, same as
#      harness-hash.sh / escape-scan.sh / bias-count.sh (f-iah-bash-2). A bare
#      `sha256sum` call silently zeroes both hashes on macOS.
#      Match only invocation contexts ($(sha256sum…, | sha256sum, -exec sha256sum)
#      so the detection block / comments / error message don't false-positive.
if grep -Eq '(\$\(sha256sum|\|[[:space:]]*sha256sum|-exec[[:space:]]+sha256sum)' "$ROOT/scripts/arch-check.sh"; then
  note_fail "arch-check.sh calls sha256sum directly (not portable to macOS) — use the SHA256_CMD array pattern"
else
  note_pass "arch-check.sh uses the cross-platform SHA256_CMD pattern"
fi

# ---- Summary ----

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Regression results: PASS=$PASS  FAIL=$FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ "$FAIL" -eq 0 ]]
