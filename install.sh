#!/usr/bin/env bash
#
# install.sh — vendor @intentsolutions/audit-harness into any repo.
#
# Works for Python / Go / Rust / Java / Ruby / PHP / C++ / .NET / Shell repos
# — anything that isn't Node. (Node repos should use: pnpm add -D @intentsolutions/audit-harness)
#
# USAGE:
#   curl -sSL https://raw.githubusercontent.com/jeremylongshore/intent-audit-harness/main/install.sh | bash
#
# Pinned to a specific version:
#   curl -sSL https://raw.githubusercontent.com/jeremylongshore/intent-audit-harness/v1.1.5/install.sh | bash
#   # or:
#   AUDIT_HARNESS_VERSION=v1.1.5 curl -sSL .../install.sh | bash
#
# INSTALLS INTO:
#   .audit-harness/               (scripts + version marker)
#   scripts/audit-harness         (wrapper binary; dispatches to .audit-harness/scripts/*)
#
# CI usage after install:
#   scripts/audit-harness verify
#   scripts/audit-harness escape-scan --staged

set -euo pipefail

VERSION="${AUDIT_HARNESS_VERSION:-v1.1.5}"
REPO="jeremylongshore/intent-audit-harness"
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

echo "→ installing @intentsolutions/audit-harness ${VERSION} into ${REPO_ROOT}"

# Clean previous install
if [[ -d "${TARGET_DIR}" ]]; then
  echo "  removing existing ${TARGET_DIR}/"
  rm -rf "${TARGET_DIR}"
fi

mkdir -p "${TARGET_DIR}" "${WRAPPER_DIR}"

# Download tarball from GitHub release
TARBALL_URL="https://github.com/${REPO}/archive/refs/tags/${VERSION}.tar.gz"
TMP_DIR="$(mktemp -d)"
trap "rm -rf ${TMP_DIR}" EXIT

echo "  downloading ${TARBALL_URL}"
if command -v curl >/dev/null 2>&1; then
  curl -sSL "${TARBALL_URL}" -o "${TMP_DIR}/audit-harness.tar.gz"
elif command -v wget >/dev/null 2>&1; then
  wget -q "${TARBALL_URL}" -O "${TMP_DIR}/audit-harness.tar.gz"
else
  echo "✗ need curl or wget to download release." >&2
  exit 2
fi

echo "  extracting"
tar -xzf "${TMP_DIR}/audit-harness.tar.gz" -C "${TMP_DIR}"

# GitHub release tarball unpacks as: <repo>-<version>/ — i.e.
# intent-audit-harness-<version>/ after the repo rename (stripped leading
# 'v' in the dir name). The glob is leading-wildcard so it stays tolerant to
# both the current `intent-audit-harness` repo name and the legacy
# `audit-harness` name (pre-rename tags).
UNPACKED_DIR="$(find "${TMP_DIR}" -maxdepth 1 -type d -name '*audit-harness-*' | head -1)"
if [[ -z "${UNPACKED_DIR}" ]]; then
  echo "✗ could not find unpacked dir in ${TMP_DIR}" >&2
  exit 2
fi

# Copy scripts/ and metadata into .audit-harness/
cp -r "${UNPACKED_DIR}/scripts" "${TARGET_DIR}/scripts"
cp "${UNPACKED_DIR}/README.md" "${TARGET_DIR}/README.md" 2>/dev/null || true
cp "${UNPACKED_DIR}/LICENSE" "${TARGET_DIR}/LICENSE" 2>/dev/null || true
cp "${UNPACKED_DIR}/CHANGELOG.md" "${TARGET_DIR}/CHANGELOG.md" 2>/dev/null || true
echo "${VERSION}" > "${TARGET_DIR}/VERSION"

# Ensure scripts are executable
chmod +x "${TARGET_DIR}/scripts/"*.sh "${TARGET_DIR}/scripts/"*.py 2>/dev/null || true

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

# Ensure .audit-harness/ is tracked (committed)
# Don't add to .gitignore — we want engineers to see updates via PR

cat <<EOF

✓ audit-harness ${VERSION} installed.

Vendored at: ${REPO_ROOT}/${TARGET_DIR}/
Wrapper at:  ${REPO_ROOT}/${WRAPPER_PATH}

Usage:
  ${WRAPPER_PATH} --help
  ${WRAPPER_PATH} verify
  ${WRAPPER_PATH} escape-scan --staged

Next steps:
  1. git add ${TARGET_DIR}/ ${WRAPPER_PATH}
  2. Commit: "chore(test): install @intentsolutions/audit-harness ${VERSION}"
  3. Wire into your pre-commit hook + CI — see .audit-harness/README.md

To upgrade later:
  AUDIT_HARNESS_VERSION=vX.Y.Z curl -sSL \\
    https://raw.githubusercontent.com/${REPO}/main/install.sh | bash
EOF
