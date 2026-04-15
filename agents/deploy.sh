#!/usr/bin/env bash
# Sync agent instructions from git to live Paperclip container
# Usage: ./agents/deploy.sh
#
# Prerequisites: SSH key auth to the server
# Override server: PAPERCLIP_SSH_HOST=user@host ./agents/deploy.sh
#
# What it does:
#   1. Runs CLI company export as backup (safety net)
#   2. For each agent with AGENTS.md, copies it to the Paperclip container
#   3. Verifies file sizes match after copy
#
# Paperclip re-reads instructions from disk on each agent wake (routine or heartbeat).
# No container restart needed — changes take effect on the next routine/heartbeat fire.

set -euo pipefail

SERVER="${PAPERCLIP_SSH_HOST:-root@t.ffmemes.com}"
COMPANY_ID="96ee7b2e-6df2-43c8-bbe3-53e19297308a"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Agent name -> ID mapping (these are public — already in agents/README.md)
AGENT_NAMES="ceo analyst cto staff-engineer qa release-engineer comms"
agent_id() {
  case "$1" in
    ceo)              echo "e782143b-5ecf-484c-ad87-939592c79dbb" ;;
    analyst)          echo "9c87d840-7041-49d8-8436-00b6dcb10971" ;;
    cto)              echo "ebdad67a-e5fa-4b1f-ad40-86a64a43f45f" ;;
    staff-engineer)   echo "1a323bb6-2b4d-46bf-9c33-7971fa1673d5" ;;
    qa)               echo "4b02ab32-596b-4339-a397-eb88559a266f" ;;
    release-engineer) echo "b5b71b81-eeed-4767-8970-8523786779d7" ;;
    comms)            echo "eac86c1e-8708-469c-af17-2925e356e4fb" ;;
    *)                echo "" ;;
  esac
}

echo "Deploying agent instructions to $SERVER..."

# Find Paperclip container
CONT=$(ssh "$SERVER" "docker ps --format '{{.Names}}' | grep k4w804 | head -1")
if [ -z "$CONT" ]; then
  echo "ERROR: Paperclip container not found on $SERVER" >&2
  exit 1
fi
echo "Container: $CONT"
echo ""

# Run backup via CLI company export (preferred over legacy backup.sh)
echo "Running backup via CLI company export..."
BACKUP_DIR="$SCRIPT_DIR/backup"
mkdir -p "$BACKUP_DIR"
ssh "$SERVER" "docker exec $CONT npx paperclipai company export $COMPANY_ID --include company,agents --out /tmp/paperclip-export 2>/dev/null" \
  && scp -rq "$SERVER:/tmp/paperclip-export" "$BACKUP_DIR/export-$(date +%Y%m%d-%H%M%S)" \
  && ssh "$SERVER" "rm -rf /tmp/paperclip-export" \
  && echo "  Backup saved to $BACKUP_DIR/export-$(date +%Y%m%d-%H%M%S)" \
  || echo "  WARNING: CLI backup failed, continuing without backup"
echo ""

# Sync each agent
SYNCED=0
ERRORS=0
for agent in $AGENT_NAMES; do
  AGENTS_FILE="$SCRIPT_DIR/$agent/AGENTS.md"
  if [ ! -f "$AGENTS_FILE" ]; then
    continue
  fi

  AGENT_ID=$(agent_id "$agent")
  if [ -z "$AGENT_ID" ]; then
    echo "  SKIP $agent — unknown agent ID" >&2
    continue
  fi

  REMOTE_PATH="/paperclip/instances/default/companies/$COMPANY_ID/agents/$AGENT_ID/instructions/AGENTS.md"

  # Copy to server, ensure target dir exists, copy into container
  scp -q "$AGENTS_FILE" "$SERVER:/tmp/deploy-$agent.md"
  ssh "$SERVER" "docker exec $CONT mkdir -p '$(dirname "$REMOTE_PATH")' && docker cp /tmp/deploy-$agent.md '$CONT:$REMOTE_PATH' && rm -f /tmp/deploy-$agent.md"

  # Verify file size matches (wc runs inside the container)
  REMOTE_SIZE=$(ssh "$SERVER" "docker exec $CONT sh -c 'wc -c < \"$REMOTE_PATH\"' 2>/dev/null || echo 0")
  LOCAL_SIZE=$(wc -c < "$AGENTS_FILE")
  if [ "$REMOTE_SIZE" -eq "$LOCAL_SIZE" ]; then
    echo "  OK  $agent ($AGENT_ID) — $LOCAL_SIZE bytes"
  else
    echo "  ERR $agent — size mismatch (local=$LOCAL_SIZE remote=$REMOTE_SIZE)" >&2
    ERRORS=$((ERRORS + 1))
  fi
  SYNCED=$((SYNCED + 1))
done

echo ""
echo "Synced $SYNCED agents. Changes take effect on next routine/heartbeat wake."
if [ "$ERRORS" -gt 0 ]; then
  echo "WARNING: $ERRORS agents had size mismatches — check manually." >&2
  exit 1
fi
