#!/bin/bash
# Automated Paperclip state backup
# Usage: ./agents/backup/backup.sh
#
# Prerequisites: PAPERCLIP_URL and PAPERCLIP_API_KEY in environment
#
# Keeps the last 10 backups, deletes older ones.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPANY_ID="96ee7b2e-6df2-43c8-bbe3-53e19297308a"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
OUTFILE="$SCRIPT_DIR/paperclip-state-${TIMESTAMP}.json"

if [ -z "${PAPERCLIP_URL:-}" ] || [ -z "${PAPERCLIP_API_KEY:-}" ]; then
  echo "ERROR: Set PAPERCLIP_URL and PAPERCLIP_API_KEY" >&2
  exit 1
fi

API="$PAPERCLIP_URL/api/companies/$COMPANY_ID"
AUTH="Authorization: Bearer $PAPERCLIP_API_KEY"

# Fetch all state to temp files
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

curl -sf "$API/agents" -H "$AUTH" > "$TMP/agents.json"
curl -sf "$API/routines" -H "$AUTH" > "$TMP/routines.json"
curl -sf "$API/skills" -H "$AUTH" > "$TMP/skills.json"

# Assemble backup
python3 -c "
import json
backup = {
    'timestamp': '$TIMESTAMP',
    'company_id': '$COMPANY_ID',
    'agents': json.load(open('$TMP/agents.json')),
    'routines': json.load(open('$TMP/routines.json')),
    'skills': json.load(open('$TMP/skills.json')),
}
with open('$OUTFILE', 'w') as f:
    json.dump(backup, f, indent=2)
"

echo "Backup saved: $OUTFILE"

# Prune: keep only the 10 most recent backups
ls -t "$SCRIPT_DIR"/paperclip-state-*.json 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
echo "Pruned old backups (keeping 10)"
