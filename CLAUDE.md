# CLAUDE.md

Legacy guidance for Claude Code. **Codex is the primary coding-agent surface**
for this repo. Prefer:

| Need | Source of truth |
|------|-----------------|
| Repo rules for agents | [`AGENTS.md`](AGENTS.md) |
| Domain vocabulary (RU) | [`CONTEXT.md`](CONTEXT.md) |
| Task routing / agent docs | [`docs/agents/README.md`](docs/agents/README.md) |
| Product + data overview | [`SPEC.md`](SPEC.md) |
| Virality / growth thesis | [`docs/growth/virality-loop.md`](docs/growth/virality-loop.md) |
| Public-repo redaction | [`docs/public-repo-rule.md`](docs/public-repo-rule.md) |

Do **not** duplicate architecture here — it drifts. The sections below are only
what Claude-era workflows still rely on that is not already in `AGENTS.md`.

## What this is

Telegram meme recommendation bot (`@ffmemesbot`). Infinite feed of memes with
like/dislike that drives personalized recommendations. North star: **session
length** (memes per session) and **organic growth via shares** (see growth doc).

## Commands

```bash
# First-time setup
cp .env.example .env
docker network create ffmemes_network
docker-compose up -d --build

# Development
just up
just build
just logs app
just exec bash
docker compose exec app ipython

# Database
just migrate
just mm "migration name"
just downgrade -1

# Code quality — MUST run before every commit
ruff check --fix src/ tests/
ruff format src/ tests/
# or: just lint

# Tests
docker compose exec app pytest
# Host-mode: set -a; source .env.test; set +a; python3 -m pytest tests/... -x
```

## Architecture (short)

- **Bot**: python-telegram-bot, webhook in prod / `start-polling.py` locally
- **API**: FastAPI + Uvicorn
- **DB**: PostgreSQL 14, SQLAlchemy `Table` objects in `src/database.py` (not ORM models)
- **Cache/Queue**: Redis recommendation queues
- **Jobs**: Prefect via `scripts/serve_flows.py`
- **Describe Memes**: free OpenRouter vision only — see `AGENTS.md` / `specs/describe-memes.md`
- **Telegram repos**: `src/tgbot/repo/*` (barrel: `src/tgbot/service.py`)
- **Feed plan**: `src/feed_turn/planner.py` is **wired** into `RecommendationBatchPipeline`

### Docker services

| Service | Purpose |
|---------|---------|
| `app` | FastAPI webhook server |
| `app_prefect` | Prefect scheduled job worker |
| `app_tgbot_polling` | Polling bot (local) |
| `app_db` | PostgreSQL |
| `app_redis` | Redis |

## Migrations

After rebasing a branch with a new migration onto `production`, verify a single head:

```bash
docker compose exec app alembic heads   # MUST return exactly one revision
```

## Credential safety

Always reference secrets via `$ENV_VAR_NAME` in shell. Never expand real secret
values inline. See `docs/public-repo-rule.md`.

Production SSH, Coolify app IDs, and private hostnames are **not** documented
in this public repo. Use your private ops notes / Coolify dashboard.

## Broadcasts

Read `docs/broadcasts.md` before any broadcast. Use `send_broadcast()` with a
unique `broadcast_id`. Language detection uses `user_language`, not
`user_tg.language_code`.

## Source moderation CLI

`scripts/admin/advance_source.py` — see `docs/source-moderation-cli.md`.

## Known issues (current)

- Queue refill threshold is **≤ 8** (docs that still say 2 are stale)
- Source diversity flag is dormant without `meme_source_id` on engine rows
- No strong exploration mechanism (engines mostly exploit)
- VK ETL lacks some TG quality guards (`parsing_enabled`, auto-snooze) — intentional debt

## Skill routing

When a request matches a gstack/skill workflow (ship, review, investigate,
office-hours, etc.), invoke that skill first rather than ad-hoc answers.
