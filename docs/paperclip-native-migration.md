# Paperclip-native migration

Branch: `feat/paperclip-native-migration`. Prod is on **Paperclip v2026.416.0** (verified by deployed commit `4bdae1f42` → tag `v2026.416.0`). CLI is `paperclipai@2026.416.0`.

Goal: stop maintaining custom scaffolding for things Paperclip ships natively, so upstream fixes apply to us for free.

## 2026-05-04 docs/release learnings

Paperclip latest stable is **v2026.428.0** ([release notes](https://github.com/paperclipai/paperclip/releases/tag/v2026.428.0); mirror: [newreleases](https://newreleases.io/project/github/paperclipai/paperclip/release/v2026.428.0)). Canary builds exist, but production should stay on stable unless a specific blocker requires a canary and the rollback path is explicit.

Native Paperclip docs and shipped skills now cover most scaffolding we previously had to hand-roll: heartbeat scoped-wake fast paths, inbox-lite, `heartbeat-context`, structured interactions, blocker and child-issue wakes, documents, approvals, and workspace/runtime controls. Relevant upstream entry points:
- [Heartbeat protocol](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/heartbeat-protocol.md)
- [Task workflow](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/task-workflow.md)
- [Agents REST API](https://github.com/paperclipai/paperclip/blob/master/docs/api/agents.md)
- [MCP server tools](https://github.com/paperclipai/paperclip/blob/master/packages/mcp-server/README.md)
- [Paperclip skill source](https://github.com/paperclipai/paperclip/blob/master/skills/paperclip/SKILL.md)

Safe company import still rejects `replace` for existing companies, so the repo's native-API deploy/sync path remains justified. Current local touchpoints are [`agents/deploy.sh`](../agents/deploy.sh), [`agents/_sync_config.py`](../agents/_sync_config.py), [`agents/.paperclip.yaml`](../agents/.paperclip.yaml), and the still-custom PR trigger in [`.github/workflows/staff-engineer-trigger.yml`](../.github/workflows/staff-engineer-trigger.yml). Next simplification: use native `POST /api/agents/:id/skills/sync` for desired-skill assignment and reduce direct `adapterConfig` mutation to only fields that do not yet have a narrower native endpoint. See the short linked handoff in [`docs/agents/paperclip-simplification-2026-05-04.md`](agents/paperclip-simplification-2026-05-04.md).

## Pre-flight backups (taken 2026-04-24 09:27 UTC)

On `t.ffmemes.com:/root/paperclip-backups/pre-export-2026-04-24/`:
- `preexport-20260424-092754.sql.gz` — 16 MB DB dump via `paperclipai db:backup`
- `paperclip-config-2026-04-24.tgz` — 2.4 GB tar of `.paperclip` + `.claude` + `.claude.json` from the named volume

Restore (only if needed):
```bash
gunzip -c preexport-20260424-092754.sql.gz | docker exec -i <paperclip-container> psql "$DATABASE_URL"
```

## What Paperclip-native looks like (v2026.416)

CLI commands we now rely on:
- `paperclipai db:backup` — native DB dump.
- `paperclipai company export <id> --include company,agents,skills` — git-syncable export of the entire company definition.
- `paperclipai dashboard get --json` — replaces custom health-summary scripts.
- `paperclipai heartbeat run --agent-id <id>` — wake an agent on demand.

API endpoints we now use directly (no SSH, no `docker cp`):
- `GET  /api/companies/<id>/agents` — slug → agent ID resolution.
- `GET  /api/agents/<id>/instructions-bundle?companyId=<id>` — list current instruction files.
- `PUT  /api/agents/<id>/instructions-bundle/file?companyId=<id>` — body `{path, content}`. Records audit + config revision (rollbackable).
- `PATCH /api/agents/<id>` — adapter config, `desiredSkills`, runtime, permissions (not yet wired in deploy script — see "Future work").

## Why `company import` is **not** the deploy path

`paperclipai company import --target existing --collision replace` is **rejected by the server** with `403: Safe import route does not allow replace collision strategy`. The CLI accepts the flag but the v416 API hardens the existing-company import endpoint against destructive overwrites. `--collision skip` works but does not update existing agents.

So `company import` is for:
- bootstrapping a new company (`--target new`)
- additive sync of new agents into an existing company (`--target existing --collision skip`)

For **updating existing agent prompts**, use the instructions-bundle PUT endpoint (per-file, audited, rollbackable). That is what `agents/deploy.sh` now does.

## Phase 1 — Repo as source of truth (this PR)

What changed in `agents/`:
- **Slug renames**: `comms/` → `comms-manager/`, `qa/` → `qa-engineer/` to match prod `urlKey`s. Done via `git mv` to preserve history.
- **CEO additions**: `agents/ceo/{SOUL,TOOLS,HEARTBEAT}.md` pulled from prod (Paperclip pattern; CEO-only for now).
- **Top-level files**: `agents/COMPANY.md`, `agents/README.md`, `agents/images/{org-chart.png,company-logo.jpg}` pulled from prod.
- **Manifest** `agents/.paperclip.yaml` rewritten in `paperclip/v1` schema with full prod structure (heartbeat, model, maxTurnsPerRun, env-default declarations, sidebar order, brand color) and the union of repo + prod env var declarations. The inlined `capabilities` text from prod's `comms-manager` was dropped — `AGENTS.md` is the single source.
- **Removed** `agents/backup/` (legacy local snapshots; server-side backups now exist).
- **Replaced** `agents/deploy.sh`: now 70 LOC of curl + jq against the native API. No SSH. No docker cp.

What did **not** change in this PR:
- `agents/<slug>/AGENTS.md` text content. Repo content is preserved as-is per CEO direction ("repo is final").

### Drift status when this PR merges

Per `paperclipai company export` taken 2026-04-24, repo vs prod AGENTS.md diff:

| Agent | Δ lines (repo − prod) | First deploy effect |
|---|---:|---|
| analyst | +9 | Repo overwrites prod (minor) |
| ceo | −13 | **Prod text replaced** by older repo text |
| comms-manager | +62 | Repo overwrites prod (intended — anomaly-driven content rules etc.) |
| cto | −14 | **Prod text replaced** by older repo text |
| qa-engineer | +6 | Repo overwrites prod (minor) |
| release-engineer | −12 | **Prod text replaced** by older repo text |
| staff-engineer | −11 | **Prod text replaced** by older repo text |

**Reviewer's call before merging**: for each "Prod text replaced" row, decide whether to (a) ship as-is and accept the lost prod edits, or (b) `curl -H ... GET .../instructions-bundle/file?path=AGENTS.md` to pull prod's current text into repo first. Pre-merge backups exist in case of regret.

## Phase 2 — Auto-deploy on push to `production` (this PR)

`.github/workflows/paperclip-deploy-agents.yml` triggers on:
- `push` to `production` touching `agents/**` (or the workflow itself), or
- manual `workflow_dispatch`.

Steps:
1. `./agents/deploy.sh --dry-run` — fails build on slug-resolution miss.
2. `./agents/deploy.sh` — applies via API.

Required GitHub repo secrets (set before merging this PR):
- `PAPERCLIP_URL` = `https://org.ffmemes.com`
- `PAPERCLIP_API_KEY` = a board-operator scoped token (use a dedicated CI key, not your personal one)

Concurrency group `paperclip-deploy-agents` prevents overlapping runs; `cancel-in-progress: false` ensures in-flight syncs complete.

## Phase 3 — Pending (separate PRs)

**3a. Adapter config sync from `.paperclip.yaml`** (next iteration of `agents/deploy.sh`).
Read agent block from manifest, PATCH `/api/agents/<id>` with `adapterConfig`, `runtimeConfig`, `permissions`, `desiredSkills` (parsed from AGENTS.md frontmatter). Currently we only sync the prompt text.

**3b. Retire the webhook proxy.** ✅ Done 2026-04-29. QA trigger `30901464-...` flipped to `signingMode: none`, Sentry Internal Integration `paperclip-qa-alert-b86aa3` now POSTs directly to `https://org.ffmemes.com/api/routine-triggers/public/18a2f9e439c396e9b21a02fa/fire`. Deleted: `src/integrations/paperclip.py`, `notify_qa_sync` callsite in `src/flows/hooks.py`, env vars `WEBHOOK_PROXY_SECRET` / `SENTRY_CLIENT_SECRET` / `PAPERCLIP_QA_TRIGGER_URL` / `PAPERCLIP_QA_TRIGGER_SECRET`. Coolify webhook path was unused (no hits in 24h prior to removal). Prefect failures now surface via the QA Log Scan 3h cron instead of an instant push — accepted tradeoff for less code. Trigger publicId leakage = at most noisy QA scans (no user input or commands accepted).

**3c. CLI-native agent skills.** In each AGENTS.md, replace raw `curl https://org.ffmemes.com/api/...` with `paperclipai issue list --json`, `paperclipai approval create`, `paperclipai dashboard get`, `paperclipai heartbeat run --agent-id`. Reduces per-wake context.

**3d. gstack skill update routine.** Codex flagged: Paperclip already shipped "pinned GitHub skills with update checks" in v2026.325.0. Build a daily Paperclip routine that:
- compares pinned `skills.source` ref against `garrytan/gstack` HEAD,
- summarizes the changelog/commit delta in plain English,
- creates **one** Paperclip issue ("review gstack updates: <slug list>") for human/CEO triage,
- bumps the pin only after explicit approval (never auto-bump — supply-chain roulette).

Prefer Paperclip's native skill-update mechanism over a custom-rolled routine if it exists in the UI; this routine should hook into it, not replace it.

## What stays custom

- `.github/workflows/staff-engineer-trigger.yml` — no native Paperclip↔GitHub PR integration yet; HTTP POST to a routine trigger is the right shape.
- `agents/<slug>/AGENTS.md` content — our IP, not Paperclip's job.
- Telegram plugin — already native (Paperclip plugin system).

## Risks acknowledged

- **First deploy overwrites 4 prod-ahead agents** (CEO/CTO/release-eng/staff-eng) with older repo text. Reviewer must decide pre-merge.
- **`--collision replace` was rejected** by the v416 safe-import server — we work around with per-file PUT, but if Paperclip changes the instructions-bundle endpoint behavior in a future version, we re-evaluate.
- **No drift monitoring yet.** Auto-deploy reduces drift; UI edits between deploys still possible. Codex recommended a nightly `company export` artifact job; deferred per CEO call. Revisit if drift bites.
- **CI auth uses a single API key.** No first-class service-account exists in Paperclip. The key must be scoped to this company and rotated if leaked.
