# Paperclip-native migration

Prod is on **Paperclip v2026.512.0** as of 2026-05-12. Verified deployment:
Coolify deployment `q12xc4c1q6m4smzk1zfkog02`, fork branch
`ohld/paperclip:ffmemes/v2026.512.0`, commit
`c445e5925628d11bf59d52604b8aa63a6e9aa800`, health check green. Codex
OAuth auth is present at `/paperclip/.codex/auth.json`, and `OPENAI_API_KEY`
is absent from the Paperclip host env and all managed Codex agent env bindings.

Goal: stop maintaining custom scaffolding for things Paperclip ships natively, so upstream fixes apply to us for free.

## 2026-05-12 adopted: v2026.512.0

Upstream `v2026.512.0` adds several native surfaces we adopted after fresh DB
and volume backups, Coolify deploy verification, and live agent config sync.
The important constraint is Codex auth: upstream can write Codex auth from
`OPENAI_API_KEY`, but our production path must stay subscription/OAuth-only.

Adopted:

- **Codex subscription-only agents.** Replace remaining `claude_local` agents
  with `codex_local`, but keep Codex authenticated through the persistent
  `/paperclip/.codex/auth.json` OAuth volume. Do not bind `OPENAI_API_KEY` to
  `codex_local` agents and do not set it in the Paperclip host env. Codex CLI
  0.122+ treats `OPENAI_API_KEY` as API-key billing, not subscription billing.
- **Planning mode.** Strategic, experiment, architecture, and proposal issues
  should use Paperclip's native planning work mode instead of pretending every
  issue is execution work. Execution tickets stay in standard mode.
- **Full company search.** Before creating recurrent issues, agents should use
  native company search / issue search to find existing bracket slugs across
  open work and historical context. Keep bracket slugs, but let Paperclip search
  do more of the dedupe work.
- **Routine revision history.** Continue syncing routine descriptions from this
  repo, but include `baseRevisionId` when the API exposes a latest revision so
  Paperclip's built-in revision history and restore flow remain useful.
- **Issue monitors and retry-now.** Time-gated follow-ups, post-deploy waits,
  and delayed verification should use native issue monitors / retry-now instead
  of comment-only due timestamps and custom wake prose.
- **System notices and monitor liveness.** Prefer the dashboard/native runtime
  surfaces for generic "agent alive, monitor stale, retry queued" checks. Keep
  local audits focused on FFmemes-specific outcome contracts.

Do not adopt yet:

- **AWS Secrets Manager provider vaults.** We are not using AWS as the source of
  truth. Keep Paperclip company secrets (`secret_ref`) for agent-level secrets.
  Coolify envs are acceptable for Paperclip service-level configuration, but not
  as a way to expose `OPENAI_API_KEY` to Codex.
- **OPENAI_API_KEY-backed Codex auth.** This is useful upstream for users who
  want API billing. It is explicitly not our desired path.

## Previous 2026-05-06 stable deployment

Previous verified production was **v2026.428.0** ([release notes](https://github.com/paperclipai/paperclip/releases/tag/v2026.428.0); mirror: [newreleases](https://newreleases.io/project/github/paperclipai/paperclip/release/v2026.428.0)). Production now runs **v2026.512.0** from a pinned stable ref. Canary builds may exist, but production should stay on a pinned stable release unless a specific blocker requires a canary and the rollback path is explicit.

The previous deployed target was upstream tag `v2026.428.0` at commit
`3494e84a2920f3e2bc5f627f916da29e224086dc`. Coolify deploys
`ohld/paperclip`, so create/use a pinned fork branch such as
`ffmemes/v2026.428.0` pointing to that exact commit. Do **not** sync
`ohld/paperclip:master` to upstream `master`; upstream master can be newer than
stable. The old fork-only Dockerfile checksum workaround is no longer needed at
`v2026.428.0`.

Native Paperclip docs and shipped skills now cover most scaffolding we previously had to hand-roll: heartbeat scoped-wake fast paths, inbox-lite, `heartbeat-context`, structured interactions, blocker and child-issue wakes, documents, approvals, and workspace/runtime controls. Relevant upstream entry points:
- [Heartbeat protocol](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/heartbeat-protocol.md)
- [Task workflow](https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/task-workflow.md)
- [Agents REST API](https://github.com/paperclipai/paperclip/blob/master/docs/api/agents.md)
- [MCP server tools](https://github.com/paperclipai/paperclip/blob/master/packages/mcp-server/README.md)
- [Paperclip skill source](https://github.com/paperclipai/paperclip/blob/master/skills/paperclip/SKILL.md)

Safe company import still rejects `replace` for existing companies, so the repo's native-API deploy/sync path remains justified. Current local touchpoints are [`agents/deploy.sh`](../agents/deploy.sh), [`agents/_sync_config.py`](../agents/_sync_config.py), [`agents/.paperclip.yaml`](../agents/.paperclip.yaml), and the still-custom PR trigger in [`.github/workflows/staff-engineer-trigger.yml`](../.github/workflows/staff-engineer-trigger.yml). The sync path now uses native `POST /api/agents/:id/skills/sync` for desired-skill assignment and patches adapter/runtime/env config from the manifest only where no narrower endpoint exists. See the short linked handoff in [`docs/agents/paperclip-simplification-2026-05-04.md`](agents/paperclip-simplification-2026-05-04.md).

## Pre-flight backups

Fresh v2026.512.0 upgrade backups taken 2026-05-12 on
`t.ffmemes.com:/root/paperclip-backups/`:

- `paperclip-20260512T145333Z.sql.gz` — DB dump, gzip verified.
- `paperclip-volume-20260512T145333Z.tgz` — Paperclip named-volume archive,
  tar verified.

Earlier v2026.428.0 upgrade backups taken 2026-05-06 on
`t.ffmemes.com:/root/paperclip-backups/`:

- `paperclip-20260506T160310Z.sql.gz` — DB dump, gzip verified.
- `paperclip-volume-clean-20260506T160914Z.tgz` — Paperclip named-volume archive, tar verified.

Earlier migration backups taken 2026-04-24 09:27 UTC:

On `t.ffmemes.com:/root/paperclip-backups/pre-export-2026-04-24/`:
- `preexport-20260424-092754.sql.gz` — 16 MB DB dump via `paperclipai db:backup`
- `paperclip-config-2026-04-24.tgz` — 2.4 GB tar of `.paperclip` + `.claude` + `.claude.json` from the named volume

Restore (only if needed):
```bash
gunzip -c preexport-20260424-092754.sql.gz | docker exec -i <paperclip-container> psql "$DATABASE_URL"
```

## What Paperclip-native looks like (v2026.512+)

CLI commands we now rely on:
- `paperclipai db:backup` — native DB dump.
- `paperclipai company export <id> --include company,agents,skills` — git-syncable export of the entire company definition.
- `paperclipai dashboard get --json` — replaces custom health-summary scripts.
- `paperclipai heartbeat run --agent-id <id>` — wake an agent on demand.
- Native issue monitors / retry-now — replace comment-only delayed wakeups.
- Native company search — replace broad custom issue scans for slug dedupe.
- Native routine revision history and restore — replace manual description
  history outside git for routine text.

API endpoints we now use directly (no SSH, no `docker cp`):
- `GET  /api/companies/<id>/agents` — slug → agent ID resolution.
- `GET  /api/agents/<id>/instructions-bundle?companyId=<id>` — list current instruction files.
- `PUT  /api/agents/<id>/instructions-bundle/file?companyId=<id>` — body `{path, content}`. Records audit + config revision (rollbackable).
- `PATCH /api/agents/<id>` — adapter type, adapter config, env bindings, and runtime heartbeat.
- `POST  /api/agents/<id>/skills/sync?companyId=<id>` — desired skills parsed from AGENTS.md frontmatter.
- `PATCH /api/agents/<id>/permissions` — create-agent and related permission drift.
- `PATCH /api/routines/<id>` — routine descriptions declared under `agents/<slug>/routines/*.yaml`; on v2026.512.0 include `baseRevisionId` when available.

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
- **Manifest** `agents/.paperclip.yaml` rewritten in `paperclip/v1` schema with full prod structure (heartbeat, model, reasoning effort, maxTurnsPerRun, env declarations, sidebar order, brand color) and the union of repo + prod env var declarations. The inlined `capabilities` text from prod's `comms-manager` was dropped — `AGENTS.md` is the single source.
- **Removed** `agents/backup/` (legacy local snapshots; server-side backups now exist).
- **Replaced** `agents/deploy.sh`: native API only. No SSH. No docker cp. The second pass calls `_sync_config.py` to diff and patch adapter type/config, env `secret_ref`s, runtime heartbeat, permissions, and desired skills.

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

## Phase 3 — Follow-ups

**3a. Adapter config sync from `.paperclip.yaml`.** ✅ Done 2026-05-06.
`agents/_sync_config.py` reads each agent block from the manifest, resolves Paperclip company secrets by name, preflights every required env binding before any agent config PATCH, applies `adapterType`, `adapterConfig` with `replaceAdapterConfig: true`, env bindings, `runtimeConfig.heartbeat`, permissions, and syncs desired skills through the native skills endpoint. It also syncs routine description files declared under `agents/<slug>/routines/*.yaml`. Current Codex config: all managed agents use `codex_local` + `gpt-5.5`; CEO runs effort `xhigh`, Analyst/CTO/QA/Staff run effort `high`, and Comms/Release run effort `medium`.

**2026-05-12 update:** all agents are now configured for `codex_local` in the
manifest. Codex auth is subscription/OAuth-only; `OPENAI_API_KEY` is deliberately
absent from Codex env bindings.

**3b. Retire the webhook proxy.** ✅ Done 2026-04-29. QA trigger signing mode flipped to `none`; Sentry Internal Integration now POSTs directly to the Paperclip QA trigger URL stored in Sentry/Paperclip configuration. Do not commit routine trigger IDs or full public trigger paths; treat publicIds as sensitive operational material. Deleted: `src/integrations/paperclip.py`, `notify_qa_sync` callsite in `src/flows/hooks.py`, env vars `WEBHOOK_PROXY_SECRET` / `SENTRY_CLIENT_SECRET` / `PAPERCLIP_QA_TRIGGER_URL` / `PAPERCLIP_QA_TRIGGER_SECRET`. Coolify webhook path was unused (no hits in 24h prior to removal). Prefect failures now surface via the QA Log Scan 3h cron instead of an instant push — accepted tradeoff for less code. Trigger publicId leakage = at most noisy QA scans (no user input or commands accepted).

**3c. CLI-native agent skills and v512 built-ins.** In each AGENTS.md, replace raw `curl https://org.ffmemes.com/api/...` with native Paperclip skill/MCP/CLI operations: issue search, company search, planning-mode issue creation, monitor/retry-now, approvals, `paperclipai dashboard get`, and `paperclipai heartbeat run --agent-id`. Reduces per-wake context and avoids custom liveness logic.

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
- Paperclip deploy/sync from git — still custom because existing-company
  `replace` import is blocked by the safe import route.

## Risks acknowledged

- **First deploy overwrites 4 prod-ahead agents** (CEO/CTO/release-eng/staff-eng) with older repo text. Reviewer must decide pre-merge.
- **`--collision replace` was rejected** by the v416 safe-import server — we work around with per-file PUT, but if Paperclip changes the instructions-bundle endpoint behavior in a future version, we re-evaluate.
- **No drift monitoring yet.** Auto-deploy reduces drift; UI edits between deploys still possible. Codex recommended a nightly `company export` artifact job; deferred per CEO call. Revisit if drift bites.
- **CI auth uses a single API key.** No first-class service-account exists in Paperclip. The key must be scoped to this company and rotated if leaked.
- **Env sync replaces live `adapterConfig.env` from the manifest.** Required missing secrets now abort before PATCH; optional missing secrets are omitted. Comms `DATABASE_URL` intentionally maps to the read-only `ANALYST_DATABASE_URL` secret, so `editorial_posts` writes from agent runtime are not guaranteed until a dedicated writer secret is created.
- **Codex API-key billing regression.** If `OPENAI_API_KEY` is added to the
  Paperclip host env or to any `codex_local` agent env, Codex CLI 0.122+ can
  switch from subscription OAuth to API-key billing. Treat that as a deploy
  blocker unless explicitly approved.
