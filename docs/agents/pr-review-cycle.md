# PR review cycle (Staff Engineer agent)

Concise reference for how the autonomous PR review loop works. For the full
agent infrastructure, see `paperclip-ops-runbook.md`.

## Trigger flow

1. PR `opened`, `reopened`, or `synchronize` (push to PR branch) →
   `.github/workflows/staff-engineer-trigger.yml` fires.
2. Workflow calls Paperclip's native routine API run endpoint. It looks up the
   `[pr:{{pr_number}}] Review` routine and enabled API trigger, then sends
   `{pr_number, pr_url}` as explicit routine variables. Auth uses the existing
   `PAPERCLIP_URL` + `PAPERCLIP_API_KEY` GitHub Actions secrets; do not paste
   routine or trigger IDs into public docs.
3. Paperclip routes to the **Staff Engineer** agent (id
   `1a323bb6-2b4d-46bf-9c33-7971fa1673d5`). Its status flips
   `idle → running` and `lastHeartbeatAt` ticks.
4. Staff Engineer reads CI state, checks out the PR, runs `/review` plus
   `/codex review`, posts a GitHub-visible review signal, then either:
   - **Approve** — real `gh pr review --approve` when allowed, or a
     `STAFF ENGINEER REVIEW: APPROVED` comment fallback for self-review-blocked
     PRs; internal PRs are queued with `gh pr merge --squash --auto`.
   - **Hold** — real request-changes review when allowed, or a
     `STAFF ENGINEER REVIEW: CHANGES REQUESTED` comment fallback. A CTO child
     issue/subtask is created through native Paperclip tooling for required
     fixes.

## What "running" means

Status is `running` only while the agent is actively burning CPU/turns. Heartbeat
updates while running. Status returns to `idle` after the agent's task closes,
whether merged, held, or errored.

## After a hold

A new push to the PR branch fires the `synchronize` event automatically. **No
need to close-and-reopen** — the trigger re-fires on every push. The agent
re-reads the latest CI state on its next run; it does not remember its previous
review unless it left a comment.

## Pre-merge invariants the agent enforces

- All required CI checks (`lint`, `test`) must be green.
- Auto-merge must be enabled before merge; the agent queues `--auto` instead of
  racing CI with a bare merge.
- A single alembic head (lint catches this).
- External/fork PRs are never auto-merged, even if their branch name looks
  internal.
- The PR description's "Test plan" boxes don't have to all be ticked, but
  obvious gaps (e.g. "no tests added for new public function") will hold.
- No banned-substring violations introduced into agent-facing instructions.
- Coolify A3 deploy timestamp probe failures file `[chain-broken:*]` follow-up
  issues instead of blocking the already-delivered review/merge issue.

## Manual fire (if the GitHub workflow misses)

```bash
ROUTINES_JSON="$(curl -sSf \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  "$PAPERCLIP_URL/api/companies/$PAPERCLIP_COMPANY_ID/routines")"
ROUTINE_ID="$(printf '%s' "$ROUTINES_JSON" | jq -r '.[] | select(.title == "[pr:{{pr_number}}] Review") | .id' | head -1)"
API_TRIGGER_ID="$(printf '%s' "$ROUTINES_JSON" | jq -r --arg id "$ROUTINE_ID" '.[] | select(.id == $id) | (.triggers // [])[] | select(.kind == "api" and (.enabled != false)) | .id' | head -1)"
jq -n \
  --arg trigger "$API_TRIGGER_ID" \
  --arg pr "183" \
  --arg url "https://github.com/ffmemes/ff-backend/pull/183" \
  '{
    source: "api",
    triggerId: $trigger,
    payload: {pr_number: $pr, pr_url: $url, variables: {pr_number: $pr, pr_url: $url}},
    variables: {pr_number: $pr, pr_url: $url}
  }' | curl -sSf -X POST \
    "$PAPERCLIP_URL/api/routines/$ROUTINE_ID/run" \
    -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
    -H "Content-Type: application/json" \
    --data @-
```

## Why the agent did not merge PR #183 on first push

Recorded so the failure mode is searchable:

1. CI test job was red (Cyrillic homoglyph bypass test caught a real ban-list gap).
2. `mergeStateStatus` was `DIRTY` (rebase needed onto current production).
3. Even after rebase, multi-head migration produced an `UndefinedTableError`
   that masked as a runtime test failure — fixed by adding the alembic-head
   check to the lint job (this PR).

The agent itself worked correctly: it held merge while CI was red, then
approved and merged once both CI and the structural reviews passed on push
`81333de`.
