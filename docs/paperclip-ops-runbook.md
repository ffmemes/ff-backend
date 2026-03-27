# Paperclip Operations Runbook

## Overview

Paperclip manages the autonomous AI agent team for @ffmemesbot.
Dashboard: `https://org.ffmemes.com` (URL is public, auth required).

All secrets (API keys, DB credentials, tokens) live in **environment variables** — never in this repo.
Required env vars for local management: `PAPERCLIP_URL`, `PAPERCLIP_API_KEY` (set in `~/.zshrc` or `.env`).

## Architecture

```
org.ffmemes.com (Paperclip dashboard)
  ├── Coolify app: k4w804sco4s8kc88kwcw0ow4
  ├── External PostgreSQL (shared Coolify DB service)
  │   └── Database: paperclip
  ├── Named volume: paperclip-data → /paperclip
  │   ├── .claude/         # Claude CLI auth (survives redeploy)
  │   ├── .codex/          # Codex auth (survives redeploy)
  │   ├── .config/gh/      # GitHub CLI auth (survives redeploy)
  │   ├── bin/             # Persistent tool binaries (gh, sentry)
  │   └── instances/default/
  │       ├── config.json  # Paperclip server config
  │       ├── companies/   # Agent instructions, workspaces
  │       └── logs/        # Runtime logs
  └── Agents run Claude CLI / Codex as subprocesses
```

## Managing from MacBook

Set these env vars locally (in `~/.zshrc` or `.env`):
```bash
export PAPERCLIP_URL="https://org.ffmemes.com"
export PAPERCLIP_API_KEY="<your-board-api-key>"  # Get from dashboard Settings
```

### Common API operations

```bash
# List agents
curl -s "$PAPERCLIP_URL/api/companies/<company-id>/agents" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" | jq '.[].name'

# List routines
curl -s "$PAPERCLIP_URL/api/companies/<company-id>/routines" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" | jq '.[].title'

# List secrets (names only, values encrypted)
curl -s "$PAPERCLIP_URL/api/companies/<company-id>/secrets" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" | jq '.[].name'

# Create a secret
curl -s -X POST "$PAPERCLIP_URL/api/companies/<company-id>/secrets" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"SECRET_NAME","key":"SECRET_NAME","value":"secret-value"}'

# Import gstack skills
curl -s -X POST "$PAPERCLIP_URL/api/companies/<company-id>/skills/import" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "https://github.com/garrytan/gstack"}'

# Wake an agent manually
curl -s -X POST "$PAPERCLIP_URL/api/agents/<agent-id>/wake" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY"
```

### SSH operations

```bash
ssh root@t.ffmemes.com
CONT=$(docker ps --format '{{.Names}}' | grep k4w804 | head -1)

# Re-auth tools (interactive — needed after volume loss only)
docker exec -it $CONT claude login
docker exec -it $CONT codex login --device-auth
docker exec -it $CONT gh auth login

# Upload agent instructions after editing locally
scp agents/<name>/AGENTS.md root@t.ffmemes.com:/tmp/agent.md
ssh root@t.ffmemes.com "docker cp /tmp/agent.md $CONT:/paperclip/instances/default/companies/<company-id>/agents/<agent-id>/instructions/AGENTS.md"
```

## Agent Team

| Agent | Role | Reports To | Heartbeat | Model |
|-------|------|-----------|-----------|-------|
| CEO | Strategic decisions, experiments | — | Daily | opus |
| Analyst | Metrics, anomaly detection | CEO | 6h | sonnet |
| CTO | Engineering, PRs | CEO | On-demand | sonnet |
| QA Engineer | Log monitoring, bug reports | CEO | 6h | sonnet |
| Release Engineer | PR merge, deploy verify | CTO | On-demand | sonnet |
| Comms Manager | Public TG channel updates | CEO | On-demand | sonnet |

Agent instructions: `agents/<name>/AGENTS.md` in this repo.

## Routines

| Routine | Agent | Schedule (UTC) | What it does |
|---------|-------|----------------|-------------|
| Daily Analyst Report | Analyst | `0 6 * * *` | Query metrics, detect anomalies, write report |
| QA Log Scan | QA | `0 */6 * * *` | Sentry, Coolify logs, DB health |
| Weekly CEO Review | CEO | `0 9 * * 1` | Retro, experiments, priorities |
| gstack Update Check | CEO | `0 3 * * *` | Update skills, review changelog |

## Plugins

### Telegram Bot (`paperclip-plugin-telegram` v0.2.1)

Bidirectional Telegram integration for managing Paperclip via @ffnerdbot (separate from production @ffmemesbot).

**Plugin ID**: `a6ad4ec4-f158-47b4-bed5-8057dec86f23`
**Bot**: @ffnerdbot (user_id `49820636` only)
**Features**: push notifications, bot commands, voice transcription (Whisper), agent escalation, daily digest

**Configuration** (stored in `plugin_config` table, survives redeploys):
- `defaultChatId`: `49820636` — all notifications go to the owner
- `escalationChatId`: `49820636` — escalations also go to the owner
- `transcriptionApiKeyRef`: uses existing `OPENAI_API_KEY` secret for Whisper
- `dailyDigestEnabled`: true, at 09:00 UTC
- All notification types enabled

**Persistence**: npm package lives in `/paperclip/instances/default/plugins/` (named volume).
Config and secrets are in external PostgreSQL. Both survive redeploys.

**If plugin is missing after redeploy**:
```bash
# Re-install via API (config auto-loads from DB)
curl -X POST https://org.ffmemes.com/api/plugins/install \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"packageName":"paperclip-plugin-telegram"}'
```

**Available bot commands** (in @ffnerdbot chat):
- `/status` — system overview
- `/issues` — list open issues
- `/agents` — list agents and status
- `/approve` — approve/reject pending requests
- `/connect ffmemes` — link chat to company
- `/acp spawn/status/cancel/close` — manage agent sessions
- Voice messages auto-transcribed via Whisper

## Secrets (Paperclip company secrets)

These are encrypted in Paperclip DB and injected as env vars during agent runs:

| Secret | Used by | Purpose |
|--------|---------|---------|
| `ANALYST_DATABASE_URL` | Analyst, QA | Read-only prod DB access |
| `COOLIFY_ACCESS_TOKEN` | QA | Coolify API for container logs |
| `COOLIFY_BASE_URL` | QA | Coolify API URL |
| `SENTRY_DSN` | QA | Sentry project DSN |
| `SENTRY_AUTH_TOKEN` | QA | Sentry CLI authentication |
| `OPENAI_API_KEY` | All (Codex), Telegram plugin (Whisper) | OpenAI API for Codex + voice transcription |
| `TEST_DATABASE_URL` | CTO | Test/staging DB for safe experiments |
| `TELEGRAM_BOT_TOKEN` | Telegram plugin | @ffnerdbot token (NOT @ffmemesbot!) |

## Persistent Tool Binaries

Tools installed to `/paperclip/bin/` survive redeploys (on named volume).
Agents need `PATH=/paperclip/bin:$PATH` to find them.

| Tool | Path | Install command |
|------|------|----------------|
| `gh` | `/paperclip/bin/gh` | `curl + tar` from GitHub releases |
| `sentry` | `/paperclip/bin/sentry` | `npm install sentry` (needs SQLite fix) |

Post-deployment command (runs after each Coolify deploy) is configured to reinstall these,
but runs as non-root `node` user — see Coolify Quirks below.

---

## NEVER DO THIS

1. **Never change `PAPERCLIP_DEPLOYMENT_EXPOSURE` or `PAPERCLIP_DEPLOYMENT_MODE`** — breaks auth
2. **Never run `npx paperclipai onboard`** on an existing install — WIPES the database
3. **Never commit secrets** to this repo — it's PUBLIC
4. **Never redeploy without verifying named volume** is configured in Coolify Storages

## Coolify Quirks (battle-tested 2026-03-27)

### Named volume is REQUIRED
- Coolify's Dockerfile `VOLUME /paperclip` creates anonymous volumes by default
- Anonymous volumes are NOT reused across redeploys — each deploy gets a fresh one
- **Fix**: Add `paperclip-data` named volume in Coolify → app → Storages tab, mount at `/paperclip`
- Without this, ALL data (config, auth, agent state) is lost on every redeploy

### Post-deployment command runs as non-root
- Coolify executes `post_deployment_command` via `docker exec` as the container's default user (`node`)
- `apt-get` fails with "Permission denied" — cannot install system packages
- **Workaround**: Install tools to user-writable paths (`/paperclip/bin/`, `npm install --prefix`)
- Or install tools to `/paperclip/bin/` once manually and they persist on the named volume

### Post-deployment command container resolution (Coolify bug #9076)
- If `post_deployment_command_container` field is set to the app UUID, Coolify may fail to find the container
- **Fix**: Leave the container field empty — Coolify auto-detects
- Fix PR #9165 is open but not merged as of beta.470

### `--name` in custom docker run options is ignored
- Coolify only supports specific options: `--cap-add`, `--shm-size`, `--gpus`, `--hostname`, etc.
- `--name` is NOT in the whitelist — container naming is managed by Coolify internally
- Container names follow pattern: `{app-uuid}-{timestamp}`

### Config.json recovery
If `config.json` is lost but DB is intact, recreate manually — **DO NOT run onboard**:
```bash
CONT=$(docker ps --format '{{.Names}}' | grep k4w804 | head -1)
# Get DATABASE_URL from Coolify env vars first, then:
docker exec $CONT sh -c 'cat > /paperclip/instances/default/config.json << '\''EOF'\''
{
  "\$meta": {"version": 1, "generator": "manual", "source": "recovery"},
  "database": {"provider": "external-postgres", "connectionString": "PASTE_DATABASE_URL_HERE"},
  "logging": {"provider": "file", "mode": "file", "logDir": "/paperclip/instances/default/logs"},
  "server": {
    "host": "0.0.0.0", "port": 3100,
    "deploymentMode": "authenticated", "deploymentExposure": "private",
    "publicUrl": "https://org.ffmemes.com",
    "authBaseUrlMode": "explicit", "authPublicBaseUrl": "https://org.ffmemes.com",
    "allowedHostnames": ["org.ffmemes.com", "localhost"]
  }
}
EOF'
docker restart $CONT
```

## Incidents

### 2026-03-27: Full data wipe + rebuild

**Sequence**: Changed env var → auth broke → config.json lost → ran `onboard` → wiped DB → rebuilt from scratch with external Postgres + named volume.

**What survived**: Agent instructions (in git), bot production data (separate DB).
**What was lost**: Task history, run logs, routine execution history, auth tokens.

**Fixes applied**:
1. External PostgreSQL (data survives redeploys)
2. Named volume `paperclip-data` (auth/config survives redeploys)
3. Agent configs stored in git (`agents/` directory)
4. This runbook documents all recovery procedures
5. Board API key generated via direct DB insert (no UI dependency)

### Pre-redeploy checklist

1. Verify named volume `paperclip-data` is in Coolify Storages
2. `docker exec $CONT cat /paperclip/instances/default/config.json` — should exist
3. Do NOT change deployment exposure/mode env vars

### Post-redeploy checklist (MANUAL — Coolify post-deploy is broken, bug #9076)

After every redeploy, run this to install system tools:

```bash
ssh root@t.ffmemes.com
CONT=$(docker ps --format '{{.Names}}' | grep k4w804 | head -1)

# Install gh and sentry-cli (runs as root)
docker exec -u root $CONT sh -c "apt-get update -qq && apt-get install -y -qq gh && npm install -g @sentry/cli sentry"

# Verify
docker exec $CONT sh -c "gh --version; sentry-cli --version; claude --version; codex login status"
```

Tools on `/paperclip/bin/` (named volume) survive redeploys but agents may not have them in PATH.
System-wide installs via `apt-get` and `npm install -g` do NOT survive redeploys.

### Verify after redeploy

```bash
# Auth survived?
docker exec $CONT sh -c "test -f /paperclip/.claude/.credentials.json && echo claude:OK"
docker exec $CONT sh -c "test -f /paperclip/.codex/auth.json && echo codex:OK"
docker exec $CONT sh -c "test -f /paperclip/.config/gh/hosts.yml && echo gh:OK"

# API works?
curl -s https://org.ffmemes.com/api/health

# Telegram plugin loaded?
curl -s "$PAPERCLIP_URL/api/plugins" -H "Authorization: Bearer $PAPERCLIP_API_KEY" | python3 -c "
import sys,json
plugins = json.load(sys.stdin)
tg = [p for p in plugins if p['pluginKey'] == 'paperclip-plugin-telegram']
if tg: print(f'telegram-plugin: {tg[0][\"status\"]}')
else: print('telegram-plugin: MISSING — reinstall via API (see Plugins section)')
"

# Agents listed?
curl -s "$PAPERCLIP_URL/api/companies/<company-id>/agents" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" | jq '.[].name'
```
