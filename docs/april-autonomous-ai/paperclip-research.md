# Paperclip Research

Open-source, self-hosted Node.js + React. MIT license. ~30K GitHub stars.
Repo: github.com/paperclipai/paperclip
Site: paperclip.ing

## What It Is
Orchestration control plane for AI agent teams. Not a chatbot, not a framework.
Manages agents that do actual work. CLI + web dashboard.

## Setup
```bash
npx paperclipai onboard --yes
# → Bootstraps embedded PostgreSQL (PGlite)
# → Starts server at http://localhost:3100
# → Dashboard opens in browser
```

Data: `~/.paperclip/instances/default/db`

## Key Concepts

### Company
Top-level org unit with mission, org chart, agents, projects, budget controls.

### Agents
Run in **heartbeats** — short discrete execution windows, not persistent processes.

Adapter types:
- `claude_local` — spawns `claude` CLI as subprocess ← THIS IS WHAT WE NEED
- `codex_local`, `cursor`, `gemini_local`, etc.
- `http` — calls external endpoint
- `process` — any shell command

The `claude_local` adapter:
- Spawns Claude Code CLI with env vars (PAPERCLIP_API_KEY, AGENT_ID, RUN_ID)
- Needs `dangerouslySkipPermissions` for unattended execution
- Session IDs persist per agent-task pair (resumes context, not from scratch)

### Task Flow
- Tasks created as issues with assigneeAgentId
- Agents only work on assigned tasks
- Atomic checkout lock (409 if someone else owns it)
- Status: todo → in_progress → done/blocked/in_review
- **Agents CAN create tasks for each other** (delegation up/down org chart)

### Triggers
1. Timer (`intervalSec`) — scheduled heartbeats (e.g. every 30 min)
2. Assignment — triggered when task assigned
3. On-demand — manual trigger via UI
4. Automation — system-triggered

### Budget
Per-agent monthly caps. 80% soft warning. 100% auto-pause.

## Deployment Options

### Local Mac (simpler)
Just `npx paperclipai run`. Mac must stay on.

### Coolify/Docker (production)
Docker Compose with PostgreSQL + Node.js server.
Community repos: richardadonnell/paperclip-coolify

**CRITICAL**: `claude_local` adapter needs Claude Code CLI installed on the server.
We don't have Anthropic API key — using CLI subscription auth only.
Need to figure out if CLI auth works headlessly on server.

### Key Env Vars for Production
- DATABASE_URL — PostgreSQL connection
- BETTER_AUTH_SECRET — required auth secret
- PAPERCLIP_PUBLIC_URL — domain
- PAPERCLIP_HOME — persistent data dir
- PAPERCLIP_DEPLOYMENT_MODE — authenticated
- AUTH_DISABLE_SIGNUP — after initial setup

## Dashboard
React web UI at port 3100:
- Org chart, task boards, agent config
- Real-time run log streaming (WebSocket)
- Approval queue for governance
- Budget tracking per agent
- PWA support

## Integration with gstack
Implicit: install gstack in project dir → Paperclip's Claude agent gets those skills.
Paperclip also injects its own instructions (AGENTS.md, SOUL.md, HEARTBEAT.md, TOOLS.md).
