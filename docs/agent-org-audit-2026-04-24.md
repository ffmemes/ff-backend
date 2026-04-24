# Agent org audit — issue origin (last 100 issues)

**Window:** 2026-03-27 → 2026-04-24 (29 days, last 100 issues).
**Goal:** validate or refute codex's hypothesis that routines mechanically manufacture firefighting volume — and identify which routines/agents to throttle.

## Origin breakdown

| Origin × Creator | Count | % of 100 |
|---|---:|---:|
| `manual` × QA Engineer (`4b02ab32`) | 38 | 38% |
| `routine_execution` × null (PR Review routine `39bf8a48`) | 30 | 30% |
| `manual` × CEO (`e782143b`) | 23 | 23% |
| `manual` × null (board / human) | 4 | 4% |
| `manual` × CTO (`ebdad67a`) | 3 | 3% |
| `manual` × Analyst (`9c87d840`) | 2 | 2% |

100% of `routine_execution` issues come from a single routine: **PR Review**. No other routine writes to the inbox directly — they wake agents who then file issues manually.

## QA's 38 issues — almost entirely firefighting + duplicates

By topic (string match in title):

| Topic | Count | Notes |
|---|---:|---|
| DB connection pool / asyncpg | 11 | 4 separate "PRODUCTION INCIDENT: DB connection pool exhaustion" / "URGENT: Connection pool exhaustion" / "CRITICAL: DB pool exhausted" / "CRITICAL: Deploy DB pool fix" filed within hours of each other on 2026-04-01 — clear duplicate-filing |
| `describe_memes` / OpenRouter | 6 | repeated incidents over Apr 8 → Apr 19 — fits the `feedback_describe_memes_no_issues.md` rule that QA shouldn't file these at all |
| `score` column / `ProgrammingError` | 4 | filed Apr 13–14 across 4 separate issues for the same root cause |
| Other infra/incident | ~15 | TG conflict, ETL crashes, IG circuit breaker, video upload stuck, webhook 502, etc. |
| Genuine net-new bug found | ~2 | proportional to the 100 |

**Conclusion:** QA's role is structurally a fire-detector, but it files duplicates rather than commenting on existing tickets. CEO's `issue-hygiene-v1` rule (slug-first titles, dedupe preflight, `[incident:<slug>]`) lives in CEO's prompt but **not in QA's** — explains the duplication.

## CEO's 23 issues — half strategic, half routing

Sample: `[experiment:early-channel-popup]`, `[report:2026-04-22]`, `[incident:analyst-stale-heartbeat]`, `URGENT: Ship PR #140`, `Daily analyst report Apr 6`, `Fix comms agent: Russian font`. Roughly:
- ~10 strategic / experiment-driving (`[experiment:...]`, "Implement goat per-user recency filter")
- ~8 reactive routing ("URGENT: Ship", "Fix describe_memes degradation")
- ~5 daily-report tracking issues

CEO is doing some proactive work — but report-tracking + reactive routing dominate the volume.

## PR Review's 30 issues — boilerplate routine

All 30 titled exactly `"PR Review"` (no PR number in title — bad for slug dedupe). Routine `39bf8a48` fires on each PR webhook, creates one execution issue, Staff Eng works it. Most close as `done` quickly. Volume is high but **not actually firefighting** — it's necessary review work. Problem: the issues clutter CEO's inbox view because they share a project with strategic issues.

## Verdict on codex's hypothesis

**Partially right, partially wrong.**

- **Wrong:** routines do not directly create firefighting issues. PR Review (the only routine that writes the inbox) creates legitimate review work, not noise.
- **Right:** routines mechanically manufacture firefighting *via the QA agent*. QA Log Scan / Process Health Check wake QA, who then files duplicate incident issues.

So the fix isn't "kill routines" — it's:
1. **Make QA dedupe correctly** (apply `[incident:<slug>]` hygiene — port the CEO's rule into QA's prompt).
2. **Cap QA Log Scan output** to one daily summary issue per topic, not N per error class.
3. **Filter PR Review issues out of CEO's inbox view** (project assignment or label) so the 30% volume doesn't displace strategic work in CEO's attention.
4. **Suppress `describe_memes` reports entirely** — already in `feedback_describe_memes_no_issues.md` memory, but QA's prompt didn't have it. Add explicitly.

## Action items into Stage 1.2

| Action | Where | Effort |
|---|---|---|
| Port `issue-hygiene-v1` rule into QA's AGENTS.md (slug-first, dedupe preflight, single-writer for execution issues) | `agents/qa-engineer/AGENTS.md` | small edit |
| Add explicit "DO NOT file describe_memes / OpenRouter / DB-pool-recurrence issues — comment on existing instead" to QA prompt | `agents/qa-engineer/AGENTS.md` | small edit |
| Cap QA Log Scan output: one summary issue per day max, with bulleted findings | QA's AGENTS.md "Routine" section | small edit |
| (Defer) Move PR Review issues to a separate Paperclip project so CEO inbox filter excludes them | Paperclip UI / API | medium |
| (Defer) Add issue-source dashboard for ongoing monitoring | Stage 2.3 | medium |

**No routines killed in Stage 1** — the routines themselves aren't broken, the agents they wake need stricter dedupe discipline.
