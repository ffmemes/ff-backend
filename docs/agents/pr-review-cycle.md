# PR review cycle (Staff Engineer agent)

Concise reference for how the autonomous PR review loop works. For the full
agent infrastructure, see `paperclip-ops-runbook.md`.

## Trigger flow

1. PR `opened`, `reopened`, or `synchronize` (push to PR branch) →
   `.github/workflows/staff-engineer-trigger.yml` fires.
2. Workflow `POST`s the bearer trigger at
   `https://org.ffmemes.com/api/routine-triggers/public/910d844a954042dc060c56bf/fire`
   with `{pr_number, pr_url}`. Secret is in repo secret `PAPERCLIP_TRIGGER_SECRET`.
3. Paperclip routes to the **Staff Engineer** agent (id
   `1a323bb6-2b4d-46bf-9c33-7971fa1673d5`). Its status flips
   `idle → running` and `lastHeartbeatAt` ticks.
4. Staff Engineer reads CI state, runs `gh pr checkout`, runs the `review`
   skill (codex pass + structural checks), then either:
   - **Approve** — `gh pr review --approve` and `gh pr merge --squash`.
   - **Hold** — posts a `## Staff Engineer review — changes requested`
     comment listing P1/P2 issues. (Self-authored PRs can't be reviewed
     with `--request-changes`, so a comment is the canonical signal.)

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
- A single alembic head (lint catches this).
- The PR description's "Test plan" boxes don't have to all be ticked, but
  obvious gaps (e.g. "no tests added for new public function") will hold.
- No banned-substring violations introduced into agent-facing instructions.

## Manual fire (if the GitHub workflow misses)

Per `~/.claude/projects/.../memory/reference_paperclip_trigger_secrets.md`:

```bash
curl -s -X POST \
  "https://org.ffmemes.com/api/routine-triggers/public/910d844a954042dc060c56bf/fire" \
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
