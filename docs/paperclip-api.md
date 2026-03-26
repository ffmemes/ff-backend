# Paperclip API Reference

Dashboard: https://org.ffmemes.com
Company: FFmemes (`e3abd0fa-72b3-421b-84a5-f5d4e1e130ad`)

## Authentication

```bash
AUTH="Authorization: Bearer pcp_88894a65173afd16c2c37cc136780377e4b8dc44d727d28fa176ea6ec24bb6a3"
BASE="https://org.ffmemes.com/api"
COMPANY="e3abd0fa-72b3-421b-84a5-f5d4e1e130ad"
```

## Common Operations

### List all tasks
```bash
curl -s -H "$AUTH" "$BASE/companies/$COMPANY/issues?per_page=50"
```

### List open/stuck tasks
```bash
curl -s -H "$AUTH" "$BASE/companies/$COMPANY/issues?status=in_progress,in_review,todo,blocked&per_page=50"
```

### Update task status (todo, in_progress, in_review, done, blocked)
```bash
curl -s -X PATCH -H "$AUTH" -H "Content-Type: application/json" \
  "$BASE/issues/{ISSUE_ID}" -d '{"status": "done"}'
```

### Create a new task
```bash
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  "$BASE/companies/$COMPANY/issues" \
  -d '{"title": "...", "description": "...", "assigneeAgentId": "AGENT_ID", "priority": "high"}'
```

### List agents
```bash
curl -s -H "$AUTH" "$BASE/companies/$COMPANY/agents"
```

### List routines
```bash
curl -s -H "$AUTH" "$BASE/companies/$COMPANY/routines"
```

### Trigger a routine manually
```bash
curl -s -X POST -H "$AUTH" "$BASE/routines/{ROUTINE_ID}/trigger"
```

## Agent IDs

| Agent | ID | Role |
|-------|----|------|
| CEO | `6a4db8cd-94e5-4f87-ab16-f2fe85d5f49c` | Strategy, priorities |
| Analyst | `fec29691-2ae0-40e4-810f-1dd4e93f2fb4` | Data, metrics, reports |
| CTO | `ede681e2-4ba1-41ab-bc82-c01347a60822` | Implementation |
| QA | `1d16f4ad-c4fc-4f50-a032-a8c731785c81` | Testing, log scanning |
| Release Engineer | `f0ca6353-56d6-45f2-8ae0-f86876bd4176` | PR review, deploy |
| Comms | `c6a14543-8e31-48f7-8af3-62480b618ced` | TG channel posts |

## Routine IDs

| Routine | ID |
|---------|----|
| QA Log Scan | `4d31a33b-29c8-4a2c-8731-1b680cfa0c7a` |
| Review & merge PR | `0e9ccc28-e53c-40b0-9fb0-a3e0814d2682` |
| Weekly Retro & Strategy | `7f2a4e95-68e5-432e-a8ac-e54d0cc9bddf` |
| Daily Analyst Report | `3a4c8b32-f9c2-4283-b822-76ec75e115d7` |
| Update gstack skills | `bb29fb31-4352-426e-9cb4-5e3035ceb831` |

## GitHub Webhook

Webhook ID `602814436` on `ffmemes/ff-backend` fires on `pull_request` events.
Hits: `https://org.ffmemes.com/api/routine-triggers/public/7026017f83dbe75696d2fd76/fire`
Triggers: "Review and merge GitHub PR" routine → Release Engineer gets task.
