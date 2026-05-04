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
`request_confirmation` for real gates, sets `blockedByIssueIds` when waiting on
data or implementation, and closes the loop when child issues finish.

## Existing Tools

- [`routine-observability.md`](routine-observability.md) defines routine outcome
  contracts.
- [`paperclip-simplification-2026-05-04.md`](paperclip-simplification-2026-05-04.md)
  defines the runtime simplification direction.
- [`../../scripts/paperclip_routine_audit.py`](../../scripts/paperclip_routine_audit.py)
  gives compact routine health input.
