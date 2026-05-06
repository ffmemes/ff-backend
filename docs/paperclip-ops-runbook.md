# Paperclip Operations Runbook

## Overview

Paperclip manages the autonomous AI agent team for @ffmemesbot.
Dashboard: `https://org.ffmemes.com` (URL is public, auth required).
**Version**: 2026.416.0 (deployed from `ohld/paperclip` fork on 2026-04-16).

All secrets (API keys, DB credentials, tokens) live in **environment variables** — never in this repo.
Required env vars for local management: `PAPERCLIP_URL`, `PAPERCLIP_API_KEY` (set in `~/.zshrc` or `.env`).

### MCP Server (v2026.416.0+)

Paperclip API is available as an MCP tool server via `@paperclipai/mcp-server`. Configured in two places:

**Local (MacBook, Claude Code hosts)**: register via `claude mcp add` CLI (writes to `~/.claude.json` under the project entry). **Do NOT put `mcpServers` in `.claude/settings.local.json` — Claude Code does not read that key there.** Codex sessions can use the same Paperclip HTTP API with `PAPERCLIP_URL` + `PAPERCLIP_API_KEY` when MCP is unavailable.

```bash
source ~/.zshrc   # loads PAPERCLIP_URL + PAPERCLIP_API_KEY
claude mcp add paperclip -s local \
  -e PAPERCLIP_API_URL="$PAPERCLIP_URL" \
  -e PAPERCLIP_API_KEY="$PAPERCLIP_API_KEY" \
  -e PAPERCLIP_COMPANY_ID=96ee7b2e-6df2-43c8-bbe3-53e19297308a \
  -- npx -y @paperclipai/mcp-server

claude mcp list               # verify paperclip ✓ Connected
claude mcp get paperclip      # note: prints API key in plaintext — do not screen-share
```

**Server (agents)**: `/paperclip/.claude/settings.json` — uses `http://localhost:3100` (internal) and inherits `$PAPERCLIP_API_KEY` from Paperclip agent runtime.

34 MCP tools available (issues, agents, comments, documents, approvals, projects, goals) + `paperclipApiRequest` escape hatch for anything not covered.

Agent prompts reference MCP tools instead of curl. See agent `AGENTS.md` files for the tool list.

## Architecture

```
org.ffmemes.com (Paperclip dashboard)
  ├── Coolify app: k4w804sco4s8kc88kwcw0ow4
  ├── Git source: ohld/paperclip fork (master branch)
  │   └── Fork needed: upstream Dockerfile has hardcoded sha256 for GH CLI GPG key
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
  └── Agents run Claude CLI or Codex as subprocesses
```

## Managing from MacBook

Set these env vars locally (in `~/.zshrc` or `.env`):
```bash
export PAPERCLIP_URL="https://org.ffmemes.com"
export PAPERCLIP_API_KEY="<your-board-api-key>"  # Get from dashboard Settings
```

### CLI operations (v2026.403.0+)

Run on the server: `ssh root@t.ffmemes.com`, then `docker exec -it $CONT npx paperclipai <command>`.
Or locally with `--api-base` and `--api-key` flags.

```bash
# List agents
npx paperclipai agent list --company-id <company-id>

# List issues
npx paperclipai issue list --company-id <company-id>

# Create an issue
npx paperclipai issue create --company-id <company-id> --title "Fix bug" --body "Details..."

# Export company (backup)
npx paperclipai company export <company-id> --include company,agents,projects,issues

# Import company (restore)
npx paperclipai company import <path-or-url>

# Plugin management
npx paperclipai plugin list
npx paperclipai plugin install paperclip-plugin-telegram
npx paperclipai plugin inspect paperclip-plugin-telegram

# Disable all routines (maintenance)
npx paperclipai routines disable-all --company-id <company-id>

# Auth
npx paperclipai auth whoami
```

### API operations (MCP preferred, curl fallback)

With MCP server configured, use MCP tools from Claude Code for most operations:

```
# List issues (MCP)
paperclipListIssues

# Get/update issue (MCP)
paperclipGetIssue issueId=<id>
paperclipUpdateIssue issueId=<id> status="done"

# Create issue (MCP)
paperclipCreateIssue title="..." body="..."

# Escape hatch for any endpoint (MCP)
paperclipApiRequest method="GET" path="/api/companies/<id>/secrets"
paperclipApiRequest method="POST" path="/api/agents/<id>/wakeup"
```

Curl fallback (when MCP unavailable):
```bash
# List secrets (names only, values encrypted)
curl -s "$PAPERCLIP_URL/api/companies/<company-id>/secrets" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" | jq '.[].name'

# Create a secret
curl -s -X POST "$PAPERCLIP_URL/api/companies/<company-id>/secrets" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg value "$SECRET_VALUE" \
    '{"name":"SECRET_NAME","key":"SECRET_NAME","value":$value}')"

# Rotate an existing secret value; agents using version=latest pick it up
# on their next wake. PATCH edits metadata only; value rotation is POST /rotate.
curl -s -X POST "$PAPERCLIP_URL/api/secrets/<secret-id>/rotate" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg value "$SECRET_VALUE" '{"value":$value}')"

# Import gstack skills
curl -s -X POST "$PAPERCLIP_URL/api/companies/<company-id>/skills/import" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "https://github.com/garrytan/gstack"}'

# Wake an agent manually
curl -s -X POST "$PAPERCLIP_URL/api/agents/<agent-id>/wakeup" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source":"on_demand","reason":"manual verification"}'
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
# Preferred: use the deploy script (syncs all agents + runs backup)
./agents/deploy.sh
# Manual (single agent):
# scp agents/<name>/AGENTS.md root@t.ffmemes.com:/tmp/agent.md
# ssh root@t.ffmemes.com "docker cp /tmp/agent.md $CONT:/paperclip/instances/default/companies/<company-id>/agents/<agent-id>/instructions/AGENTS.md"
```

## Agent Team

| Agent | Role | Reports To | Activation | Adapter / model |
|-------|------|-----------|------------|-----------------|
| CEO | Strategic decisions, experiments | — | Weekly routine + daily heartbeat | `codex_local` / `gpt-5.5`, effort `xhigh` |
| Analyst | Metrics, anomaly detection | CEO | Routines only | `claude_local` / `claude-sonnet-4-6` |
| CTO | Engineering, PRs | CEO | On-demand | `codex_local` / `gpt-5.5`, effort `high` |
| Staff Engineer | PR review + merge for internal PRs | CTO | PR webhook routine | `codex_local` / `gpt-5.5`, effort `high` |
| QA Engineer | Log monitoring, bug reports | CTO | Schedule + Sentry webhook + API | `claude_local` / `claude-sonnet-4-6` |
| Release Engineer | Post-merge deploy verification | CTO | On-demand | `claude_local` / `claude-sonnet-4-6` |
| Comms Manager | Public TG channel updates | CEO | Daily heartbeat | `claude_local` / `claude-sonnet-4-6` |

Agent instructions: `agents/<name>/AGENTS.md` in this repo.
Deploy after editing: `./agents/deploy.sh`

## Routines

Start routine debugging with the compact audit helper instead of dumping raw
Paperclip JSON:

```bash
source ~/.zshrc
python scripts/paperclip_routine_audit.py --focus all
```

Outcome contracts live in `docs/agents/routine-observability.md`. In particular,
`@ffnerdbot` is an activity feed only; it is not the source of truth for whether
a routine produced a useful result.

| Routine | Agent | Schedule (UTC) | Trigger Type | What it does |
|---------|-------|----------------|-------------|--------------|
| Daily Analyst Report | Analyst | `19 6 * * *` | schedule + API | Query metrics, detect anomalies, write report |
| QA Log Scan | QA | `7 */3 * * *` | schedule + Sentry webhook + API | Sentry, Coolify logs, DB health, E2E smoke |
| Process Health Check | QA | `37 12 * * *` | schedule | Watchdog: verify all routines are running and succeeding |
| Weekly CEO Review | CEO | `11 9 * * 1` | schedule | Retro, experiments, priorities |
| Weekly Analyst Summary | Analyst | `23 9 * * 1` | schedule | Weekly summary for CEO review |
| gstack Update Check | CEO | `17 3 * * *` | schedule | Update skills, review changelog |
| Paperclip Update Check | CTO | `0 4 * * *` | schedule | Check for Paperclip updates |
| Daily Channel Post | Comms | `0 7 * * *` | schedule | Daily @ffmemes TG channel post; success means published, not only draft approved |
| PR Review | Staff Engineer | on PR event | 2 webhooks + API | Review PRs via GitHub Actions trigger |

## Plugins

### Telegram Bot (`paperclip-plugin-telegram` v0.2.3)

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
# Re-install via CLI (config auto-loads from DB)
npx paperclipai plugin install paperclip-plugin-telegram

# Or via API (legacy):
curl -X POST https://org.ffmemes.com/api/plugins/install \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"packageName":"paperclip-plugin-telegram"}'

# Verify status:
npx paperclipai plugin inspect paperclip-plugin-telegram
```

**Available bot commands** (in @ffnerdbot chat):
- `/status` — system overview
- `/issues` — list open issues
- `/agents` — list agents and status
- `/approve` — approve/reject pending requests
- `/connect ffmemes` — link chat to company
- `/acp spawn/status/cancel/close` — manage agent sessions
- Voice messages auto-transcribed via Whisper

## Webhook Triggers & Signing Modes (v2026.416.0+)

Paperclip triggers now support multiple signing modes:
- **`bearer`** (default) — `Authorization: Bearer <secret>` header
- **`hmac_sha256`** — Paperclip-native HMAC with `X-Paperclip-Signature`
- **`github_hmac`** (NEW) — reads `X-Hub-Signature-256` header. Compatible with GitHub webhooks.
- **`none`** (NEW) — no auth, publicId in URL acts as shared secret.

### Current webhook setup (post PR #212, 2026-04-29)

| Source | Path | Auth | Notes |
|--------|------|------|-------|
| Sentry | Sentry Internal Integration → Paperclip trigger | none (publicId is the secret) | Internal Integration `paperclip-qa-alert-b86aa3` |
| GitHub | GH Actions (`notify-staff-engineer`) → Paperclip trigger | Bearer token | Direct call |
| Prefect | (none) | — | Failures surface via QA Log Scan 3h cron |
| Coolify | (none) | — | Was never actively used in practice |

**Sentry → Paperclip QA trigger** is fully direct since PR #212. Set up:
- QA routine `477f452d-06f3-421e-a274-7f09155bb5bb`, webhook trigger `30901464-a100-4cff-9515-9fdbcfc1a797`
- `signingMode: none` — `server/dist/services/routines.js` short-circuits all auth checks
- Public URL: `https://org.ffmemes.com/api/routine-triggers/public/18a2f9e439c396e9b21a02fa/fire`
- Sentry posts the raw payload (`{"action":"created","data":{"issue":{...}}}`); Paperclip stores it in `routine_run.triggerPayload` verbatim
- Trigger fires only on **issue creation**, not subsequent occurrences. To re-test, send an event with a unique exception class so Sentry creates a new issue group.

### How to test the Sentry path end-to-end

```bash
set -a; source .env; set +a
python3 -c "
import sentry_sdk, time
sentry_sdk.init(dsn='$SENTRY_DSN', environment='production')
class _SentryE2EProbe(Exception): pass
try:
    raise _SentryE2EProbe(f'sentry-paperclip e2e probe {int(time.time())}')
except Exception as e:
    sentry_sdk.capture_exception(e)
sentry_sdk.flush(timeout=10)
"

# Within ~15-30s, a new routine_execution issue (title 'QA Log Scan') should appear
# at https://org.ffmemes.com/issues, source='webhook', triggerId=30901464-...
```

### Reverting if Sentry → Paperclip breaks

```bash
# Flip trigger back to bearer mode
curl -X PATCH "https://org.ffmemes.com/api/routine-triggers/30901464-a100-4cff-9515-9fdbcfc1a797" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"signingMode":"bearer"}'

# Restore proxy: revert PR #212 in this repo. Until that's redeployed,
# Sentry deliveries will 401 because Paperclip is back in bearer mode without
# auth headers. Acceptable for short windows; QA cron runs every 3h regardless.
```

**Tradeoff accepted**: no Sentry HMAC verification, no Coolify UUID filter, no instant Prefect alert. Worst case is noisy QA scans (the routine has no user-input parsing — its agent always re-scans logs from scratch). The 24-char publicId provides URL-based obscurity; if it leaks, rotate via `POST /routine-triggers/:id/rotate-secret`.

## Secrets (Paperclip company secrets)

These are encrypted in Paperclip DB and injected as env vars during agent runs:

`agents/_sync_config.py` materializes env from `agents/.paperclip.yaml`: `kind: secret` becomes a Paperclip `secret_ref`, `kind: plain` is written directly, and missing required secrets fail the config sync before any PATCH. Optional missing secrets are omitted. Docs should name env var names and Paperclip secret names only, never secret IDs or values.

| Secret | Used by | Purpose |
|--------|---------|---------|
| `ANALYST_DATABASE_URL` | Analyst, QA, Comms | Read-only prod DB access. Comms also receives this as env `DATABASE_URL` by explicit CEO decision; this supports data reads, not `editorial_posts` writes. |
| `COOLIFY_ACCESS_TOKEN` | CTO, QA, Release Engineer | Coolify API for container logs |
| `COOLIFY_BASE_URL` | CTO, QA, Release Engineer | Coolify API URL |
| `SENTRY_AUTH_TOKEN` | CTO, QA | Sentry CLI authentication (read-only project scope) |
| `PREFECT_API_URL` | CTO, QA | Prefect API endpoint (`https://prefect.swanrate.com/api`) |
| `PREFECT_AUTH_STRING` | CTO, QA | Prefect API Basic auth credentials |
| `OPENAI_API_KEY` | All (Codex), Telegram plugin (Whisper) | OpenAI API for Codex + voice transcription |
| `TEST_DATABASE_URL` | CTO | Test/staging DB for safe experiments |
| `TELEGRAM_BOT_TOKEN` | Telegram plugin | @ffnerdbot token (NOT @ffmemesbot!) |

The least-privilege `comms_writer` role in `docs/comms/comms-writer-role-setup.sql` remains available as a future upgrade if Comms needs to persist `editorial_posts` rows from the agent runtime. Do not bind Comms to `FFMEMES_DATABASE_URL` or any full-write app DB secret.

QA runtime access is considered degraded unless all of these are present in the live QA `adapterConfig.env`: `PATH` with `/paperclip/bin`, `ANALYST_DATABASE_URL`, `COOLIFY_BASE_URL`, `COOLIFY_ACCESS_TOKEN`, `SENTRY_AUTH_TOKEN`, `PREFECT_AUTH_STRING`.

## Persistent Tool Binaries

Tools installed to `/paperclip/bin/` survive redeploys (on named volume).
Agents need `PATH=/paperclip/bin:$PATH` to find them.

| Tool | Path | Install command |
|------|------|----------------|
| `gh` | `/paperclip/bin/gh` | `curl + tar` from GitHub releases |
| `codex` | `/paperclip/bin/codex` | `npm install --prefix /paperclip/.npm-global @openai/codex@latest && ln -sf /paperclip/.npm-global/node_modules/.bin/codex /paperclip/bin/codex` |
| `sentry` / `sentry-cli` | `/paperclip/bin/sentry` or system path | `npm install --prefix /paperclip/.npm-global sentry @sentry/cli && ln -sf /paperclip/.npm-global/node_modules/.bin/sentry /paperclip/bin/sentry && ln -sf /paperclip/.npm-global/node_modules/.bin/sentry-cli /paperclip/bin/sentry-cli` |

`sentry` and legacy `sentry-cli` use different issue-list syntax. Prefer `sentry issue list --query "is:unresolved" --limit 20`; use `sentry-cli issues list --org "$SENTRY_ORG" --project "$SENTRY_PROJECT" --status unresolved --max-rows 20` only as a legacy fallback. QA and CTO receive `SENTRY_ORG=ffmemes` and `SENTRY_PROJECT=ff-backend` from the manifest.

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

# Install gh, persistent Codex, and Sentry CLI aliases (runs as root)
docker exec -u root $CONT sh -c "apt-get update -qq && apt-get install -y -qq gh && npm install --prefix /paperclip/.npm-global @openai/codex@latest @sentry/cli sentry && ln -sf /paperclip/.npm-global/node_modules/.bin/codex /paperclip/bin/codex && ln -sf /paperclip/.npm-global/node_modules/.bin/sentry /paperclip/bin/sentry && ln -sf /paperclip/.npm-global/node_modules/.bin/sentry-cli /paperclip/bin/sentry-cli"

# Verify
docker exec $CONT sh -c "PATH=/paperclip/bin:\$PATH; gh --version; codex --version; (sentry --version || sentry-cli --version); claude --version; codex login status"
```

Tools on `/paperclip/bin/` (named volume) survive redeploys. Agents that need them must have `PATH=/paperclip/bin:...` in `.paperclip.yaml`.
System-wide installs via `apt-get` and `npm install -g` do NOT survive redeploys.

### Verify after redeploy

```bash
CONT=$(docker ps --format '{{.Names}}' | grep k4w804 | head -1)

# Auth survived?
docker exec $CONT sh -c "test -f /paperclip/.claude/.credentials.json && echo claude:OK"
docker exec $CONT sh -c "test -f /paperclip/.codex/auth.json && echo codex:OK"
docker exec $CONT sh -c "test -f /paperclip/.config/gh/hosts.yml && echo gh:OK"

# API + version?
curl -s https://org.ffmemes.com/api/health
docker exec $CONT npx paperclipai --version

# Telegram plugin loaded?
docker exec $CONT npx paperclipai plugin inspect paperclip-plugin-telegram

# Agents listed?
docker exec $CONT npx paperclipai agent list --company-id 96ee7b2e-6df2-43c8-bbe3-53e19297308a
```

### Updating Paperclip

Paperclip is deployed from the fork `ohld/paperclip` (not upstream `paperclipai/paperclip`).
Use pinned stable refs. Do not sync the fork to upstream `master`; upstream
master may be ahead of the latest stable release.

Current production deployment (verified 2026-05-06): Coolify app
`k4w804sco4s8kc88kwcw0ow4` tracks
`ohld/paperclip:ffmemes/v2026.428.0` at
`3494e84a2920f3e2bc5f627f916da29e224086dc`. State file
`/paperclip/.last-deployed-paperclip-sha` must match that verified deployed
commit.

```bash
# 1. Pick the approved stable release.
TARGET_VERSION=2026.428.0
TARGET_SHA=3494e84a2920f3e2bc5f627f916da29e224086dc
FORK_BRANCH=ffmemes/v${TARGET_VERSION}

# 2. Create/update a pinned fork branch at the stable upstream tag.
gh api -X PATCH "repos/ohld/paperclip/git/refs/heads/${FORK_BRANCH}" \
  -f sha="$TARGET_SHA" -F force=true || \
gh api -X POST repos/ohld/paperclip/git/refs \
  -f ref="refs/heads/${FORK_BRANCH}" -f sha="$TARGET_SHA"

# 3. Check migration prerequisites.
ssh root@t.ffmemes.com "docker exec \$(docker ps --format '{{.Names}}' | grep tkg4c0 | head -1) psql -U paperclip -d paperclip -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'"

# 4. Take a fresh db + volume backup before deploy.

# 5. Point Coolify app k4w804sco4s8kc88kwcw0ow4 at the pinned fork branch,
#    then force deploy. Hard gate: the finished deployment commit must equal
#    TARGET_SHA. Queueing a deploy is not success.

# 6. Run post-redeploy checklist above and verify migrations are up to date.
ssh root@t.ffmemes.com "CONT=\$(docker ps --format '{{.Names}}' | grep k4w804 | head -1) && docker exec \$CONT cat /paperclip/.claude/settings.json"
```

### Notable version changes

| Version | Key changes |
|---------|-------------|
| v2026.428.0 | Stable target for v416 upgrade: productivity review, stranded assignment recovery, routine variables UI, attachment size limits, issue tree pause/resume fixes |
| v2026.427.0 | Multi-user control plane, structured issue interactions, liveness/watchdog recovery, blocker-aware scheduling, issue subtree pause/cancel/restore, beta Environments |
| v2026.416.0 | MCP server, chat threads, execution policies, blocker deps, `none`/`github_hmac` webhook signing, security fix GHSA-68qg-g8mg-6pr7 |
| v2026.403.0 | Execution workspaces, routines engine, company skills, telemetry (disabled via env var) |
| v2026.325.0 | Company import/export, company skills library |
| v2026.318.0 | Plugin framework + SDK |
