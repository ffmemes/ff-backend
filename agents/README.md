# FFmemes Agent Company

Autonomous AI team for @ffmemesbot, managed by [Paperclip](https://paperclip.ing) at [org.ffmemes.com](https://org.ffmemes.com).

## Agents

| Agent | Title | Reports To | Heartbeat | Skills |
|-------|-------|-----------|-----------|--------|
| CEO | Chief Executive Officer | — | Daily | plan-ceo-review, office-hours, autoplan |
| Analyst | Data Analyst | CEO | 6h | investigate, browse, retro |
| CTO | Chief Technology Officer | CEO | On-demand | plan-eng-review, plan-design-review, retro, cso, codex, review, investigate |
| QA Engineer | QA Engineer | CEO | 6h | investigate, browse, qa, qa-only |
| Release Engineer | Release Engineer | CTO | On-demand | ship, land-and-deploy, document-release |
| Comms Manager | Communications | CEO | On-demand | browse, frontend-design |

## Routines

| Routine | Agent | Schedule (UTC) |
|---------|-------|----------------|
| Daily Analyst Report | Analyst | `0 6 * * *` |
| QA Log Scan | QA | `0 */6 * * *` |
| Weekly CEO Review | CEO | `0 9 * * 1` |
| gstack Update Check | CEO | `0 3 * * *` |

## Structure

```
agents/
├── COMPANY.md              # Company definition (agentcompanies/v1)
├── .paperclip.yaml         # Runtime config (secrets, adapters)
├── README.md               # This file
├── ceo/AGENTS.md           # CEO instructions
├── analyst/AGENTS.md       # Analyst instructions
├── cto/AGENTS.md           # CTO instructions
├── qa/AGENTS.md            # QA Engineer instructions
├── release-engineer/AGENTS.md  # Release Engineer instructions
└── comms/AGENTS.md         # Comms Manager instructions
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

### Sync instructions to server

After editing AGENTS.md files locally:

```bash
# Upload to Paperclip managed paths
CONTAINER=$(ssh root@t.ffmemes.com "docker ps --format '{{.Names}}' | grep k4w804")
scp agents/<name>/AGENTS.md root@t.ffmemes.com:/tmp/agent-instructions.md
ssh root@t.ffmemes.com "docker cp /tmp/agent-instructions.md $CONTAINER:/paperclip/instances/default/companies/<company-id>/agents/<agent-id>/instructions/AGENTS.md"
```

Company ID, agent IDs, and other operational details: see `docs/paperclip-ops-runbook.md`.

## Adding new agents

1. Create `agents/<slug>/AGENTS.md` with frontmatter (name, title, reportsTo, skills)
2. Create agent via Paperclip API: `POST $PAPERCLIP_URL/api/companies/$COMPANY_ID/agents`
3. Upload instructions to managed path
4. Agent picks up instructions on next heartbeat/wake
