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
INSTALLER="${INSTALLER_UNDER_TEST:-$ROOT/install.sh}"
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
for p in scripts schemas docs bin .audit-harness-configs README.md LICENSE NOTICE CHANGELOG.md package.json; do
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
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" bash "$INSTALLER" --version "$VER" >"$TMP/install.log" 2>&1); then
  pass "install.sh --version $VER from a file:// tarball succeeded offline"
else
  fail "install.sh failed: $(cat "$TMP/install.log")"
fi

H="$CONSUMER/.audit-harness"

# README links into docs/ must resolve in the installed consumer, not just in
# the upstream checkout. Compare the complete release-selected documentation.
if diff -r "$ROOT/docs" "$H/docs" >/dev/null 2>&1; then
  pass "vendored documentation is byte-identical to the release tree"
else fail "vendored docs/ missing or differs from the release tree"; fi

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

# Installed imports and pinned MCP/hook schemas must work without the checkout.
ENVELOPES="$TMP/envelopes"
mkdir -p "$ENVELOPES/.claude"
python3 - "$FIX" "$ENVELOPES" <<'PY_ENVELOPES'
import json, sys
from pathlib import Path
fixtures, target = map(Path, sys.argv[1:])
mcp = json.loads((fixtures / "kernel-mcp/positive/canonical-01.json").read_text())
name = mcp.pop("name")
(target / ".mcp.json").write_text(json.dumps({"mcpServers": {name: mcp}}))
hook = json.loads((fixtures / "kernel-hook/positive/canonical-01.json").read_text())
event, matcher = hook.pop("event"), hook.pop("matcher")
(target / ".claude/settings.json").write_text(json.dumps({
    "hooks": {event: [{"matcher": matcher, "hooks": [hook]}]},
}))
PY_ENVELOPES
if env "${OFFLINE_ENV[@]}" "$CONSUMER/scripts/audit-harness" conform "$ENVELOPES" \
    --tier marketplace --strict >"$TMP/envelopes.json" 2>"$TMP/envelopes.err" &&
    python3 - "$TMP/envelopes.json" "$ENVELOPES" <<'PY_ENVELOPE_ROWS'
import hashlib, json, sys
from pathlib import Path
rows = json.loads(Path(sys.argv[1]).read_text())
for kind, path in (("mcp", ".mcp.json"), ("hook", ".claude/settings.json")):
    selected = [r for r in rows if r["gate_id"].endswith("conform-" + kind)]
    assert len(selected) == 1, selected
    row = selected[0]
    assert row["result"] == "PASS", row
    assert row["input_hash"] == "sha256:" + hashlib.sha256((Path(sys.argv[2]) / path).read_bytes()).hexdigest()
PY_ENVELOPE_ROWS
then pass "fresh install: MCP and embedded hooks PASS with original-byte binding offline"
else fail "fresh-install MCP/hooks: $(cat "$TMP/envelopes.json" "$TMP/envelopes.err")"; fi

python3 - "$ENVELOPES/.mcp.json" <<'PY_INVALID_MCP'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text())
del next(iter(data["mcpServers"].values()))["enabled"]
path.write_text(json.dumps(data))
PY_INVALID_MCP
if env "${OFFLINE_ENV[@]}" "$CONSUMER/scripts/audit-harness" conform "$ENVELOPES" \
    --tier marketplace --strict >"$TMP/envelopes-fail.json" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 1 ] && python3 - "$TMP/envelopes-fail.json" <<'PY_INVALID_ROWS'
import json, sys
rows = json.load(open(sys.argv[1]))
assert any(r["gate_id"].endswith("conform-mcp") and r["result"] == "FAIL" for r in rows), rows
PY_INVALID_ROWS
then pass "fresh install: missing MCP field remains strict FAIL"
else fail "fresh-install MCP strict refusal (exit $ec)"; fi

# The opt-in shared checker and its license must also survive offline vendoring.
SHARED_AGENT="$TMP/shared-agent"
mkdir -p "$SHARED_AGENT/agents"
cat > "$SHARED_AGENT/agents/example.md" <<'SHARED_FIXTURE'
---
name: fixture
description: Fixture agent
tools: [Read]
---
Use mcp__fixture__read.
SHARED_FIXTURE
if env "${OFFLINE_ENV[@]}" "$CONSUMER/scripts/audit-harness" conform "$SHARED_AGENT" \
    --shared-validators --strict >"$TMP/shared-agent.json" 2>/dev/null; then ec=0; else ec=$?; fi
if [ "$ec" -eq 1 ] && python3 - "$TMP/shared-agent.json" <<'PY_SHARED_ROWS'
import json, sys
rows = json.load(open(sys.argv[1]))
selected = [r for r in rows if r["gate_id"].endswith("conform-agent")]
assert len(selected) == 1, selected
row = selected[0]
assert row["result"] == "FAIL" and row["failure_mode"] == "conform:shared-validator-violation", row
assert row["metadata"]["shared_validator"]["static_only"], row
assert row["metadata"]["shared_validator"]["errors"], row
assert not row["metadata"].get("indeterminate"), row
PY_SHARED_ROWS
then pass "fresh install: pinned shared agent checker produces strict static-policy FAIL offline"
else fail "fresh-install shared agent checker (exit $ec)"; fi

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

# Older release archives may omit docs/. Their scripts must remain installable.
tar --exclude="intent-audit-harness-${VER#v}/docs" \
  --exclude="intent-audit-harness-${VER#v}/docs/*" \
  -czf "$TMP/no-docs.tar.gz" -C "$TMP/stage" "intent-audit-harness-${VER#v}"
LEGACY="$TMP/legacy-consumer"
mkdir -p "$LEGACY"
git -C "$LEGACY" init -q
if (cd "$LEGACY" && env "${OFFLINE_ENV[@]}" \
    "AUDIT_HARNESS_TARBALL_URL=file://$TMP/no-docs.tar.gz" \
    bash "$INSTALLER" --version "$VER" >"$TMP/legacy-install.log" 2>&1) \
    && [ ! -e "$LEGACY/.audit-harness/docs" ] \
    && [ -f "$LEGACY/.audit-harness/schemas/audit-profile/registry.v1.json" ] \
    && [ "$(cd "$LEGACY" && scripts/audit-harness --version)" = "$VER" ]; then
  pass "older archive without docs installs and its wrapper reports the selected version"
else fail "archive without docs did not retain working installation"; fi

# Failure preservation is checked against a working, deliberately customized
# installation, including its wrapper and source provenance. No live consumer.
printf 'retained installation\n' > "$CONSUMER/.audit-harness/operator-sentinel"
chmod 640 "$CONSUMER/.audit-harness/operator-sentinel"
chmod 750 "$CONSUMER/scripts/audit-harness"
cp -a "$CONSUMER/.audit-harness" "$TMP/before-tree"
cp -a "$CONSUMER/scripts/audit-harness" "$TMP/before-wrapper"

preserved_install() {
  diff -r "$TMP/before-tree" "$CONSUMER/.audit-harness" >/dev/null 2>&1 &&
    cmp -s "$TMP/before-wrapper" "$CONSUMER/scripts/audit-harness" &&
    [ "$(stat -c %a "$CONSUMER/.audit-harness/operator-sentinel")" = 640 ] &&
    [ "$(stat -c %a "$CONSUMER/scripts/audit-harness")" = 750 ] &&
    [ "$(cd "$CONSUMER" && scripts/audit-harness --version)" = "$VER" ]
}
refused_upgrade() {
  local archive="$1" label="$2"
  if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" \
      "AUDIT_HARNESS_TARBALL_URL=file://$archive" \
      bash "$INSTALLER" --version v9.9.9 >"$TMP/refused.log" 2>&1); then
    fail "$label unexpectedly succeeded"
  elif preserved_install; then
    pass "$label preserves working tree, wrapper, provenance and permissions"
  else
    fail "$label damaged existing installation"
  fi
}
printf 'not an archive\n' > "$TMP/corrupt.tar.gz"
refused_upgrade "$TMP/absent.tar.gz" "failed download"
refused_upgrade "$TMP/corrupt.tar.gz" "invalid archive"
mkdir -p "$TMP/incomplete/intent-audit-harness-incomplete"
printf 'missing scripts\n' > "$TMP/incomplete/intent-audit-harness-incomplete/README.md"
tar -czf "$TMP/incomplete.tar.gz" -C "$TMP/incomplete" intent-audit-harness-incomplete
refused_upgrade "$TMP/incomplete.tar.gz" "incomplete release"
mkdir -p "$TMP/linked/intent-audit-harness-linked"
ln -s "$TMP/outside" "$TMP/linked/intent-audit-harness-linked/scripts"
tar -czf "$TMP/linked.tar.gz" -C "$TMP/linked" intent-audit-harness-linked
refused_upgrade "$TMP/linked.tar.gz" "symlink archive"

# A failure at the second publication rename must restore the first path too.
mkdir "$TMP/fail-mv"
REAL_MV="$(command -v mv)"
cat > "$TMP/fail-mv/mv" <<'MV_STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in */new-wrapper) exit 73 ;; esac
done
exec "$INSTALL_TEST_REAL_MV" "$@"
MV_STUB
chmod +x "$TMP/fail-mv/mv"
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" \
    "PATH=$TMP/fail-mv:$PATH" "INSTALL_TEST_REAL_MV=$REAL_MV" \
    bash "$INSTALLER" --version v9.9.9 >"$TMP/publish-failure.log" 2>&1); then
  fail "wrapper publication fault unexpectedly succeeded"
elif preserved_install; then
  pass "wrapper publication fault restores both original paths"
else fail "wrapper publication fault damaged existing install"; fi

# Refuse redirected destinations without writing into the linked directory.
LINKED="$TMP/linked-consumer"
mkdir -p "$LINKED" "$TMP/untouched"
git -C "$LINKED" init -q
printf 'outside remains\n' > "$TMP/untouched/sentinel"
ln -s "$TMP/untouched" "$LINKED/.audit-harness"
if (cd "$LINKED" && env "${OFFLINE_ENV[@]}" \
    bash "$INSTALLER" --version "$VER" >"$TMP/linked-destination.log" 2>&1); then
  fail "symlink destination unexpectedly accepted"
elif [ -L "$LINKED/.audit-harness" ] &&
    [ "$(cat "$TMP/untouched/sentinel")" = 'outside remains' ] &&
    [ "$(find "$TMP/untouched" -type f | wc -l)" -eq 1 ]; then
  pass "symlink destination refuses without altering external target"
else fail "symlink destination was altered"; fi

# A catchable termination during publication restores the prior installation.
mkdir "$TMP/signal-mv"
cat > "$TMP/signal-mv/mv" <<'MV_SIGNAL'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in */new-wrapper) kill -TERM "$PPID"; exit 143 ;; esac
done
exec "$INSTALL_TEST_REAL_MV" "$@"
MV_SIGNAL
chmod +x "$TMP/signal-mv/mv"
if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" \
    "PATH=$TMP/signal-mv:$PATH" "INSTALL_TEST_REAL_MV=$REAL_MV" \
    bash "$INSTALLER" --version v9.9.9 >"$TMP/termination.log" 2>&1); then
  fail "terminated publication unexpectedly succeeded"
elif preserved_install; then
  pass "terminated publication restores tree and wrapper"
else fail "terminated publication damaged existing install"; fi

if (cd "$CONSUMER" && env "${OFFLINE_ENV[@]}" \
    bash "$INSTALLER" --version v9.9.9 >"$TMP/upgrade.log" 2>&1) &&
    [ "$(cd "$CONSUMER" && scripts/audit-harness --version)" = v9.9.9 ] &&
    [ ! -e "$CONSUMER/.audit-harness/operator-sentinel" ] &&
    diff -r "$ROOT/schemas" "$CONSUMER/.audit-harness/schemas" >/dev/null; then
  pass "valid upgrade replaces tree and wrapper after failed attempts"
else fail "valid upgrade failed"; fi

echo ""
echo "install suite: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
