# PR review cycle (Staff Engineer agent)

Concise reference for how the autonomous PR review loop works. For the full
agent infrastructure, see `paperclip-ops-runbook.md`.

## Trigger flow

1. PR `opened`, `reopened`, or `synchronize` (push to PR branch) →
   `.github/workflows/staff-engineer-trigger.yml` fires.
2. Workflow `POST`s the Paperclip PR Review routine trigger with
   `{pr_number, pr_url}`. URL and bearer secret live in GitHub Actions secrets
   / workflow config; do not paste trigger IDs into public docs.
3. Paperclip routes to the **Staff Engineer** agent (id
   `1a323bb6-2b4d-46bf-9c33-7971fa1673d5`). Its status flips
   `idle → running` and `lastHeartbeatAt` ticks.
4. Staff Engineer reads CI state, checks out the PR, runs `/review` plus
   `/codex review`, posts a GitHub-visible review signal, then either:
   - **Approve** — real `gh pr review --approve` when allowed, or a
     `STAFF ENGINEER REVIEW: APPROVED` comment fallback for self-review-blocked
     PRs; internal PRs are queued with `gh pr merge --squash --auto`.
   - **Hold** — real request-changes review when allowed, or a
     `STAFF ENGINEER REVIEW: CHANGES REQUESTED` comment fallback. A CTO issue
     is created for required fixes.

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
curl -s -X POST \
  "$PAPERCLIP_PR_REVIEW_TRIGGER_URL" \
  -H "Authorization: Bearer $PAPERCLIP_TRIGGER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"pr_number": 183, "pr_url": "https://github.com/ffmemes/ff-backend/pull/183"}'
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
