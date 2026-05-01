---
status: IMPLEMENTED
---
# Ralphex Plan: Feed Turn Planner Contract

Repo: ffmemes/ff-backend
Primary brief: specs/feed-turn-module.md
Target PR: first safe Feed Turn Module slice

## Goal

Add a pure Feed Turn recommendation planner contract and tests. This first PR
must not wire the planner into the production recommendation path yet.

The goal is to lock the current maturity-stage decision table before any hot
path refactor touches Redis, Postgres, Telegram delivery, or queue mutation.

## Hard Constraints

- Do not edit `src/recommendations/meme_queue.py` in this PR.
- Do not change `generate_recommendations()` behavior or public signature.
- Do not change `src/tgbot/senders/next_message.py`.
- Do not change `src/tgbot/handlers/reaction.py`.
- Do not change Redis key format or queued meme JSON shape.
- Do not add migrations, schema changes, feature flags, or observability writes.
- Do not rename engine names or production `recommended_by` strings.
- Do not weaken existing tests.

## Planner Contract

Create:

```text
src/feed_turn/
  __init__.py
  planner.py
```

The planner must be pure:

- no Redis imports
- no SQLAlchemy imports
- no Telegram imports
- no `CandidatesRetriever` imports
- no async functions
- no DB or network access

Required public interface:

```python
@dataclass(frozen=True)
class EngineFallback:
    engine: str
    kwargs: Mapping[str, Any]


@dataclass(frozen=True)
class CandidateSelectionPlan:
    maturity_stage: str
    primary_engine: str | None
    blend_weights: Mapping[str, float]
    fixed_pos: Mapping[int, str]
    fallback_engines: tuple[EngineFallback, ...]


def plan_candidate_selection(nmemes_sent: int) -> CandidateSelectionPlan:
    ...


def low_sent_quota(limit: int, user_type: str | None) -> int:
    ...
```

## Current Behavior To Encode

Regular users:

- `nmemes_sent < 6`
  - primary engine: `cold_start_explore`
  - fallback engines: `lr_smoothed` with `min_sends=10`, then `best_uploaded_memes`
- `6 <= nmemes_sent < 16`
  - primary engine: `cold_start_adapt`
  - fallback engines: `lr_smoothed` with `min_sends=10`, then `best_uploaded_memes`
- `16 <= nmemes_sent < 30`
  - blend weights: `cold_start_adapt=0.5`, `lr_smoothed=0.3`,
    `like_spread_and_recent_memes=0.2`
  - fixed position: `{0: "cold_start_adapt"}`
  - if blend is empty, fallback engines: `cold_start_adapt`, `lr_smoothed` with
    `min_sends=10`, then `best_uploaded_memes`
- `30 <= nmemes_sent < 100`
  - blend weights: `best_uploaded_memes=0.1`, `lr_smoothed=0.3`,
    `recently_liked=0.2`, `goat=0.1`, `es_ranked=0.1`,
    `like_spread_and_recent_memes=0.2`
  - fixed position: `{0: "lr_smoothed"}`
  - no fallback after blend
- `nmemes_sent >= 100`
  - blend weights: `best_uploaded_memes=0.3`,
    `like_spread_and_recent_memes=0.3`, `lr_smoothed=0.4`,
    `recently_liked=0.2`, `goat=0.1`, `es_ranked=0.1`
  - fixed position: `{0: "lr_smoothed"}`
  - no fallback after blend

Moderator/admin quota:

- `low_sent_quota(limit, "moderator") == ceil(limit * 0.75)`
- `low_sent_quota(limit, "admin") == ceil(limit * 0.75)`
- regular, unknown, and null user types get quota `0`

## Tasks

Ralphex may enforce one task per iteration. Keep checkbox status accurate and
do not mark later tasks complete until their own verification has run.

### Task 1: Add Pure Planner Tests

- [x] Add `tests/feed_turn/test_planner.py`.
- [x] Cover exact stage boundaries: `5/6`, `15/16`, `29/30`, `99/100`.
- [x] Assert cold-start primary engines and fallback engines.
- [x] Assert `lr_smoothed` cold-start fallback keeps `kwargs == {"min_sends": 10}`.
- [x] Assert transition, growing, and mature blend weights and fixed positions.
- [x] Assert moderator/admin low-sent quota uses `ceil(limit * 0.75)`.
- [x] Assert regular, unknown, and null user types get no low-sent quota.
- [x] Ensure tests do not hit Redis, Postgres, Telegram, or `CandidatesRetriever`.

### Task 2: Add Pure Planner Module

- [x] Create `src/feed_turn/__init__.py`.
- [x] Create `src/feed_turn/planner.py`.
- [x] Add frozen dataclasses for `EngineFallback` and `CandidateSelectionPlan`.
- [x] Implement `plan_candidate_selection()`.
- [x] Implement `low_sent_quota()`.
- [x] Keep mapping fields read-only where practical.
- [x] Do not edit `src/recommendations/meme_queue.py`.

### Task 3: Verify Local Safety

- [x] Run:

```bash
pytest tests/feed_turn/test_planner.py tests/recommendations/test_meme_queue.py -q
ruff check src/ tests/
ruff format --check src/ tests/
```

- [x] If the full integration gate is run, run it inside compose/test infra,
  not host-mode defaults that cannot resolve `redis` or `app_db`.
- [x] In the PR body, state behavior changed: `none`.
- [x] In the PR body, state production path wiring is intentionally deferred to
  the next PR.

## Suggested Ralphex Command

The tasks above are already complete in this branch. Use review mode for this
branch to avoid re-running the implementation task:

```bash
ralphex --review specs/feed-turn-ralphex-plan.md
```

For a fresh implementation from `production`, use:

From the repo root:

```bash
ralphex \
  --worktree \
  --max-iterations 4 \
  --review-patience 2 \
  --session-timeout 30m \
  --idle-timeout 5m \
  specs/feed-turn-ralphex-plan.md
```

Optional dashboard/watch mode in a separate terminal:

```bash
ralphex --serve --port 8081 --watch .ralphex/progress
```

Progress log is expected near:

```bash
tail -f .ralphex/progress/progress-feed-turn-ralphex-plan.txt
```

## Babysitting Checklist

- [x] Stop or redirect if Ralphex edits `meme_queue.py`, `next_message.py`,
  `reaction.py`, Redis helpers, migrations, schemas, or observability writes.
- [x] Watch for changed engine names, weights, boundaries, fallback order, or
  `min_sends=10`.
- [x] Watch for weakened assertions in existing tests.
- [x] Before PR creation, inspect `git diff --stat` and `git diff`.
