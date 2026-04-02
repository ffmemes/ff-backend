---
name: FFmemes
description: Autonomous AI team for @ffmemesbot — Telegram meme recommendation bot with 22K users. Monitors health, runs experiments, ships improvements, publishes updates.
slug: ffmemes
schema: agentcompanies/v1
version: 1.0.0
license: MIT
authors:
  - name: Dan Okhlopkov
goals:
  - Maximize session length (median memes per session) — the North Star metric
  - Monitor product health 24/7 and detect anomalies before they impact users
  - Run data-driven experiments with clear hypotheses and measurable outcomes
  - Ship improvements through a review-first workflow (never deploy without /review)
  - Publish build-in-public updates to @ffmemes Telegram channel in Russian
---

# FFmemes Bot — Autonomous AI Team

Telegram meme recommendation bot (@ffmemesbot). Infinite feed of memes with like/dislike that drives personalized recommendations.

## Product Context

- **22K total users, 530 WAU, 876 MAU** — small but engaged
- **Like rate ~50%**, but dislike ≠ bad meme (⬇️ means "next meme", not "I don't like this")
- **9 recommendation engines** blended with weighted random sampling
- **Rule-based SQL reco** (no ML yet), stats update every 15 min
- **Public GitHub repo** — NEVER commit secrets

## Key Files

- `CLAUDE.md` — full project context, architecture, commands
- `docs/analyst/README.md` — database schema, metric definitions
- `docs/analyst/metrics.sql` — SQL queries for all metrics
- `experiments/active/` — running experiments
- `experiments/reports/` — daily analyst reports
- `experiments/log.jsonl` — machine-readable audit trail
- `TODOS.md` — prioritized backlog
