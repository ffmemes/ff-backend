# FFmemes Agent Company

Autonomous AI team for @ffmemesbot, managed by [Paperclip](https://paperclip.ing) at [org.ffmemes.com](https://org.ffmemes.com).

## Agents

| Agent | Title | Reports To | Trigger | Skills |
|-------|-------|-----------|---------|--------|
| CEO | Chief Executive Officer | — | Daily heartbeat | plan-ceo-review, office-hours, autoplan |
| Analyst | Data Analyst | CEO | Every 6h (routine) | investigate, browse, retro |
| CTO | Chief Technology Officer | CEO | On-demand (CEO task) | plan-eng-review, plan-design-review, retro, cso, codex |
| Staff Engineer | Staff Engineer | CTO | PR webhook (auto) | review, investigate |
| QA Engineer | QA Engineer | CTO | Sentry webhook + 30min fallback | browse, qa, qa-only, benchmark, canary, design-review, design-consultation, setup-browser-cookies |
| Release Engineer | Release Engineer | CTO | On-demand (Staff Eng approval) | ship, land-and-deploy, document-release, setup-deploy |
| Comms Manager | Communications | CEO | On-demand (CEO task) | browse, frontend-design |

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
              -> If clean: hands off to Release Engineer
                -> Release Engineer runs /ship + /land-and-deploy
                  -> Coolify auto-deploys
                    -> Deploy triggers QA /canary
                      -> If issues: escalates to CTO
                      -> If clean: done
```

## Routines

| Routine | Agent | Schedule (UTC) | What it does |
|---------|-------|----------------|-------------|
| Daily Analyst Report | Analyst | `0 6 * * *` | Query metrics, detect anomalies, write report for CEO |
| QA Health Check | QA | `*/30 * * * *` | Lightweight scan: Sentry + Prefect + DB health (fallback for webhooks) |
| Weekly CEO Review | CEO | `0 9 * * 1` | Retro, experiments, priorities, backlog review |
| gstack Update Check | CEO | `0 3 * * *` | Update skills, review changelog |

## Webhook Triggers

| Source | Target Agent | Event |
|--------|-------------|-------|
| Sentry | QA Engineer | New issue created -> classify + escalate |
| GitHub | Staff Engineer | PR created/updated -> /review |
| Coolify | QA Engineer | Deploy complete -> /canary |

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

### Sync instructions to server

After editing AGENTS.md files locally:

```bash
CONTAINER=$(ssh root@t.ffmemes.com "docker ps --format '{{.Names}}' | grep k4w804")
scp agents/<name>/AGENTS.md root@t.ffmemes.com:/tmp/agent-instructions.md
ssh root@t.ffmemes.com "docker cp /tmp/agent-instructions.md $CONTAINER:/paperclip/instances/default/companies/96ee7b2e-6df2-43c8-bbe3-53e19297308a/agents/<agent-id>/instructions/AGENTS.md"
```

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
