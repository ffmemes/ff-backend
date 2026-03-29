# FFmemes Agent Company

Autonomous AI team for @ffmemesbot, managed by [Paperclip](https://paperclip.ing) at [org.ffmemes.com](https://org.ffmemes.com).

## Agents

| Agent | Title | Reports To | Trigger | Heartbeat | Skills |
|-------|-------|-----------|---------|-----------|--------|
| CEO | Chief Executive Officer | — | Weekly routine (Mon 09:00 UTC) | 24h (daily) | plan-ceo-review, office-hours, autoplan |
| Analyst | Data Analyst | CEO | Daily routine (06:00 UTC) | 6h | investigate, browse, retro |
| CTO | Chief Technology Officer | CEO | On-demand (CEO task) | **off** | plan-eng-review, plan-design-review, retro, cso, codex, investigate |
| Staff Engineer | Staff Engineer | CTO | PR webhook (GitHub Actions) | **off** | review, investigate |
| QA Engineer | QA Engineer | CTO | Webhook (Sentry/Coolify proxy) + 6h schedule | 6h | browse, qa, qa-only, benchmark, canary, design-review, design-consultation, setup-browser-cookies |
| Release Engineer | Release Engineer | CTO | On-demand (Staff Eng approval) | **off** | ship, land-and-deploy, document-release, setup-deploy |
| Comms Manager | Communications | CEO | Daily heartbeat | 24h (daily) | browse, frontend-design |

## Org Chart

```
                    CEO
                     |
         +-----------+-----------+
         |           |           |
      Analyst       CTO      Comms Manager
                     |
         +-----------+-----------+
         |           |           |
    Staff Eng   Release Eng   QA Engineer
```

## Handoff Flow

```
Bug detected (Sentry webhook or QA scan)
  -> QA classifies severity
    -> Critical/High: task for CTO
      -> CTO investigates + implements on branch
        -> CTO creates PR
          -> GitHub PR webhook triggers Staff Engineer
            -> Staff Engineer runs /review
              -> If issues: back to CTO
              -> If clean: approves PR + tasks Release Engineer
                -> Release Engineer runs /ship + /land-and-deploy (merge + deploy)
                  -> Coolify auto-deploys
                    -> Deploy webhook triggers QA post-deploy verification:
                      1. /canary (mandatory)
                      2. Sentry scan (last 10 min)
                      3. DB health check
                      4. E2E smoke: returning user + fresh user (--fresh)
                      5. Exploratory testing (5-10 min, improvised)
                      -> If issues: escalates to CTO
                      -> If clean: done
```

## Routines

| Routine | Agent | Schedule (UTC) | Trigger Type | What it does |
|---------|-------|----------------|-------------|--------------|
| Daily Analyst Report | Analyst | `19 6 * * *` | schedule + API | Query metrics, detect anomalies, write report for CEO |
| QA Log Scan | QA | `7 */6 * * *` | schedule + 2 webhooks + API | Sentry + Coolify logs + DB health + E2E smoke |
| Process Health Check | QA | `37 12 * * *` | schedule | Watchdog: verify all routines are running and succeeding |
| Weekly CEO Review | CEO | `11 9 * * 1` | schedule | Retro, experiments, priorities, backlog review |
| Weekly Analyst Summary | Analyst | `23 9 * * 1` | schedule | Weekly summary for CEO review |
| gstack Update Check | CEO | `17 3 * * *` | schedule | Update skills, review changelog |
| PR Review | Staff Engineer | on PR event | 2 webhooks + API | Review PRs via GitHub Actions trigger |

**Schedule design**: Prime-minute offsets ensure no two routines fire in the same minute. This avoids resource contention and makes debugging easier.

## Webhook Triggers

| Source | Target Agent | Event | Mechanism |
|--------|-------------|-------|-----------|
| GitHub | Staff Engineer | PR created/updated/synced | GitHub Actions → Paperclip bearer trigger |
| Sentry | QA Engineer | New issue created | App webhook proxy (`/webhooks/qa-alert`) → Paperclip |
| Coolify | QA Engineer | Deploy complete | App webhook proxy (`/webhooks/qa-alert?secret=...`) → Paperclip |
| Prefect | QA Engineer | Flow failure | `notify_qa_sync()` in `src/integrations/paperclip.py` |

### Webhook Proxy

Sentry and Coolify can't send custom `Authorization` headers. The ff-backend app proxies their webhooks to Paperclip at `POST /webhooks/qa-alert` (see `src/integrations/paperclip.py`).

Requires env vars: `PAPERCLIP_QA_TRIGGER_URL`, `PAPERCLIP_QA_TRIGGER_SECRET`, `SENTRY_CLIENT_SECRET`, `WEBHOOK_PROXY_SECRET`.

## Backup & Restore

```bash
# Take a snapshot of all agents, routines, skills
./agents/backup/backup.sh

# Restore from backup (after data loss)
./agents/backup/restore.sh [backup-file.json]
```

Backups are saved to `agents/backup/paperclip-state-*.json` (gitignored). The script keeps the last 10 snapshots. Run before any major config changes.

**What's backed up:** Agent configs (heartbeats, skills, adapters), routines (triggers, schedules), skills inventory.
**What's NOT backed up:** Secrets (re-add manually), issue history, execution logs.

## Structure

```
agents/
├── COMPANY.md              # Company definition (agentcompanies/v1)
├── .paperclip.yaml         # Runtime config (skills source, secrets per agent)
├── README.md               # This file
├── ceo/AGENTS.md           # CEO: strategy, experiments, delegation
├── analyst/AGENTS.md       # Analyst: metrics, reports, anomalies
├── cto/AGENTS.md           # CTO: architecture, implementation
├── staff-engineer/AGENTS.md  # Staff Engineer: PR review, investigation
├── qa/AGENTS.md            # QA: log monitoring, post-deploy verification
├── release-engineer/AGENTS.md  # Release Engineer: ship, merge, deploy
└── comms/AGENTS.md         # Comms: @ffmemes TG channel posts
```

## Skills

27+ gstack skills imported from [github.com/garrytan/gstack](https://github.com/garrytan/gstack).

### Update gstack skills

```bash
# All secrets come from env vars: $PAPERCLIP_URL, $PAPERCLIP_API_KEY
# Set these in ~/.zshrc (never commit to repo)
curl -X POST "$PAPERCLIP_URL/api/companies/$COMPANY_ID/skills/import" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "https://github.com/garrytan/gstack"}'
```

### Attach skills to an agent

Skills must be explicitly attached via `PATCH /api/agents/{id}` with `adapterConfig.paperclipSkillSync.desiredSkills`. The `skills:` list in AGENTS.md frontmatter is documentation only — Paperclip does NOT auto-discover from it.

```bash
curl -s -X PATCH "$PAPERCLIP_URL/api/agents/<agent-id>" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"adapterConfig": {"paperclipSkillSync": {"desiredSkills": ["garrytan/gstack/skill-name"]}}}'
```

### Deploy instructions to server

After editing AGENTS.md files locally, sync all agents to the live Paperclip container:

```bash
./agents/deploy.sh
```

This runs a backup first, then copies all AGENTS.md files to the container with size verification.
Changes take effect on the next routine/heartbeat wake (Paperclip re-reads instructions from disk on each agent wake).

Requires SSH key auth to the server (default: `root@t.ffmemes.com`).
Override with: `PAPERCLIP_SSH_HOST=user@host ./agents/deploy.sh`

## Agent IDs

| Agent | ID |
|-------|-----|
| CEO | e782143b-5ecf-484c-ad87-939592c79dbb |
| Analyst | 9c87d840-7041-49d8-8436-00b6dcb10971 |
| CTO | ebdad67a-e5fa-4b1f-ad40-86a64a43f45f |
| Staff Engineer | 1a323bb6-2b4d-46bf-9c33-7971fa1673d5 |
| QA Engineer | 4b02ab32-596b-4339-a397-eb88559a266f |
| Release Engineer | b5b71b81-eeed-4767-8970-8523786779d7 |
| Comms Manager | eac86c1e-8708-469c-af17-2925e356e4fb |
| Company (FFmemes) | 96ee7b2e-6df2-43c8-bbe3-53e19297308a |
