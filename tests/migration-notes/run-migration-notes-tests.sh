#!/usr/bin/env bash
# Golden suite for `audit-harness migration-notes` (adopter-facing migration-notes
# generator, iah-E05d — the fourth acceptance criterion of the iah-E05 SemVer epic).
#
# Verifies the generator turns CHANGELOG.md + SEMVER.md into traceable adopter
# migration notes, deterministically:
#   1. Default (no arg) -> the latest release; a patch/minor boundary says
#      "no action required" + any_breaking:false.
#   2. A MAJOR release -> any_breaking:true, surfaces the Removed/Changed sections,
#      and appends the SEMVER.md breaking-change rules + "never do" guarantees.
#   3. A minor release -> bump:minor, no Removed/Changed action sections forced.
#   4. Range (--from A --to B] is half-open: A exclusive, B inclusive; a range that
#      crosses a major flags any_breaking:true.
#   5. The Unreleased buffer is never emitted as a release.
#   6. Error handling: unknown version -> exit 1; missing CHANGELOG -> exit 2;
#      inverted range (--from newer than --to) -> exit 1.
#   7. --json envelope shape (schema, any_breaking, versions[].bump, etc.).
#   8. Smoke test against the SHIPPED CHANGELOG.md + SEMVER.md: parses, exit 0,
#      latest version matches package.json.
#
# Run from repo root:  bash tests/migration-notes/run-migration-notes-tests.sh
# Exit 0 = all assertions pass; exit 1 = at least one failed.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GEN="$ROOT/scripts/migration-notes.py"
FIXDIR="$ROOT/tests/fixtures/migration-notes"
FIX_CHANGELOG="$FIXDIR/CHANGELOG.fixture.md"
FIX_SEMVER="$FIXDIR/SEMVER.fixture.md"
SHIPPED_CHANGELOG="$ROOT/CHANGELOG.md"
SHIPPED_SEMVER="$ROOT/SEMVER.md"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Convenience wrapper: always run the generator against the fixture pair.
gen() { python3 "$GEN" --changelog "$FIX_CHANGELOG" --semver "$FIX_SEMVER" "$@"; }

echo "migration-notes golden suite"

# ---- 1: default -> latest release (1.1.0 in the fixture is the newest below 2.0.0?) ----
# The fixture's newest released version is 2.0.0 (major). Default must select it.
o="$TMP/default.json"
if gen --json >"$o" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -ne 0 ]; then fail "default invocation exited $ec (expected 0)"; fi
if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["schema"] == "migration-notes/v1", d["schema"]
assert d["package"] == "@intentsolutions/audit-harness", d["package"]
vs = d["versions"]
assert len(vs) == 1, f"default should be one version, got {len(vs)}"
assert vs[0]["version"] == "2.0.0", f"latest should be 2.0.0, got {vs[0]['version']}"
PY
then pass "default selects the latest released version (2.0.0)"
else fail "default did not select the latest version / envelope malformed"; fi

# ---- 2: a MAJOR release surfaces breaking sections + SEMVER context ----
o="$TMP/major.json"
gen 2.0.0 --json >"$o" 2>/dev/null
if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["any_breaking"] is True, "2.0.0 must be flagged breaking"
v = d["versions"][0]
assert v["bump"] == "major", f"bump should be major, got {v['bump']}"
assert v["prev_version"] == "1.1.0", f"prev should be 1.1.0, got {v['prev_version']}"
secs = v["action_required_sections"]
assert "Removed" in secs, "Removed section must be surfaced"
assert "Changed" in secs, "Changed section must be surfaced"
assert "Added" not in secs, "Added must NOT be an action section (additive)"
ctx = d["semver_context"]
assert any("Remove or rename" in r for r in ctx["major_change_rules"]), "SEMVER major rules missing"
assert any("Re-use a removed subcommand" in n for n in ctx["never_do"]), "SEMVER never-do missing"
PY
then pass "MAJOR release: any_breaking + Removed/Changed surfaced + Added excluded + SEMVER context attached"
else fail "MAJOR release notes wrong"; fi

# Markdown form of the MAJOR notes must include the action-required heading + a rule.
t="$TMP/major.md"
gen 2.0.0 >"$t" 2>/dev/null
if grep -q "Action may be required" "$t" \
   && grep -q "What changed (read before upgrading)" "$t" \
   && grep -q "legacy-scan" "$t" \
   && grep -q "What counts as a breaking change" "$t"; then
  pass "MAJOR Markdown: action banner + change section + SEMVER breaking-change rules rendered"
else fail "MAJOR Markdown missing required sections"; fi

# ---- 3: a minor release is additive (no forced action sections) ----
o="$TMP/minor.json"
gen 1.1.0 --json >"$o" 2>/dev/null
if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["any_breaking"] is False, "1.1.0 is minor, not breaking"
v = d["versions"][0]
assert v["bump"] == "minor", f"bump should be minor, got {v['bump']}"
assert not v["action_required_sections"], "minor must have no action-required sections"
PY
then pass "minor release: not breaking, no action sections"
else fail "minor release classification wrong"; fi

m="$TMP/minor.md"
gen 1.1.0 >"$m" 2>/dev/null
if grep -q "No action required" "$m" && ! grep -q "What counts as a breaking change" "$m"; then
  pass "minor Markdown: 'No action required' banner, no SEMVER breaking-change appendix"
else fail "minor Markdown banner/appendix wrong"; fi

# ---- 4: range semantics — (from, to] half-open; crossing a major flags breaking ----
o="$TMP/range.json"
gen --from 1.0.1 --to 2.0.0 --json >"$o" 2>/dev/null
if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
vs = [v["version"] for v in d["versions"]]
# from=1.0.1 exclusive -> 1.0.1 NOT included; to=2.0.0 inclusive -> included.
assert "1.0.1" not in vs, f"--from is exclusive, 1.0.1 should be excluded: {vs}"
assert vs == ["2.0.0", "1.1.0"], f"range should be [2.0.0, 1.1.0], got {vs}"
assert d["any_breaking"] is True, "range crossing 2.0.0 must be breaking"
PY
then pass "range (from exclusive, to inclusive) + crosses-major -> breaking"
else fail "range semantics wrong"; fi

# ---- 5: the Unreleased buffer is never emitted ----
all_versions="$TMP/all.json"
gen --from 1.0.0 --to 2.0.0 --json >"$all_versions" 2>/dev/null
if python3 - "$all_versions" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
vs = [v["version"].lower() for v in d["versions"]]
assert "unreleased" not in vs, f"Unreleased must never appear: {vs}"
PY
then pass "Unreleased buffer is skipped"
else fail "Unreleased buffer leaked into notes"; fi

# ---- 6: error handling ----
# Helper: assert a command exits with an exact code (avoids the SC2015 A&&B||C
# trap where the C branch can fire even when A succeeded).
assert_exit_code() { # $1=expected  $2=label  shift 2; rest = command
  local expected="$1" label="$2"; shift 2
  local ec=0
  "$@" >/dev/null 2>&1 || ec=$?
  if [ "$ec" -eq "$expected" ]; then
    pass "$label -> exit $expected"
  else
    fail "$label exit was $ec (want $expected)"
  fi
}

assert_exit_code 1 "unknown version" gen 9.9.9
assert_exit_code 2 "missing CHANGELOG" python3 "$GEN" --changelog "$TMP/does-not-exist.md"
assert_exit_code 1 "inverted range" gen --from 2.0.0 --to 1.0.0

# ---- 7: --json envelope completeness for a single version ----
o="$TMP/envelope.json"
gen 1.0.1 --json >"$o" 2>/dev/null
if python3 - "$o" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for key in ("schema", "package", "selection", "any_breaking", "versions", "semver_context"):
    assert key in d, f"envelope missing top-level key: {key}"
v = d["versions"][0]
for key in ("version", "date", "prev_version", "bump", "breaking", "summary",
            "action_required_sections", "all_sections"):
    assert key in v, f"version record missing key: {key}"
assert v["bump"] == "patch", f"1.0.1 should be patch, got {v['bump']}"
assert v["date"] == "2026-06-01", f"date should parse, got {v['date']}"
PY
then pass "JSON envelope carries all documented fields; patch classified + date parsed"
else fail "JSON envelope incomplete"; fi

# ---- 8: smoke test against the SHIPPED CHANGELOG.md + SEMVER.md ----
o="$TMP/shipped.json"
if python3 "$GEN" --changelog "$SHIPPED_CHANGELOG" --semver "$SHIPPED_SEMVER" --json >"$o" 2>/dev/null; then
  ec=0
else ec=$?; fi
if [ "$ec" -ne 0 ]; then fail "shipped CHANGELOG/SEMVER did not generate (exit $ec)"; fi
PKG_VERSION="$(node -p "require('$ROOT/package.json').version" 2>/dev/null)"
if python3 - "$o" "$PKG_VERSION" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
pkg = sys.argv[2]
assert d["schema"] == "migration-notes/v1"
assert d["versions"], "shipped CHANGELOG produced no versions"
latest = d["versions"][0]["version"]
assert latest == pkg, f"latest CHANGELOG version {latest} != package.json {pkg}"
PY
then pass "shipped CHANGELOG.md parses; latest entry == package.json version ($PKG_VERSION)"
else fail "shipped CHANGELOG latest != package.json version (or parse failed)"; fi

echo ""
echo "migration-notes suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
