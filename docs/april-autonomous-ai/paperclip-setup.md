# Paperclip Setup for FFMemes Bot

## Local Instance
```
Dashboard: http://localhost:3100
API: http://127.0.0.1:3100/api
Database: ~/.paperclip/instances/default/db (embedded PG, port 54329)
Config: ~/.paperclip/instances/default/config.json
```

## Company
- **Name**: FFMemes Bot
- **ID**: 12eb8c61-ecaf-4203-ab75-920f12276237
- **Prefix**: FFM

## Agents

| Name | Role | ID | Heartbeat | Description |
|------|------|-----|-----------|-------------|
| analyst | researcher | 57061809-9142-42c9-8fdb-4b2316b63d66 | Daily | Monitors metrics, produces reports |
| ceo | ceo | cb468934-4acb-48e9-b2f3-164b7d09b2a4 | Daily | Reviews reports, manages experiments |

## CLI Commands

```bash
# Start Paperclip
npx paperclipai run

# Trigger a heartbeat manually
npx paperclipai heartbeat run --agent-id <AGENT_ID> --source on_demand --trigger manual --debug

# List agents
npx paperclipai agent list --company-id <COMPANY_ID>

# Get agent details
npx paperclipai agent get <AGENT_ID>

# Diagnostics
npx paperclipai doctor

# Backup database
npx paperclipai db:backup
```

## Agent Configuration

Each agent uses:
- **Adapter**: `claude_local` (spawns Claude Code CLI)
- **Model**: `claude-sonnet-4-6`
- **Working dir**: `/Users/ohld/Documents/GitHub/ff-backend`
- **Instructions**: `CLAUDE.md` (main) + `agents/<name>/AGENTS.md` (per-agent)
- **Permissions**: `dangerouslySkipPermissions: true` (required for unattended operation)

## API Endpoints (unauthenticated in local mode)

```
GET  /api/health                           # Health check
GET  /api/companies                        # List companies
POST /api/companies                        # Create company
GET  /api/companies/{id}/agents            # List agents
POST /api/companies/{id}/agents            # Create agent
```

Note: No PATCH/PUT/DELETE for agents via API. Use dashboard for updates.

## Safety Notes
- All agent configs reference local file paths — update when deploying to server
- `dangerouslySkipPermissions` means agents can run ANY command
- Agent instruction files (`AGENTS.md`) are the primary safety boundary
- Pre-commit hook catches secrets in git (`.git/hooks/pre-commit`)
- Read-only DB user for Analyst (can't modify prod data)
