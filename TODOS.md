# TODOS

> Living backlog only. Completed items live in git history and dated experiment
> write-ups under `experiments/completed/` / `specs/archive/`.
> Last cleaned: 2026-06 (Wave A hygiene).

**Product compass:** [docs/growth/virality-loop.md](docs/growth/virality-loop.md)

## P1 — Growth & feed measurement

### ~~Virality score for ranking~~ — SHIPPED as viral_shares_blender_v1
**What:** Engine `viral_shares` + mature blend A/B (`viral_shares_blender_v1`). See `experiments/active/2026-08-09-viral-shares-blender-v1.md`.
**Next:** day-7 readout via `docs/analyst/viral-shares-blender-v1.sql`; decide keep/scale/kill.

### Per-engine session continuation rate (dashboard)
**What:** SQL/readout for % of times a user continues scrolling after a meme from each `recommended_by` engine.
**Why:** Better engine evaluation than LR; aligns with session-length north star.
**Context:** Measurement patterns exist in archived cold-start / es-ranked experiment notes under `specs/archive/`.

### ~~Share CTA experiment harness~~ — seam landed
**What:** `src/tgbot/senders/delivery.py` unifies prep for `next_message` + `send_meme_to_user`.
**Next:** CTA copy/placement experiments only need to touch delivery + `sharing.py`.

## P2 — Supply side (ETL)

### Align VK ETL guards with TG
**What:** `parsing_enabled` gate, broken-link retry, auto-snooze after empty parses — currently TG-only in places.
**Why:** Feature drift floods or starves VK content relative to TG.
**Files:** `src/storage/etl.py`, `src/storage/service.py`, `src/flows/parsers/vk.py`

### Auto-discover sources from forwards
**What:** Forwarded channel URLs → `meme_source_candidate` (partially shipped). Keep discovery + moderator vote loop healthy.
**Files:** TG parser + `specs/moderator-community-loop.md`

### Auto-snooze broken sources
**What:** Consecutive empty parses / catastrophic like_rate → `snoozed` + alert.
**Status:** TG has partial auto-snooze; extend carefully.

## P2 — Platform hygiene

### Parameterize remaining f-string SQL on hot paths
**What:** Prefer bound params for user-id style queries in `tgbot/repo` and admin upload stats.
**Why:** Consistency + safety; not classical SQLi when ids are ints, but pattern is easy to misuse.

### Language list SSOT
**What:** One registry for meme languages (feed / upload / source admin currently diverge).
**Files:** `handlers/language.py`, `handlers/upload/constants.py`, `senders/keyboards.py`

### Drop or wire orphan tables
**What:** `user_wrapped` (Redis-only wrapped today); inventory `meme_raw_ig` then freeze or drop.
**Why:** Schema that nothing writes confuses agents and migrations.

## P3 — Nice-to-have

### Pre-commit secrets scanner upgrade
**What:** Stronger scanner than current shell hook (`detect-secrets` or keep `redaction_audit.py` as sole gate).
**Why:** Public repo.

### PTB handler layout pass
**What:** Clearer **регистратор Telegram-хендлеров** boundaries as moderator features grow.
**Files:** `src/tgbot/app.py`, `handlers/moderator/registry.py`

## Explicitly not doing right now

- Rebuilding full Feed Turn (`turn.py` / `refill.py`) until delivery ownership needs it — **planner is already live**.
- Merging `comms` / `crossposting` / `broadcasts` packages (different seams).
- Re-adding Instagram parsing without a product decision.
