# Agent Outcome Ledger

Use this when the organization is producing many issues, PR reviews, reports,
and routine comments. The goal is to force a CEO-level answer to: what did we
learn, what changed in the product, what should stop, and what is the next bet?

## First Command

```bash
source ~/.zshrc 2>/dev/null || true
python scripts/paperclip_outcome_audit.py --days 7
```

Use `--json` when another agent needs compact structured input.

## Weekly CEO Contract

Every Weekly CEO Review must create or update exactly one strategy issue:

`[strategy:weekly-outcomes-YYYY-MM-DD] Weekly outcome review`

That issue is the source of truth for the week. It must contain:

```markdown
## Outcome audit
- decision_yield:
- flags:
- issue mix:

## Decisions closed
- Continue:
- Complete:
- Cancel:
- Ask Analyst:

## Shipped outcomes
- Production changes:
- Published comms:
- Verified deploys:

## Stop list
- Stale experiments:
- Duplicate/merged issues:
- Work to stop doing:

## Next bet
- Bet:
- Owner:
- Success metric:
- First execution task:
```

## Gates

If any of these are true, the CEO review is not green:

- `activity_without_decisions`: the team closed 50+ issues but recorded fewer
  than 3 decision events.
- `low_decision_yield`: decision events are less than 5% of completed issue
  volume.
- `stale_active_experiments`: an active experiment is past its measurement date,
  still deployment-pending after 7 days, or has no parseable measurement date
  after 21 days.
- More than 2 active experiments are running.

When a gate is red, the CEO must close the decision gap before creating new
non-critical CTO/QA/Comms work.

## What Counts

Counts as an outcome:

- Experiment created, completed, cancelled, archived, or explicitly continued
  with a reason.
- Product decision logged in `experiments/log.jsonl`.
- Production deploy verified.
- Comms post actually published with `telegram_message_id` and
  `editorial_post_id`.
- Incident resolved with root cause and follow-up decision.

Does not count as an outcome by itself:

- PR reviewed.
- Issue closed as no-op.
- Routine execution completed.
- Draft approved but not published.
- Analyst report created without a CEO decision.

## Task Throttle

During the weekly review, create at most three new non-critical execution issues.
Every new execution issue must name the decision or audit flag that caused it.
Critical production incidents are exempt, but they still need stable
`[incident:<slug>]` issue hygiene.
