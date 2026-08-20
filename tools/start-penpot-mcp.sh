#!/usr/bin/env bash

set -euo pipefail

penpot_tag="${PENPOT_MCP_TAG:-2.16.2}"
base_dir="${PENPOT_MCP_BASE_DIR:-$HOME/.local/share/penpot-mcp}"
repo_dir="${base_dir}/penpot-${penpot_tag}"
mcp_dir="${repo_dir}/mcp"

bootstrap_only=0
force_install=0
force_build=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Starts the Penpot MCP runtime aligned to Penpot ${penpot_tag}.

Options:
  --bootstrap-only  Prepare the runtime but do not start it
  --force-install   Re-run dependency install and rebuild preparation
  --force-build     Re-run the MCP build before starting
  --help            Show this help

Environment overrides:
  PENPOT_MCP_TAG       Penpot source tag to use (default: ${penpot_tag})
  PENPOT_MCP_BASE_DIR  Base directory for the cloned Penpot source
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap-only)
      bootstrap_only=1
      shift
      ;;
    --force-install)
      force_install=1
      shift
      ;;
    --force-build)
      force_build=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ensure_corepack() {
  if ! command -v corepack >/dev/null 2>&1; then
    echo "corepack not found; installing via npm -g" >&2
    npm install -g corepack
  fi
  corepack enable >/dev/null 2>&1 || true
}

ensure_repo() {
  mkdir -p "${base_dir}"
  if [[ ! -d "${repo_dir}/.git" ]]; then
    echo "cloning Penpot ${penpot_tag} into ${repo_dir}" >&2
    git clone --depth 1 --branch "${penpot_tag}" https://github.com/penpot/penpot.git "${repo_dir}"
  fi
}

prepare_package_version() {
  cd "${mcp_dir}"
  bash scripts/set-version >/dev/null
}

prepare_build_policy() {
  cd "${mcp_dir}"
  npm pkg set \
    'pnpm.onlyBuiltDependencies[0]=esbuild' \
    'pnpm.onlyBuiltDependencies[1]=sharp' >/dev/null
}

install_if_needed() {
  cd "${mcp_dir}"
  if [[ "${force_install}" == "1" || ! -d node_modules ]]; then
    corepack pnpm install
    corepack pnpm rebuild
  fi
}

build_if_needed() {
  cd "${mcp_dir}"
  if [[ "${force_build}" == "1" || ! -f packages/server/dist/index.js || ! -f packages/plugin/dist/plugin.js ]]; then
    corepack pnpm run build
  fi
}

print_summary() {
  cd "${mcp_dir}"
  local version
  version="$(node -p "require('./package.json').version")"
  cat <<EOF
Penpot MCP runtime ready
  tag:      ${penpot_tag}
  version:  ${version}
  path:     ${mcp_dir}
  manifest: http://localhost:4400/manifest.json
  mcp:      http://localhost:4401/mcp
  ws:       ws://localhost:4402
EOF
}

ensure_corepack
ensure_repo
prepare_package_version
prepare_build_policy
install_if_needed
build_if_needed
print_summary

if [[ "${bootstrap_only}" == "1" ]]; then
  exit 0
fi

echo "starting Penpot MCP runtime from ${mcp_dir}" >&2
cd "${mcp_dir}"
exec corepack pnpm run start
