# Agent Autonomy Metrics

Use this to judge whether Paperclip changes make the organization more
autonomous, not just busier.

## Goal

The organization should turn product ideas, TODOs, experiments, bugs, and
routine findings into shipped work with less human routing.

## Weekly Scorecard

Track these every Monday in the CEO review:

| Metric | Target direction | Source |
|---|---|---|
| Idea-to-task conversion | up | CEO-created Paperclip issues from `TODOs`, `specs`, reports, experiments |
| Task-to-PR conversion | up | Paperclip issue links + GitHub PRs |
| PR-to-production completion | up | merged PRs + deploy verification |
| Human touch rate | down | issues requiring `ohld` comments/manual triggers before progress |
| Stale assigned work | down | assigned `todo`/`in_progress` issues older than 7 days |
| Blocker quality | up | blocked issues with `blockedByIssueIds` instead of comment-only blockers |
| Child issue completion | up | parent issues completed by agent-created child tasks |
| Routine useful outcome rate | up | `scripts/paperclip_routine_audit.py --json` |
| Comms publish completion | up | `[post:...]` issues closed with `telegram_message_id` + `editorial_post_id` |
| Decision yield | up | `scripts/paperclip_outcome_audit.py --days 7 --json` |
| Stale active experiments | down | `experiments/active/*` parsed by `paperclip_outcome_audit.py` |
| Stopped-work decisions | up | weekly `[strategy:weekly-outcomes-YYYY-MM-DD]` issue |

## CEO-Specific Check

If CEO is not implementing the backlog, measure the funnel instead of guessing:

1. Count new candidate inputs: TODOs, specs ideas, experiments, analyst
   recommendations, and routine findings.
2. Count CEO decisions: created issue, rejected, deferred with reason, or asked
   Analyst for data.
3. Count downstream execution: CTO/Comms/Analyst child issue created, PR opened,
   post published, experiment moved.
4. Flag any candidate older than 14 days with no CEO decision as
   `ceo_attention_gap`.

The CEO should not code. A healthy CEO creates clear child issues, uses
structured confirmation cards through the native Paperclip skill for real gates,
sets `blockedByIssueIds` when waiting on data or implementation, and closes the
loop when child issues finish.

## Outcome Review

Every Monday, run:

```bash
source ~/.zshrc 2>/dev/null || true
python3 scripts/paperclip_outcome_audit.py --days 7
```

The point is to catch weeks where the organization completes many issues but
does not close product loops. Treat these flags as CEO-level blockers:

- `activity_without_decisions`: 50+ completed issues and fewer than 3 decision
  events.
- `low_decision_yield`: decision events are less than 5% of completed issue
  volume.
- `execution_heavy_week`: PRs, deploys, scans, incidents, reports, and
  maintenance dominate the week.
- `stale_active_experiments`: an active experiment is past its measurement date,
  is still deployment-pending after 7 days, or lacks a parseable measurement
  date after 21 days.

The weekly CEO review should create or update one
`[strategy:weekly-outcomes-YYYY-MM-DD]` issue with:

1. Product decisions closed: continue, complete, cancel, or ask Analyst for data.
2. Work shipped to production: PR/deploy outcomes, not just reviewed PRs.
3. Work to stop, merge, or delete: stale issues, duplicate incidents, stale
   experiments, dead bets.
4. Next bet: one clear priority for the coming week.

If `paperclip_outcome_audit.py` emits `activity_without_decisions`,
`low_decision_yield`, or `stale_active_experiments`, do not open new
non-critical execution work until the outcome issue records the keep/kill/change
decisions.

## Existing Tools

- [`routine-observability.md`](routine-observability.md) defines routine outcome
  contracts.
- [`outcome-ledger.md`](outcome-ledger.md) defines the weekly CEO outcome review
  contract.
- [`paperclip-simplification-2026-05-04.md`](../archive/2026-q2/paperclip-simplification-2026-05-04.md)
  (archive) records the runtime simplification direction.
- [`../../scripts/paperclip_routine_audit.py`](../../scripts/paperclip_routine_audit.py)
  gives compact routine health input.
- [`../../scripts/paperclip_outcome_audit.py`](../../scripts/paperclip_outcome_audit.py)
  gives compact outcome-throughput input.
