# April 1-14: Autonomous AI Development Experiment

## Overview
While on vacation (Apr 1-14, 2026), AI agents autonomously improve the meme bot.
"Build in public" — TG channel @ffmemes updates, public dashboard.

## Stack
- **Paperclip** — orchestrator (assigns work, tracks progress, dashboard at localhost:3100)
- **gstack** — 21 engineering skills (globally installed in Claude Code)
- **autoresearch** — autonomous experiment loop (Phase 3, needs offline eval harness)

## Agent Pipeline

```
ANALYST (every 6h)                    CEO (daily)
  │ Queries prod DB (read-only)         │ Reviews Analyst reports
  │ Checks Sentry errors                │ Reviews TODOS.md + active experiments
  │ Reviews git log                     │ Decides: end/start experiments
  │ Reads @ffmemes community            │ Creates tasks for Engineer/Comms
  │ Detects anomalies → digs deeper     │
  │ Writes daily report                 │
  │                                     │
  ▼                                     ▼
  experiments/reports/YYYY-MM-DD.md     Paperclip tasks
  experiments/log.jsonl                    │
                                    ┌──────┴──────┐
                                    ▼             ▼
                              ENGINEER        COMMS MANAGER
                              (Phase 2)       (Phase 2)
                              Codes + ships   Posts to @ffmemes
                              Uses /review,   in Russian
                              /ship, /qa
```

## Phases

### Phase 1: PoC (NOW — validate the loop)
- 2 agents: Analyst + CEO, running locally on Mac
- Analyst queries prod DB (read-only user, 30s statement_timeout)
- CEO reviews reports, manages experiment lifecycle
- Structured experiment log (JSONL)
- Pre-commit secrets scanner (public repo protection)

### Phase 2: Full Pipeline (after PoC validates)
- Add Engineer + QA + Comms Manager agents
- Engineer ships code to prod via /review + /ship
- Comms Manager writes "build in public" posts for @ffmemes
- Community feedback loop (read TG channel replies)

### Phase 3: Autonomous Research (future)
- autoresearch for ranking optimization
- ML-based recommendations (linear models, boosting)
- Server deployment (Coolify) for 24/7 operation
- User segmentation for faster experiment signal

## Key Constraint
No Anthropic API key available. Using Claude Code CLI subscription auth only.
Paperclip's `claude_local` adapter spawns CLI as subprocess.

## Safety Rails
- Read-only DB user for Analyst (can't modify prod data)
- statement_timeout = 30s (prevents runaway queries)
- Pre-commit secrets scanner (blocks postgresql://, API keys, bot tokens)
- Experiment log for full audit trail
- No automated rollback — CEO decides based on data

## File Structure
```
docs/
├── analyst/
│   ├── README.md           # Analyst agent reference (schema, metrics, context)
│   └── metrics.sql         # SQL queries by section (health, north star, engines, etc.)
├── april-autonomous-ai/
│   ├── README.md           # This file (master plan)
│   ├── gstack-research.md
│   ├── paperclip-research.md
│   └── autoresearch-research.md
experiments/
├── active/                 # Running experiments
├── completed/              # Finished experiments (historical)
├── reports/                # Analyst daily reports (gitignored)
├── log.jsonl               # JSONL audit trail (gitignored)
└── README.md               # Experiment lifecycle docs
scripts/
└── pre-commit-secrets-check.sh  # Installable pre-commit hook
```

## North Star Metrics
- **Primary**: Session length (median memes per session)
- **Growth**: Share clicks (deep link log), new users/day
- **Retention**: D1, D7 cohort retention
- **Engagement**: DAU/WAU/MAU, like rate, reactions/day
- **Quality**: Per-engine like rate, cold start like rate

## Setup Checklist
- [x] Research Paperclip, gstack, autoresearch
- [x] Plan reviewed (CEO review + Eng review passed)
- [x] Create docs/analyst/ with SQL snippets + reference
- [x] Create experiments/ directory structure
- [x] Install pre-commit secrets scanner
- [x] Add ANALYST_DATABASE_URL to .env.example
- [ ] Create read-only PostgreSQL user on prod server
- [ ] Add ANALYST_DATABASE_URL to local .env
- [ ] Configure Analyst agent in Paperclip dashboard
- [ ] Configure CEO agent in Paperclip dashboard
- [ ] Run first Analyst heartbeat manually → verify output
- [ ] Run first CEO heartbeat manually → verify task creation
