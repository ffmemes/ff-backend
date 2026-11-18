# November 18 first-five-reactions QA

Both synthetic organic signups reached five distinct reactions. The standard Russian and English paths continued after a language switch. The earliest broken transition was an English onboarding language-picker replay, which delivered another meme before the first reaction. A replayed meme reaction inflated a transient Redis counter in the isolated reproduction.

## Baseline

The pinned base and task HEAD were `130eb0ff327f321e96f1e1e3b5a8b46910d7c613`. The task ran on `codex/credits-first-five-reactions-20261118` in the pre-created worktree of the same name. Read-only metadata from the primary checkout confirmed that the experiment-readout ref points to the pin, local `production` was `45b0f40a`, and the cached `origin/production` was `f0dc4084`. The primary checkout and the registered experiment-readout and comment-prune worktrees belonged to separate tasks.

The harness drives real webhook dispatch, handler registration, Postgres persistence, Redis queues, recommendation candidate selection and Telegram message preparation. PTB encodes its actual Bot API requests and receives synthetic responses in-process. Each journey starts with a new ID, no prior reactions or cached user, and 16 synthetic photo records per locale in the shared catalog. Fixture captions and localized UI text are asserted separately.

| Step | Telegram locale RU | Telegram locale EN |
| --- | --- | --- |
| Organic `/start` | RU welcome and first RU photo | EN welcome, first EN photo, then EN language picker |
| Onboarding picker | No picker offered | Tap English, picker deleted, second EN photo sent. Both photos are unreacted. |
| Reaction 1, like | New RU photo | New EN photo |
| Reaction 2, skip | Existing photo and caption edited to a new RU meme | Existing photo and caption edited to a new EN meme |
| `/lang` and Done | Menu opens in RU. Add EN, remove RU, confirm EN. Done closes the menu. | Menu opens in EN. Add RU, remove EN, confirm RU. Done closes the menu. |
| Reaction 3, like | The existing RU card still accepts a tap. New EN photo and EN share button. | The existing EN card still accepts a tap. New RU photo and RU share button. |
| Reaction 4, skip | Photo and caption edited to a new EN meme | Photo and caption edited to a new RU meme |
| Replay reaction 4 | Callback acknowledged. Same database rows and timestamps, same Redis queue, no extra photo or edit. | Same behavior |
| Reaction 5, like | New EN photo | New RU photo |

The existing `v_new_user.reached_5_reactions` view returned the following for each locale. The query filters out `segment = 'excluded'` and checks organic attribution. The snapshot shifted the synthetic signup, deep-link and send/reaction timestamps together by nine days in a rolled-back transaction, preserving elapsed time while passing the existing eight-day reporting gate.

| Distinct reacted meme IDs | RU fresh | RU mature snapshot | EN fresh | EN mature snapshot |
| --- | --- | --- | --- | --- |
| 4 | `NULL` | `false` | `NULL` | `false` |
| 5 | `NULL` | `true` | `NULL` | `true` |

`first_tap` was true for RU and false for EN. The English journey followed the newest card after the picker sent it. The view checks the first delivered card, which remained unreacted in that journey.

## Isolated product defects

1. **The English picker advances on replay.** Organic `/start` → tap English → redeliver the same `ol:en` update. The Bot API fake returns the already-deleted error for the second delete. The handler catches it and still sends another EN photo. Recorded deliveries increase from two to three with zero reactions. This reproduces before the first reaction. [Language selection handler](../src/tgbot/handlers/language.py#L137)
2. **A duplicate reaction writes an extra watched count.** Organic RU `/start` → like the first photo → redeliver that exact callback. The one real reaction and next photo are unchanged. After replay the observed cache writes for `memes_watched_today` were `1 → 2 → 1`. The handler increments counters before it learns whether the reaction changed. The duplicate was acknowledged and the isolated case observed no extra photo, database reaction, or lasting activation inflation. [Reaction handler](../src/tgbot/handlers/reaction.py#L28)

The two focused tests use strict expected failures for the specific extra send and counter increment. Other test failures surface normally. The runtime handlers, welcome copy, proposed humor previews, allocations and analytics definitions were left as supplied at the pin.

## Reproduction

Use Python 3.14 with `requirements/dev.txt` installed and a local Docker socket with the CI images `postgres:14` and `redis:6.2` already available. Every invocation starts its own loopback services from empty tempfs storage, clears inherited environment settings for the app and migration processes, and stops its own containers at exit.

```bash
bash scripts/qa_first_five_reactions.sh
bash scripts/qa_first_five_reactions.sh

# Show each known defect as a regular test failure.
bash scripts/qa_first_five_reactions.sh tests/tgbot/test_first_five_reactions.py \
  -k duplicate_onboarding_picker --runxfail
bash scripts/qa_first_five_reactions.sh tests/tgbot/test_first_five_reactions.py \
  -k duplicate_reaction_does_not_increment --runxfail

bash scripts/qa_first_five_reactions.sh \
  tests/tgbot/test_start.py tests/tgbot/test_onboarding_flow.py \
  tests/tgbot/test_onboarding_language.py tests/tgbot/test_reaction_handler.py \
  tests/tgbot/test_next_message.py tests/tgbot/test_meme_reaction_keyboard.py \
  tests/recommendations/test_reaction_service.py
```

Set `QA_PYTHON` to a virtual environment's Python path when it is outside the active shell path. The runner requires a checkout without `.env`, checks the actual Alembic engine target, verifies a blank application schema before collection and checks that the session downgrade returns it to base. The journey fixture verifies migration head `a7c3e9f1b5d2` and an empty catalog, Telegram user table and reaction table before seeding. The existing migrations seed two role accounts in the local schema without importing Telegram users.

## Verification

| Run | Loopback PostgreSQL / Redis ports | Result |
| --- | --- | --- |
| Baseline A | 32801 / 32804 | 2 journeys passed, 2 expected defect reproductions, downgrade verified |
| Baseline B | 32802 / 32803 | 2 journeys passed, 2 expected defect reproductions, downgrade verified |
| Adjacent onboarding, delivery and reaction tests | 32793 / 32795 | 45 passed, downgrade verified |

The step traces matched across the two baseline runs. Each run handled 70 in-process Bot API requests across the four cases, with zero Telegram network requests or attempted transport escapes. The adjacent run emitted a Redis client finalizer warning at interpreter exit and returned zero. Ruff lint and formatting, shell syntax, the public redaction audit and whitespace checks passed.

Pilot harness failures came from assuming the migrated database had no seeded accounts, using a fake transport that expected integer chat IDs, and leaving synthetic data that older downgrades cannot represent. The final harness accounts for the built-in role seeds, handles numeric string chat IDs, uses 32-bit fixture user IDs and releases only its synthetic catalog and user language rows before downgrade. These were fixture issues separate from the two callback defects.

## Limits and handoff

Live Telegram, production inventory and deployment settings, real user behavior, and experiment lift were outside this measurement. The harness checks delivery and state transitions with an eligible synthetic catalog and fake transport. It does not exercise Telegram's real media validation or client rendering.

The finish-line hook reported the three task files and the existing experiment-readout branch. The task files are intentionally uncommitted under the setup override. The coordinator owns review and the local commit. The experiment-readout task retains ownership of its ref.
