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
