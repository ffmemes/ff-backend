# Agent Routine Observability

Use this before broad manual audits. The goal is to measure useful outcomes,
not whether Paperclip emitted activity notifications.

## First Command

```bash
source ~/.zshrc
python scripts/paperclip_routine_audit.py --focus all
```

Use `--focus comms` for channel posting and `--focus updates` for Paperclip /
gstack checks. Add `--json` when another agent needs compact structured input.

## Outcome Contracts

### Daily Channel Post

Terminal success is `outcome=published` with both:

- `telegram_message_id`
- `editorial_post_id`

`draft_created`, `approval_pending`, and `APPROVED_TO_PUBLISH` are intermediate
states. CEO approval must reassign the `[post:...]` issue to Comms Manager with
status `todo`; CEO must not close the issue. Comms Manager is the only terminal
owner and closes it after publishing through `publish_editorial_post()`.

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

This is not only a SHA poll. Every run should record:

- deployed Paperclip version/ref
- latest stable npm version
- latest canary version, ignored unless explicitly requested
- changelog delta since deployed version
- impact on this agent system: simplifications, bug fixes, new skills/tools

If upstream changed, create one triage issue with the impact summary. Do not
bury the analysis in a completed routine comment.

## Telegram Activity Feed

`@ffnerdbot` is only a low-signal activity feed. It proves that agents started
or stopped tasks; it does not prove that a useful product outcome happened.
Routine health should come from the outcome contracts above and from Paperclip
issues/comments, not from Telegram notifications.

## Context Discipline For Agents

- Spawn subagents only with bounded questions and required output fields.
- Prefer `scripts/paperclip_routine_audit.py --json` over dumping full agent
  configs, issue lists, or server logs into context.
- Summarize upstream changelogs into a repo doc or Paperclip issue first, then
  reason from that artifact.
- Treat secrets in Paperclip agent config as toxic output. Never paste values
  into comments, docs, or chat.
