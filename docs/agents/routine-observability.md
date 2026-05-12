# Agent Routine Observability

Use this before broad manual audits. The goal is to measure useful FFmemes
**business outcomes**, not generic Paperclip liveness.

Two layers, do not duplicate:

- **Native Paperclip runtime** (v2026.428+, with v2026.512 issue monitors)
  owns generic liveness, stall /
  zombie-run detection, stranded assignment recovery, and productivity-review
  escalation. Read those from the Paperclip dashboard / native routine
  tooling.
- `scripts/paperclip_routine_audit.py` (this doc) owns narrow, FFmemes-specific
  outcome-contract checks: channel post publication markers, update-check
  content (changelog/version/verified deploy commit), gstack update path,
  draft handoff state, and PR payload mismatch. It does not re-derive stall
  or no-comment signals — those belong to the native runtime.

## First Command

```bash
source ~/.zshrc
python3 scripts/paperclip_routine_audit.py --focus all
```

Use `--focus comms` for channel posting and `--focus updates` for Paperclip /
gstack checks. Add `--json` when another agent needs compact structured input.
The helper reads `PAPERCLIP_API_URL` in Paperclip runtime and falls back to
`PAPERCLIP_URL` for local runs.

## Outcome Contracts

### Daily Channel Post

Terminal success is `outcome=published` with both:

- `telegram_message_id`
- `editorial_post_id`

`draft_created`, `approval_pending`, and an accepted `request_confirmation`
card (the authoritative CEO approval signal) are intermediate states. Legacy
`APPROVED_TO_PUBLISH` comments count as the same intermediate state for old
drafts only. CEO approval must reassign the `[post:...]` issue to Comms
Manager with status `todo`; CEO must not close the issue. Comms Manager is
the only terminal owner and closes it after publishing through
`publish_editorial_post()` using the returned `result.message_id` and
`result.editorial_post_id`.

If a `[post:...]` draft is older than 24 hours, refresh or skip it explicitly.
Do not publish stale daily metrics silently.

### gstack Update Check

Terminal success must include:

- `upstream_ref`
- `checked_count`
- `updated_count`
- `failed_count`
- `stale_count`
- `removed_count`
- `update_method`

If there are persistent 404s, rate limits, removed upstream skills, or no known
update path, the run is degraded. Keep one open
`[maintenance:gstack-update-blocked]` issue instead of closing each daily run as
green.

### Paperclip Update Check

This is not only a SHA poll, and queueing a Coolify deployment is not terminal
success. Every run should record:

- deployed Paperclip version/ref when `/api/health` reports it; otherwise
  `health.version=not_reported` is acceptable only with a verified Coolify
  finished deployment commit
- actual Coolify deployment commit, written as `coolify_deployment_commit` or
  `verified_deployed_commit`
- latest stable npm version
- latest canary version, ignored unless explicitly requested
- changelog delta since deployed version
- impact on this agent system: simplifications, bug fixes, new skills/tools

If upstream changed, create one triage issue with the impact summary. Do not
bury the analysis in a completed routine comment. If a deployment is attempted,
only advance any state file and close green after Coolify reports a finished
deployment whose commit equals the intended target; otherwise leave the run
blocked with `unverified_paperclip_deploy`. Channel publication markers such as
`telegram_message_id` and `editorial_post_id` do not apply to this routine.

### PR Review

Each PR event must create or resume the matching `[pr:<number>] Review` issue
through the Staff Engineer routine API trigger.
If trigger payload `pr_number=215` links to `[pr:214] Review`, that is
`coalesced_pr_review_mismatch`, not healthy queueing.

Paperclip v2026.427+ owns liveness continuations, active-run recovery, and
productivity-review escalation. Keep this audit focused on business outcome
mismatches, then file a Paperclip runtime issue only if the native recovery
surface reports a persistent failure.

### Weekly CEO Review

Terminal success is not "retro ran" or "new tasks created." A healthy Weekly CEO
Review must include the outcome ledger:

- `decision_yield` from `scripts/paperclip_outcome_audit.py --days 7`
- outcome audit flags, if any
- active experiment decisions: continue, complete, cancel, or ask Analyst
- a stop list for stale/duplicate/merged work
- one next bet with owner and success metric
- a linked `[strategy:weekly-outcomes-YYYY-MM-DD]` issue

If the outcome audit reports `activity_without_decisions`,
`low_decision_yield`, or `stale_active_experiments`, the run is YELLOW until the
strategy issue records the keep/kill/change decisions. It is RED if the CEO
opens more non-critical execution work without resolving those flags.

## Telegram Activity Feed

`@ffnerdbot` is only a low-signal activity feed. It proves that agents started
or stopped tasks; it does not prove that a useful product outcome happened.
Routine health should come from the outcome contracts above and from Paperclip
issues/comments, not from Telegram notifications.

## Blocked Work Contract

Do not stop at "blocked". Before setting `blocked`, create or link the issue
that can unblock it, set `blockedByIssueIds`, assign the unblocker to the owning
role, and leave one comment with: blocker, owner, retry condition, and next
automatic wake path.

Routine execution issues should not remain blocked just because the run was
partial. Close the routine issue with `outcome=partial` or `outcome=error` and
link the durable follow-up issue. Use `blocked` only for durable work items that
are waiting on another issue, deploy, approval, or external system.

For time-gated analysis (for example, "measure after 7 full days of data"), do
not leave the issue `blocked` on an already-completed implementation issue. Use
Paperclip's native issue monitor / retry-now surface for the due date, then move
it to `todo` only when the monitor says the data window is actually ready. Keep
an absolute due timestamp in the comment as human context, not as the scheduling
mechanism.

## Context Discipline For Agents

- Stop after the compact audit unless a flagged outcome contract requires
  deeper evidence. Do not dump full Paperclip issue lists, agent configs,
  server logs, dashboard pages, or Telegram activity feeds into context when
  `scripts/paperclip_routine_audit.py --json` already identifies the routine,
  issue id, flag, and expected contract.
- For Paperclip runtime failures, trust native productivity/liveness surfaces
  first. File one Paperclip runtime issue only when the native surface reports a
  persistent failure; do not independently search for stalled runs across raw
  logs unless the native surface is unavailable.
- Use native company search before creating recurrent bracket-slug issues; do
  not dump broad issue lists into context just to dedupe.
- Spawn subagents only with bounded questions and required output fields.
- Prefer `scripts/paperclip_routine_audit.py --json` over dumping full agent
  configs, issue lists, or server logs into context.
- Summarize upstream changelogs into a repo doc or Paperclip issue first, then
  reason from that artifact.
- For Paperclip runtime and sync simplifications, start from
  [`paperclip-simplification-2026-05-04.md`](paperclip-simplification-2026-05-04.md).
- For organization-level autonomy measurement, use
  [`autonomy-metrics.md`](autonomy-metrics.md).
- For issue-throughput versus product-learning measurement, use
  [`outcome-ledger.md`](outcome-ledger.md) and
  [`../../scripts/paperclip_outcome_audit.py`](../../scripts/paperclip_outcome_audit.py).
- Treat secrets in Paperclip agent config as toxic output. Never paste values
  into comments, docs, or chat.
