#!/usr/bin/env bash
# Sync agent instructions and adapter config from this repo to live Paperclip.
# Uses Paperclip-native HTTP API only — no SSH, no docker cp.
#
# Usage:
#   PAPERCLIP_URL=https://org.ffmemes.com PAPERCLIP_API_KEY=... ./agents/deploy.sh
#   ./agents/deploy.sh --dry-run    # show what would change without applying
#
# What it does, per agent slug found under agents/<slug>/:
#   1. Resolve agent ID by slug via GET /api/companies/<id>/agents
#   2. PUT every *.md in agents/<slug>/ to /api/agents/<id>/instructions-bundle/file
#   3. PATCH /api/agents/<id> with adapter/runtime/env config from .paperclip.yaml
#
# Paperclip records audit + config revision per write — rollback via API if needed.

set -euo pipefail

COMPANY_ID="96ee7b2e-6df2-43c8-bbe3-53e19297308a"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

: "${PAPERCLIP_URL:?Set PAPERCLIP_URL (e.g. https://org.ffmemes.com)}"
: "${PAPERCLIP_API_KEY:?Set PAPERCLIP_API_KEY}"

api() {
  local method=$1 path=$2
  shift 2
  local body
  local code
  body=$(mktemp)
  code=$(curl -s -X "$method" \
    -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
    -H "Content-Type: application/json" \
    -o "$body" -w "%{http_code}" \
    "$PAPERCLIP_URL$path" "$@")
  if [[ "$code" -ge 400 ]]; then
    echo "  HTTP $code: $(cat "$body")" >&2
    rm -f "$body"
    return 1
  fi
  cat "$body"
  rm -f "$body"
}

echo "Syncing agent instructions to $PAPERCLIP_URL (company=$COMPANY_ID)"
[[ $DRY_RUN -eq 1 ]] && echo "  (dry-run mode — no writes)"

# Fetch agent list once; build slug → id map via jq
AGENTS_JSON=$(api GET "/api/companies/$COMPANY_ID/agents")

slug_to_id() {
  echo "$AGENTS_JSON" | jq -r --arg slug "$1" '.[] | select(.urlKey == $slug) | .id' | head -1
}

errors=0
synced_files=0

for agent_dir in "$SCRIPT_DIR"/*/; do
  slug=$(basename "$agent_dir")
  [[ -f "$agent_dir/AGENTS.md" ]] || continue
  agent_id=$(slug_to_id "$slug")

  if [[ -z "$agent_id" ]]; then
    echo "  SKIP $slug — no matching agent in prod (urlKey miss)"
    continue
  fi

  for md in "$agent_dir"*.md; do
    [[ -f "$md" ]] || continue
    fname=$(basename "$md")
    size=$(wc -c < "$md")

    if [[ $DRY_RUN -eq 1 ]]; then
      echo "  WOULD PUT $slug/$fname ($size B) → agent $agent_id"
      continue
    fi

    payload=$(jq -n --arg path "$fname" --rawfile content "$md" '{path: $path, content: $content}')
    if echo "$payload" | api PUT "/api/agents/$agent_id/instructions-bundle/file?companyId=$COMPANY_ID" --data @- >/dev/null; then
      echo "  OK   $slug/$fname ($size B)"
      synced_files=$((synced_files + 1))
    else
      echo "  ERR  $slug/$fname ($size B) — PUT failed" >&2
      errors=$((errors + 1))
    fi
  done
done

echo
echo "Syncing adapter config + env + skills + routine descriptions (diff-first PATCH)..."

# Pass 2: adapter type/config, env secret refs, desiredSkills, runtime.heartbeat,
# permissions, and routine descriptions declared under agents/<slug>/routines/.
# Diff first; PATCH only on change so we don't spam Paperclip's config-revision history.
COMPANY_ID="$COMPANY_ID" SCRIPT_DIR="$SCRIPT_DIR" DRY_RUN="$DRY_RUN" \
  python3 "$SCRIPT_DIR/_sync_config.py" || {
  echo "Config sync failed." >&2
  errors=$((errors + 1))
}

echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Dry-run complete. Re-run without --dry-run to apply."
elif [[ $errors -gt 0 ]]; then
  echo "Synced $synced_files files; $errors errors during apply."
  exit 1
else
  echo "Synced $synced_files files. Changes take effect on next agent wake."
fi
