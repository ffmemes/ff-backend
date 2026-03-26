# Experiments

Structured experiment tracking for AI agents and manual development.

## Directory Structure

```
experiments/
├── active/           # Currently running experiments
│   └── YYYY-MM-DD-experiment-name.md
├── completed/        # Finished experiments (never deleted)
│   └── YYYY-MM-DD-experiment-name.md
├── reports/          # Analyst daily reports
│   └── YYYY-MM-DD-daily.md
└── log.jsonl         # Machine-readable audit trail
```

## Experiment Lifecycle

1. **Create**: CEO agent creates `active/YYYY-MM-DD-name.md`
2. **Monitor**: Analyst agent tracks metrics in daily reports
3. **Complete**: CEO moves from `active/` to `completed/` with results
4. **Never delete**: Completed experiments are historical artifacts

## Experiment File Format

```markdown
# Experiment: [Name]
Created: YYYY-MM-DD
Status: active | completed | cancelled
Owner: ceo | engineer | analyst

## Hypothesis
What we expect to happen and why.

## Changes Made
What was changed (commits, config, etc.)

## Metrics Before
Key metrics at experiment start.

## Metrics After
Key metrics at experiment end (filled by CEO on completion).

## Conclusion
What we learned (filled on completion).
```

## Daily Report Format (reports/)

```markdown
# Daily Report: YYYY-MM-DD

## Health Check
[Output of HEALTH CHECK query from docs/analyst/metrics.sql]

## North Star
Session length: median=X, avg=Y

## Anomalies
[Any metrics that deviate >30% from 7-day average]

## Active Experiments
[Status update for each experiment in active/]

## Community Feedback
[Summary of @ffmemes channel activity]

## Recommendations for CEO
[Prioritized list of suggested actions]
```

## JSONL Audit Log (log.jsonl)

Each line is a JSON object:

```json
{
  "timestamp": "2026-03-20T19:30:00Z",
  "agent": "analyst",
  "action": "daily_report",
  "status": "success",
  "summary": "Generated daily report. No anomalies detected.",
  "metrics": {
    "session_length_median": 19,
    "wau": 530,
    "dau": 180,
    "reactions_24h": 5200,
    "like_rate": 43.4
  },
  "active_experiments": ["goat-fix"],
  "error": null
}
```

### Action Types
- `daily_report` — Analyst produced a metrics report
- `anomaly_detected` — Analyst flagged a metric deviation
- `experiment_created` — CEO started a new experiment
- `experiment_completed` — CEO concluded an experiment
- `task_created` — CEO assigned work to another agent
- `investigation` — Analyst dug deeper into an anomaly
- `post_published` — Comms Manager posted to @ffmemes
