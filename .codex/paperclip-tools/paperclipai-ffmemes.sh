#!/usr/bin/env bash
set -euo pipefail

# Repo-local Paperclip entrypoint for FFmemes agent work. This keeps Paperclip
# usage explicit and task-scoped instead of relying on a global MCP install.

tool_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$tool_root/../.." && pwd)"
env_file="$tool_root/paperclip.env"

if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

if [[ -z "${PAPERCLIP_API_URL:-}" && -n "${PAPERCLIP_URL:-}" ]]; then
  export PAPERCLIP_API_URL="$PAPERCLIP_URL"
fi

export PAPERCLIP_COMPANY_ID="${PAPERCLIP_COMPANY_ID:-96ee7b2e-6df2-43c8-bbe3-53e19297308a}"
export PAPERCLIP_CONTEXT="${PAPERCLIP_CONTEXT:-$tool_root/context.json}"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-$tool_root/.npm-cache}"
export npm_config_cache="$NPM_CONFIG_CACHE"
mkdir -p "$NPM_CONFIG_CACHE"

if [[ -n "${PAPERCLIPAI_BIN:-}" ]]; then
  exec "$PAPERCLIPAI_BIN" "$@"
fi

local_bin="$repo_root/node_modules/.bin/paperclipai"

if [[ -x "$local_bin" ]]; then
  exec "$local_bin" "$@"
fi

if command -v paperclipai >/dev/null 2>&1; then
  exec paperclipai "$@"
fi

version="${PAPERCLIPAI_VERSION:-2026.513.0}"
exec npx --yes "paperclipai@$version" "$@"
