#!/usr/bin/env bash
#
# install.sh — vendor @intentsolutions/audit-harness into any repo.
#
# Works for Python / Go / Rust / Java / Ruby / PHP / C++ / .NET / Shell repos
# — anything that isn't Node. (Node repos should use: pnpm add -D @intentsolutions/audit-harness)
#
# USAGE (installs the latest release):
#   curl -sSL https://raw.githubusercontent.com/jeremylongshore/intent-audit-harness/main/install.sh | bash
#
# Pinned to a specific version — any of these work:
#   curl -sSL .../install.sh | bash -s -- --version v1.3.0     # preferred: pipe-safe
#   curl -sSL .../install.sh | AUDIT_HARNESS_VERSION=v1.3.0 bash
#   curl -sSL https://raw.githubusercontent.com/jeremylongshore/intent-audit-harness/v1.3.0/install.sh | bash
#
# NOT this — it is the shell's most common footgun and this file used to recommend it:
#   AUDIT_HARNESS_VERSION=v1.3.0 curl -sSL .../install.sh | bash
# In a pipeline the assignment applies to `curl`, NOT to `bash`. The variable never
# reaches this script, so it silently installs the default instead of what you asked
# for — with a success message naming the version you did not get.
#
# INSTALLS INTO:
#   .audit-harness/               (scripts + version marker)
#   .audit-harness/schemas/       (classify registry + conform schemas, incl. the
#                                  pinned kernel authoring/v1 subset; offline)
#   .audit-harness/configs/       (shared lint configs to `extends:` from your own root configs)
#   scripts/audit-harness         (wrapper binary; dispatches to .audit-harness/scripts/*)
#
# CI usage after install:
#   scripts/audit-harness verify
#   scripts/audit-harness escape-scan --staged

set -euo pipefail

REPO="jeremylongshore/intent-audit-harness"

# Floor used only when the latest release cannot be resolved (offline / API rate limit).
# This is a FALLBACK, not the normal path — a hardcoded default is what let installs
# silently pin to a stale version for months.
FALLBACK_VERSION="v1.3.0"

# --version/-v <tag> — the pipe-safe way to pin, since `curl | bash -s -- --version X`
# passes the argument to THIS script rather than to curl.
VERSION_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version|-v)
      VERSION_ARG="${2:-}"
      if [[ -z "${VERSION_ARG}" ]]; then
        echo "✗ audit-harness install: --version requires a tag (e.g. --version v1.3.0)" >&2
        exit 2
      fi
      shift 2
      ;;
    *)
      echo "✗ audit-harness install: unknown argument '$1'" >&2
      echo "  usage: install.sh [--version vX.Y.Z]" >&2
      exit 2
      ;;
  esac
done

resolve_latest_tag() {
  # Ask GitHub for the newest release tag. Best-effort: any failure returns empty and
  # the caller falls back, so a network problem degrades to a pinned install rather
  # than aborting.
  local api="https://api.github.com/repos/${REPO}/releases/latest"
  local body=""
  if command -v curl >/dev/null 2>&1; then
    body="$(curl -sSL --max-time 10 "${api}" 2>/dev/null || true)"
  elif command -v wget >/dev/null 2>&1; then
    body="$(wget -qO- --timeout=10 "${api}" 2>/dev/null || true)"
  fi
  [[ -z "${body}" ]] && return 0
  printf '%s' "${body}" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1
}

# Precedence: explicit flag > environment variable > resolved latest > fallback floor.
if [[ -n "${VERSION_ARG}" ]]; then
  VERSION="${VERSION_ARG}"
  VERSION_SOURCE="--version flag"
elif [[ -n "${AUDIT_HARNESS_VERSION:-}" ]]; then
  VERSION="${AUDIT_HARNESS_VERSION}"
  VERSION_SOURCE="AUDIT_HARNESS_VERSION"
else
  VERSION="$(resolve_latest_tag)"
  if [[ -n "${VERSION}" ]]; then
    VERSION_SOURCE="latest release"
  else
    VERSION="${FALLBACK_VERSION}"
    VERSION_SOURCE="fallback (could not reach the GitHub releases API)"
  fi
fi
TARGET_DIR=".audit-harness"
WRAPPER_DIR="scripts"
WRAPPER_PATH="${WRAPPER_DIR}/audit-harness"

# Must run in a git repo (so the installed files end up version-controlled)
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "✗ audit-harness install: must run from within a git repository." >&2
  exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "→ installing @intentsolutions/audit-harness ${VERSION} into ${REPO_ROOT}  [version from: ${VERSION_SOURCE}]"

# Refuse redirected destinations before staging or touching the existing install.
for path in "$TARGET_DIR" "$WRAPPER_DIR" "$WRAPPER_PATH"; do
  if [[ -L "$path" ]]; then
    echo "✗ refusing symlink install destination: $path" >&2
    exit 2
  fi
done
if [[ ( -e "$TARGET_DIR" && ! -d "$TARGET_DIR" ) ||
      ( -e "$WRAPPER_DIR" && ! -d "$WRAPPER_DIR" ) ||
      ( -e "$WRAPPER_PATH" && ! -f "$WRAPPER_PATH" ) ]]; then
  echo "✗ install destinations have incompatible file types" >&2
  exit 2
fi

# Serialize cooperating installers. A stale lock is refused, never stolen.
LOCK_DIR=".audit-harness-install.lock"
if ! mkdir "$LOCK_DIR"; then
  echo "✗ another install or retained recovery lock exists: $LOCK_DIR" >&2
  exit 2
fi
TMP_DIR=""
INSTALLING=0
COMMITTED=0
CREATED_WRAPPER_DIR=0
cleanup_install() {
  local rc=$? recovery_failed=0
  trap - EXIT HUP INT TERM
  if [[ "$INSTALLING" -eq 1 && "$COMMITTED" -eq 0 ]]; then
    # Backups are renamed, not copied: retain original bytes and permissions.
    if [[ -d "$TMP_DIR/previous-tree" ]]; then
      if rm -rf "$REPO_ROOT/.audit-harness"; then
        mv -f "$TMP_DIR/previous-tree" "$REPO_ROOT/.audit-harness" || recovery_failed=1
      else
        recovery_failed=1
      fi
    elif [[ ! -e "$TMP_DIR/new-tree" ]]; then
      rm -rf "$REPO_ROOT/.audit-harness"
    fi
    if [[ -f "$TMP_DIR/previous-wrapper" ]]; then
      if rm -f "$REPO_ROOT/scripts/audit-harness"; then
        mv -f "$TMP_DIR/previous-wrapper" "$REPO_ROOT/scripts/audit-harness" || recovery_failed=1
      else
        recovery_failed=1
      fi
    elif [[ ! -e "$TMP_DIR/new-wrapper" ]]; then
      rm -f "$REPO_ROOT/scripts/audit-harness"
    fi
    if [[ "$CREATED_WRAPPER_DIR" -eq 1 ]]; then
      rmdir "$REPO_ROOT/scripts" 2>/dev/null || true
    fi
  fi
  if [[ "$recovery_failed" -eq 1 ]]; then
    echo "✗ recovery incomplete; retained backups at $TMP_DIR and lock $LOCK_DIR" >&2
    exit 2
  fi
  [[ -z "$TMP_DIR" ]] || rm -rf "$TMP_DIR"
  rmdir "$LOCK_DIR"
  exit "$rc"
}
trap cleanup_install EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Stage on the destination filesystem so all publication/rollback moves rename.
TMP_DIR="$(mktemp -d "$REPO_ROOT/.audit-harness-install.XXXXXX")"
FINAL_TARGET_DIR="$TARGET_DIR"
FINAL_WRAPPER_PATH="$WRAPPER_PATH"
TARGET_DIR="$TMP_DIR/new-tree"
WRAPPER_PATH="$TMP_DIR/new-wrapper"
mkdir "$TARGET_DIR"

# The override remains supported for explicit offline release archives.
TARBALL_URL="${AUDIT_HARNESS_TARBALL_URL:-https://github.com/${REPO}/archive/refs/tags/${VERSION}.tar.gz}"

echo "  downloading ${TARBALL_URL}"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "${TARBALL_URL}" -o "${TMP_DIR}/audit-harness.tar.gz"
elif command -v wget >/dev/null 2>&1; then
  wget -q "${TARBALL_URL}" -O "${TMP_DIR}/audit-harness.tar.gz"
else
  echo "✗ need curl or wget to download release." >&2
  exit 2
fi

# Validate members before extraction: one release root, regular files/directories
# only, no traversal or link/device entries. No downloaded code is executed.
tar -tzf "$TMP_DIR/audit-harness.tar.gz" > "$TMP_DIR/members"
ROOT_NAME=""
while IFS= read -r member; do
  if [[ -z "$member" || "$member" == /* || "$member" == *\\* ||
        "$member" =~ [[:cntrl:]] || "/$member/" == *"/../"* || "/$member/" == *"/./"* ]]; then
    echo "✗ unsafe archive path" >&2
    exit 2
  fi
  member_root="${member%%/*}"
  if [[ "$member_root" != *audit-harness-* ||
        ( -n "$ROOT_NAME" && "$member_root" != "$ROOT_NAME" ) ]]; then
    echo "✗ archive must contain exactly one audit-harness release root" >&2
    exit 2
  fi
  ROOT_NAME="$member_root"
done < "$TMP_DIR/members"
[[ -n "$ROOT_NAME" ]] || { echo "✗ empty archive" >&2; exit 2; }
LC_ALL=C tar -tvzf "$TMP_DIR/audit-harness.tar.gz" > "$TMP_DIR/member-types"
while IFS= read -r entry; do
  case "$entry" in
    -*|d*) ;;
    *) echo "✗ archive contains a link or special file" >&2; exit 2 ;;
  esac
done < "$TMP_DIR/member-types"
echo "  extracting into private staging directory"
mkdir "$TMP_DIR/extracted"
tar -xzf "$TMP_DIR/audit-harness.tar.gz" -C "$TMP_DIR/extracted"
UNPACKED_DIR="$TMP_DIR/extracted/$ROOT_NAME"
[[ -d "$UNPACKED_DIR/scripts" ]] || { echo "✗ release scripts directory missing" >&2; exit 2; }
for required in harness-hash.sh escape-scan.sh; do
  [[ -f "$UNPACKED_DIR/scripts/$required" ]] || { echo "✗ release missing $required" >&2; exit 2; }
done

# Copy scripts/ and metadata into .audit-harness/
cp -r "${UNPACKED_DIR}/scripts" "${TARGET_DIR}/scripts"

# Keep README's relative docs/ links usable in a vendored installation. Older
# release archives without docs/ remain installable.
if [[ -d "${UNPACKED_DIR}/docs" ]]; then
  cp -r "${UNPACKED_DIR}/docs" "${TARGET_DIR}/docs"
fi

# Copy schemas/ into .audit-harness/schemas/. classify.py and conform.py resolve
# them relative to scripts/ (../schemas/...), so without this copy classify has
# no registry and conform can only emit "bundled schema missing" ADVISORY rows.
# The tree includes the vendored kernel subset under schemas/conform/kernel/,
# whose pin.json carries its own npm provenance; every file is hashed into
# PROVENANCE below. Older tags that predate schemas/ simply skip this step.
if [[ -d "${UNPACKED_DIR}/schemas" ]]; then
  cp -r "${UNPACKED_DIR}/schemas" "${TARGET_DIR}/schemas"
fi

# Copy the shared lint configs into .audit-harness/configs/. The source dir at
# the audit-harness repo root is `.audit-harness-configs/` (named so it does not
# collide with the consumer-side `.audit-harness/` install target); it lands in
# the consumer at `.audit-harness/configs/`, giving every repo one stable path
# to point an `extends:` at (markdownlint / yamllint / ruff / shellcheck).
# See .audit-harness/configs/README.md for the per-tool extend snippets.
if [[ -d "${UNPACKED_DIR}/.audit-harness-configs" ]]; then
  cp -r "${UNPACKED_DIR}/.audit-harness-configs" "${TARGET_DIR}/configs"
fi

cp "${UNPACKED_DIR}/README.md" "${TARGET_DIR}/README.md" 2>/dev/null || true
cp "${UNPACKED_DIR}/LICENSE" "${TARGET_DIR}/LICENSE" 2>/dev/null || true
# NOTICE: Apache-2.0 §4(d) requires redistributing the NOTICE file with any
# distribution of the work. Vendoring is a distribution, so it travels too.
cp "${UNPACKED_DIR}/NOTICE" "${TARGET_DIR}/NOTICE" 2>/dev/null || true
cp "${UNPACKED_DIR}/CHANGELOG.md" "${TARGET_DIR}/CHANGELOG.md" 2>/dev/null || true
echo "${VERSION}" > "${TARGET_DIR}/VERSION"

# bin/audit-harness.js: the Node CLI dispatcher. Vendored alongside the shell
# wrapper so the canonical dispatcher surface is present (referenced by sister
# CI + .harness-hash-extra-patterns); the shell wrapper at scripts/audit-harness
# stays the non-Node entry point. package.json travels too so the dispatcher's
# `--version` (which reads `../package.json`) resolves in the vendored tree.
mkdir -p "${TARGET_DIR}/bin"
cp "${UNPACKED_DIR}/bin/audit-harness.js" "${TARGET_DIR}/bin/audit-harness.js" 2>/dev/null || true
cp "${UNPACKED_DIR}/package.json" "${TARGET_DIR}/package.json" 2>/dev/null || true

# Record provenance of the vendored copy (source repo + version + install time)
# so a vendored tree is traceable back to the exact release it came from.
cat > "${TARGET_DIR}/PROVENANCE" <<PROV_EOF
source-repo:   ${REPO}
source-version: ${VERSION}
source-tarball: ${TARBALL_URL}
installed-at:  $(date -u +%Y-%m-%dT%H:%M:%SZ)
PROV_EOF

# Per-file sha256 of the vendored schemas, so a consumer can prove the conform
# policy it runs is byte-identical to the release (conform also records each
# schema's sha256 as the policy_hash of every row it emits).
if [[ -d "${TARGET_DIR}/schemas" ]]; then
  echo "schemas-sha256:" >> "${TARGET_DIR}/PROVENANCE"
  (cd "${TARGET_DIR}" && find schemas -type f | LC_ALL=C sort | while IFS= read -r f; do
    if command -v sha256sum >/dev/null 2>&1; then
      printf '  %s\n' "$(sha256sum "$f")"
    else
      printf '  %s\n' "$(shasum -a 256 "$f")"
    fi
  done) >> "${TARGET_DIR}/PROVENANCE"
fi

# Ensure scripts are executable
chmod +x "${TARGET_DIR}/scripts/"*.sh "${TARGET_DIR}/scripts/"*.py 2>/dev/null || true
chmod +x "${TARGET_DIR}/bin/audit-harness.js" 2>/dev/null || true

# Write wrapper binary at scripts/audit-harness
# This mirrors the Node CLI surface so commands are identical cross-language
cat > "${WRAPPER_PATH}" <<'WRAPPER_EOF'
#!/usr/bin/env bash
# audit-harness — vendored shell wrapper (non-Node repos).
# Mirrors the Node CLI at https://www.npmjs.com/package/@intentsolutions/audit-harness
# but dispatches directly to the scripts in .audit-harness/scripts/.

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/.." && pwd)/.audit-harness"
SCRIPTS="${HARNESS_DIR}/scripts"

if [[ ! -d "${SCRIPTS}" ]]; then
  echo "✗ audit-harness: scripts not found at ${SCRIPTS}" >&2
  echo "  re-run the installer: curl -sSL https://raw.githubusercontent.com/jeremylongshore/intent-audit-harness/main/install.sh | bash" >&2
  exit 2
fi

usage() {
  cat <<'USAGE'
audit-harness — deterministic test-enforcement toolkit (vendored)

Usage:
  scripts/audit-harness <command> [args...]

Commands:
  verify                   Verify hash-pinned artifacts (exit 2 = HARNESS_TAMPERED)
  init                     Initialize or re-init the .harness-hash manifest
  list                     List currently pinned files
  escape-scan <source>     Scan a diff for escape attempts
  arch                     Run architecture-rule checks
  bias                     Count test-bias patterns
  gherkin-lint             Advisory Gherkin quality check
  crap [args...]           CRAP scorer (requires python3 + radon/gocyclo)
  classify [repo]          Read-only repo classifier -> audit-profile/v1 (python3)
  conform [repo] [--strict] [--tier floor|marketplace]
                           Read-only conformance gate-runner -> gate-result/v1 rows,
                           against the schemas vendored in .audit-harness/schemas/
  --version, -v            Print installed version
  --help, -h               This help
USAGE
}

cmd="${1:-}"
shift || true

case "${cmd}" in
  verify)       exec bash "${SCRIPTS}/harness-hash.sh" --verify "$@" ;;
  init)         exec bash "${SCRIPTS}/harness-hash.sh" --init "$@" ;;
  list)         exec bash "${SCRIPTS}/harness-hash.sh" --list "$@" ;;
  escape-scan)  exec bash "${SCRIPTS}/escape-scan.sh" "$@" ;;
  arch)         exec bash "${SCRIPTS}/arch-check.sh" "$@" ;;
  bias)         exec bash "${SCRIPTS}/bias-count.sh" "$@" ;;
  gherkin-lint) exec bash "${SCRIPTS}/gherkin-lint.sh" "$@" ;;
  crap)         exec python3 "${SCRIPTS}/crap-score.py" "$@" ;;
  classify)     exec python3 "${SCRIPTS}/classify.py" "$@" ;;
  conform)      exec python3 "${SCRIPTS}/conform.py" "$@" ;;
  --version|-v) cat "${HARNESS_DIR}/VERSION" 2>/dev/null || echo "unknown" ;;
  --help|-h|'') usage; exit 0 ;;
  *)
    echo "✗ audit-harness: unknown command '${cmd}'" >&2
    usage
    exit 2
    ;;
esac
WRAPPER_EOF

chmod +x "${WRAPPER_PATH}"

# Publish only after every staging operation has succeeded. EXIT/signal cleanup
# restores both original paths if either rename fails. SIGKILL/power loss cannot
# run traps; their retained lock/staging directory must be inspected for recovery.
INSTALLING=1
if [[ -d "$FINAL_TARGET_DIR" ]]; then
  mv -f "$FINAL_TARGET_DIR" "$TMP_DIR/previous-tree"
fi
if [[ -f "$FINAL_WRAPPER_PATH" ]]; then
  mv -f "$FINAL_WRAPPER_PATH" "$TMP_DIR/previous-wrapper"
fi
if [[ ! -d "$WRAPPER_DIR" ]]; then
  mkdir "$WRAPPER_DIR"
  CREATED_WRAPPER_DIR=1
fi
mv -f "$TARGET_DIR" "$FINAL_TARGET_DIR"
mv -f "$WRAPPER_PATH" "$FINAL_WRAPPER_PATH"
COMMITTED=1
TARGET_DIR="$FINAL_TARGET_DIR"
WRAPPER_PATH="$FINAL_WRAPPER_PATH"

# Ensure .audit-harness/ is tracked (committed)
# Don't add to .gitignore — we want engineers to see updates via PR

cat <<EOF

✓ audit-harness ${VERSION} installed.

Vendored at: ${REPO_ROOT}/${TARGET_DIR}/
Configs at:  ${REPO_ROOT}/${TARGET_DIR}/configs/   (extend these from your own root lint configs)
Wrapper at:  ${REPO_ROOT}/${WRAPPER_PATH}

Usage:
  ${WRAPPER_PATH} --help
  ${WRAPPER_PATH} verify
  ${WRAPPER_PATH} escape-scan --staged

Shared lint configs (point an \`extends\` at these):
  ${TARGET_DIR}/configs/markdownlint.yaml   # extends: in .markdownlint.yaml
  ${TARGET_DIR}/configs/yamllint.yaml       # extends: in .yamllint.yaml
  ${TARGET_DIR}/configs/ruff.toml           # extend = in ruff.toml
  ${TARGET_DIR}/configs/shellcheckrc        # reference shape for .shellcheckrc
  ${TARGET_DIR}/configs/README.md           # per-tool extend snippets

Next steps:
  1. git add ${TARGET_DIR}/ ${WRAPPER_PATH}
  2. Commit: "chore(test): install @intentsolutions/audit-harness ${VERSION}"
  3. Wire into your pre-commit hook + CI — see .audit-harness/README.md

To upgrade later (re-running with no arguments installs the latest release):
  curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash

To pin a specific version, pass it to bash — NOT to curl:
  curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash -s -- --version vX.Y.Z
EOF
