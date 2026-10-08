#!/usr/bin/env bash
# Offline install suite for install.sh (the non-Node vendoring path).
#
# Proves a FRESH install can run `conform` with no network:
#   1. install.sh vendors schemas/ (classify registry + conform floor schemas +
#      the pinned kernel authoring/v1 subset) next to scripts/
#   2. PROVENANCE records the source tarball and a sha256 line per schema file,
#      and those hashes match the installed bytes
#   3. the vendored wrapper dispatches `conform`, and a floor run on a valid skill
#      is PASS with policy_hash == the installed floor schema (not the
#      "bundled schema missing" ADVISORY the v1.4.0 installer produced)
#   4. `conform --tier marketplace --strict` PASSes a full 8-field skill and
#      FAILs one missing `version`, against the installed kernel pin
#
# Offline by construction: the release tarball is built from this checkout and
# served via file:// (AUDIT_HARNESS_TARBALL_URL), --version skips the GitHub
# releases API lookup, and every proxy variable points at a closed port so any
# stray HTTP(S) fetch fails instead of silently succeeding.
#
# Run from the repository root:
#   bash tests/install/run-install-tests.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIX="$ROOT/tests/fixtures/conform"
PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ⛔ $1" >&2; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "install.sh offline suite"

# ---- build a release-shaped tarball from this checkout ----
VER="v0.0.0-offline-test"
STAGE="$TMP/stage/intent-audit-harness-${VER#v}"
mkdir -p "$STAGE"
for p in scripts schemas bin .audit-harness-configs README.md LICENSE NOTICE CHANGELOG.md package.json; do
  [ -e "$ROOT/$p" ] && cp -R "$ROOT/$p" "$STAGE/"
done
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
tar -czf "$TMP/release.tar.gz" -C "$TMP/stage" "intent-audit-harness-${VER#v}"

# ---- fresh consumer repo ----
CONSUMER="$TMP/consumer"
mkdir -p "$CONSUMER"
git -C "$CONSUMER" init -q
cp "$FIX/valid/skill-marketplace/SKILL.md" "$CONSUMER/SKILL.md"

OFFLINE_ENV=(
  "AUDIT_HARNESS_TARBALL_URL=file://$TMP/release.tar.gz"
  "http_proxy=http://127.0.0.1:9" "https_proxy=http://127.0.0.1:9"
  "HTTP_PROXY=http://127.0.0.1:9" "HTTPS_PROXY=http://127.0.0.1:9"
  "ALL_PROXY=http://127.0.0.1:9" "no_proxy=" "NO_PROXY="
)
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" bash "$ROOT/install.sh" --version "$VER" >"$TMP/install.log" 2>&1); then
  pass "install.sh --version $VER from a file:// tarball succeeded offline"
else
  fail "install.sh failed: $(cat "$TMP/install.log")"
fi

H="$CONSUMER/.audit-harness"

# ---- 1: schemas vendored ----
missing=0
for f in schemas/audit-profile/registry.v1.json \
         schemas/conform/v1/skillmd-frontmatter.schema.json \
         schemas/conform/kernel/intent-eval-core-0.11.0/pin.json \
         schemas/conform/kernel/intent-eval-core-0.11.0/authoring/v1/skill-frontmatter.schema.json; do
  if [ ! -f "$H/$f" ]; then fail "not vendored: $f"; missing=1; fi
done
[ "$missing" -eq 0 ] && pass "schemas/ (registry, conform floor, pinned kernel) vendored into .audit-harness/"
if diff -r "$ROOT/schemas" "$H/schemas" >/dev/null; then
  pass "vendored schemas/ is byte-identical to the release tree"
else fail "vendored schemas/ differs from the release tree"; fi

# ---- 2: provenance ----
if grep -q "^source-tarball: file://$TMP/release.tar.gz" "$H/PROVENANCE" \
   && grep -q "^schemas-sha256:" "$H/PROVENANCE"; then
  pass "PROVENANCE records the tarball source and a schemas-sha256 section"
else fail "PROVENANCE incomplete: $(cat "$H/PROVENANCE")"; fi
if python3 - "$H" <<'PY'
import hashlib, os, sys
h = sys.argv[1]
lines = open(os.path.join(h, "PROVENANCE")).read().split("schemas-sha256:\n", 1)[1].splitlines()
recorded = {}
for ln in lines:
    digest, path = ln.split()
    recorded[path] = digest
on_disk = set()
for root, _, files in os.walk(os.path.join(h, "schemas")):
    for f in files:
        on_disk.add(os.path.relpath(os.path.join(root, f), h))
assert set(recorded) == on_disk, set(recorded) ^ on_disk
for path, digest in recorded.items():
    got = hashlib.sha256(open(os.path.join(h, path), "rb").read()).hexdigest()
    assert got == digest, path
PY
then pass "PROVENANCE schemas-sha256 covers every vendored schema file and matches the bytes"
else fail "PROVENANCE schemas-sha256 does not match the installed files"; fi

# ---- 3: wrapper dispatches conform; floor verdict is real, not indeterminate ----
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" scripts/audit-harness conform . >"$TMP/floor.json" 2>"$TMP/floor.err"); then
  ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && python3 - "$TMP/floor.json" "$H/schemas/conform/v1/skillmd-frontmatter.schema.json" <<'PY'
import hashlib, json, sys
r = [x for x in json.load(open(sys.argv[1])) if "conform-skillmd" in x["gate_id"]][0]
want = "sha256:" + hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
assert r["result"] == "PASS", r
assert r["policy_hash"] == want, (r["policy_hash"], want)
assert not r.get("metadata", {}).get("indeterminate"), r
PY
then pass "fresh install: scripts/audit-harness conform -> PASS against the vendored floor schema"
else fail "fresh-install floor conform (exit $ec): $(cat "$TMP/floor.json" "$TMP/floor.err")"; fi

# ---- 4: marketplace tier against the installed kernel pin ----
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" scripts/audit-harness conform . --tier marketplace --strict >"$TMP/mk.json" 2>/dev/null); then
  ec=0; else ec=$?; fi
if [ "$ec" -eq 0 ] && python3 - "$TMP/mk.json" "$H/schemas/conform/kernel/intent-eval-core-0.11.0/pin.json" <<'PY'
import hashlib, json, sys
r = [x for x in json.load(open(sys.argv[1])) if "conform-skillmd" in x["gate_id"]][0]
want = "sha256:" + hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
assert r["result"] == "PASS" and r["policy_hash"] == want, r
PY
then pass "fresh install: --tier marketplace --strict -> PASS on a full 8-field skill"
else fail "fresh-install marketplace PASS (exit $ec): $(cat "$TMP/mk.json")"; fi

cp "$FIX/malformed/skill-no-version/SKILL.md" "$CONSUMER/SKILL.md"
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" scripts/audit-harness conform . --tier marketplace --strict >"$TMP/nv.json" 2>/dev/null); then
  ec=0; else ec=$?; fi
if [ "$ec" -eq 1 ] && grep -q "missing required property 'version'" "$TMP/nv.json"; then
  pass "fresh install: --tier marketplace --strict -> FAIL (exit 1) on a skill missing version"
else fail "fresh-install marketplace FAIL (exit $ec): $(cat "$TMP/nv.json")"; fi

echo ""
echo "install suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
