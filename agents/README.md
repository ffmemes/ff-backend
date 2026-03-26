# FFmemes Agent Company

Autonomous AI team for @ffmemesbot, managed by [Paperclip](https://paperclip.ing) at [org.ffmemes.com](https://org.ffmemes.com).

## Agents

| Agent | Title | Reports To | Heartbeat | Skills |
|-------|-------|-----------|-----------|--------|
| CEO | Chief Executive Officer | — | Daily | review, ship, investigate, office-hours, plan-ceo-review, plan-eng-review, retro, qa, browse |
| Analyst | Data Analyst | CEO | 6h | investigate, browse, retro |

## Structure

```
agents/
├── COMPANY.md              # Company definition (agentcompanies/v1)
├── .paperclip.yaml         # Runtime config (secrets, adapters)
├── README.md               # This file
├── ceo/AGENTS.md           # CEO instructions + frontmatter
├── analyst/AGENTS.md       # Analyst instructions + frontmatter
└── qa/AGENTS.md            # (future) QA agent
```

## Skills

28 gstack skills imported from [github.com/garrytan/gstack](https://github.com/garrytan/gstack).

### Update gstack skills

```bash
# Update all gstack skills to latest
curl -X POST "https://org.ffmemes.com/api/companies/$COMPANY_ID/skills/import" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source": "https://github.com/garrytan/gstack"}'
```

### Sync instructions to server

After editing AGENTS.md files locally:

```bash
# Upload to Paperclip managed paths
scp agents/ceo/AGENTS.md root@65.108.127.32:/tmp/ceo-instructions.md
ssh root@65.108.127.32 "docker cp /tmp/ceo-instructions.md <container>:/paperclip/instances/default/companies/<company-id>/agents/<agent-id>/instructions/AGENTS.md"
```

## Adding new agents

1. Create `agents/<slug>/AGENTS.md` with frontmatter (name, title, reportsTo, skills)
2. Create agent via Paperclip API or dashboard
3. Upload instructions to managed path
4. Sync skills: `POST /api/agents/:id/skills/sync`
