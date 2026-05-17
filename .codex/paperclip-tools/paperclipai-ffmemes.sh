#!/usr/bin/env bash
set -euo pipefail

# Repo-local Paperclip entrypoint for FFmemes agent work. This keeps Paperclip
# usage explicit and task-scoped instead of relying on a global MCP install.

if [[ -n "${PAPERCLIPAI_BIN:-}" ]]; then
  exec "$PAPERCLIPAI_BIN" "$@"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
local_bin="$repo_root/node_modules/.bin/paperclipai"

if [[ -x "$local_bin" ]]; then
  exec "$local_bin" "$@"
fi

if command -v paperclipai >/dev/null 2>&1; then
  exec paperclipai "$@"
fi

version="${PAPERCLIPAI_VERSION:-2026.513.0}"
exec npx --yes "paperclipai@$version" "$@"
