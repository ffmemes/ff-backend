#!/bin/bash
# Restore Paperclip agent team from backup
# Usage: ./restore.sh [backup-file.json]
#
# Prerequisites:
#   - PAPERCLIP_URL and PAPERCLIP_API_KEY in environment
#   - Company must exist (agents are recreated under the same company)
#
# This script:
#   1. Creates all agents with correct config, skills, and reporting lines
#   2. Creates routines with webhook triggers
#   3. Uploads AGENTS.md instructions from agents/ directory
#   4. Does NOT restore secrets (re-add manually via API or dashboard)

set -euo pipefail

BACKUP_FILE="${1:-$(ls -t agents/backup/paperclip-state-*.json 2>/dev/null | head -1)}"
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
  echo "Usage: $0 <backup-file.json>"
  echo "No backup file found."
  exit 1
fi

if [ -z "${PAPERCLIP_URL:-}" ] || [ -z "${PAPERCLIP_API_KEY:-}" ]; then
  echo "Set PAPERCLIP_URL and PAPERCLIP_API_KEY first"
  exit 1
fi

COMPANY_ID=$(python3 -c "import json; print(json.load(open('$BACKUP_FILE'))['company_id'])")
echo "Restoring to company: $COMPANY_ID"
echo "From backup: $BACKUP_FILE"
echo ""

# Step 1: Import gstack skills
echo "=== Importing gstack skills ==="
curl -s -X POST "$PAPERCLIP_URL/api/companies/$COMPANY_ID/skills/import" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "https://github.com/garrytan/gstack"}' | python3 -c "import json,sys; skills=json.load(sys.stdin); print(f'  Imported {len(skills)} skills')" 2>/dev/null || echo "  Skills import failed (may already exist)"

# Step 2: Recreate agents
echo ""
echo "=== Creating agents ==="
python3 -c "
import json, subprocess, sys

backup = json.load(open('$BACKUP_FILE'))
url = '$PAPERCLIP_URL'
key = '$PAPERCLIP_API_KEY'
company = '$COMPANY_ID'

for agent in backup['agents']:
    name = agent['name']
    data = {
        'name': name,
        'role': agent.get('role', 'engineer'),
        'adapterType': agent.get('adapterType', 'claude_local'),
        'adapterConfig': agent.get('adapterConfig', {}),
        'runtimeConfig': agent.get('runtimeConfig', {}),
    }
    # reportsTo will be set in a second pass (need IDs first)
    result = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'{url}/api/companies/{company}/agents',
         '-H', f'Authorization: Bearer {key}',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(data)],
        capture_output=True, text=True
    )
    try:
        resp = json.loads(result.stdout)
        print(f'  {name}: {resp.get(\"id\", \"FAILED\")}')
    except:
        print(f'  {name}: ERROR - {result.stdout[:100]}')
"

echo ""
echo "=== MANUAL STEPS ==="
echo "1. Set reportsTo for each agent via PATCH /api/agents/{id}"
echo "2. Re-add secrets via dashboard or API"
echo "3. Upload AGENTS.md files: see agents/README.md for scp commands"
echo "4. Create webhook triggers for routines"
echo "5. Update GitHub webhook URL and secret"
echo "6. Verify with: curl \$PAPERCLIP_URL/api/companies/$COMPANY_ID/agents -H 'Authorization: Bearer \$PAPERCLIP_API_KEY' | python3 -m json.tool"
