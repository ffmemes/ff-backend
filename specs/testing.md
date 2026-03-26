# Testing Strategy

## Current State

- 8 test files, ~1,592 LOC
- ~5-7% coverage overall
- Critical hot path (reaction -> queue -> send): **0% coverage**
- All tests are integration tests requiring PostgreSQL

### What's Tested

| Area | Tests | What They Cover |
|------|-------|-----------------|
| blender.py | 5 tests | Multiple engines, zero-weight, fixed positions, statistical distribution |
| meme_queue.py | 3 tests | generate_recommendations() with mocks for maturity stages |
| candidates/selected_sources | 1 test | get_selected_sources() integration |
| candidates/lr_smoothed | ? | get_lr_smoothed() integration |
| stats/meme | 1 test | calculate_meme_reactions_stats() lr_smoothed calculation |
| redis | 1 test | add_memes_to_queue_by_key() |
| forwarded_meme utils | 6 tests | extract_meme_id, format_age, was_forwarded_from_bot |

### What's NOT Tested (Critical Gaps)

1. **Reaction flow**: handle_reaction(), update_user_meme_reaction(), next_message() — **0%**
2. **All 9 recommendation engines**: SQL queries untested — **0%**
3. **Meme delivery**: send_new_message, edit_last_message — **0%**
4. **Redis queue ops**: pop, clear, length check — **7%**
5. **Stats pipeline**: user_stats, source_stats, user_source_stats — **9%**
6. **Entire ETL pipeline**: parsers, watermark, upload, ad filter — **0%**
7. **Onboarding**: /start, save_user_data — **0%**
8. **All handler functions**: 130+ untested

## Testing Priority Order

### Phase 1: Freeze the hot path (BEFORE any code changes)

**1a. Engine contract tests** — parametrized test across all engines:
- Returns only `meme.status = 'ok'`
- Matches user_language
- Excludes already-seen memes (R.meme_id IS NULL)
- Has correct `recommended_by` field
- Respects `exclude_meme_ids`

**1b. Reaction flow tests** (mock Telegram, real DB):
- Reaction persists correctly
- Double-tap doesn't trigger double next-meme
- reaction_is_new = False prevents next_message()
- If next_message() fails, reaction is still saved

**1c. Queue correctness tests**:
- No seen memes enter Redis queue
- Refill triggers at threshold <= 2
- Cold start path works (nmemes_sent < 30)
- Moderator path works (75% low_sent_pool)

### Phase 2: Stats and personalization

**2a. Stats computation tests**:
- lr_smoothed produces expected values from seeded reactions
- user_meme_source_stats produces expected affinity scores
- Verify incremental recompute doesn't corrupt data

**2b. Blender integration tests** (not just unit tests):
- End-to-end: real candidates -> blend -> verify queue contents
- Per-user seed produces different orderings
- Weight changes produce expected traffic shift

### Phase 3: ETL and parsing

**3a. Dedup tests**:
- find_meme_duplicate() with matching OCR text
- Perceptual hash dedup (after implementation)

**3b. ETL integration tests**:
- Raw TG post -> processed meme with correct fields
- Ad filter catches known ad patterns
- Single-media filter works correctly

### Phase 4: E2E smoke tests (Telethon)

**Only 2-3 tests, run nightly, not on every PR:**
- /start: user gets first meme with buttons
- Tap Like: next meme arrives within 3s
- Upload: user can submit a meme

**Why minimal e2e**: Core risk is SQL/queue correctness, not Telegram transport. Telethon tests are slow, flaky, and expensive to maintain. 90% of safety comes from integration tests.

## Test Infrastructure Improvements

Current `conftest.py` runs full alembic upgrade/downgrade per session. Needs:

1. **Factory helpers** — Stop hand-rolling INSERT statements in every test. Create `create_test_user()`, `create_test_meme()`, `create_test_reaction()` etc.
2. **Per-test DB cleanup** — Current tests share DB state. Add transaction rollback or truncation per test.
3. **Mock Telegram bot** — Need a fixture that captures bot.send_photo/send_video calls without hitting Telegram API.
4. **Redis test isolation** — Use separate Redis DB or flush between tests.

## Test Directory Structure

```
tests/
├── conftest.py                     # Existing: migrations, new: factories
├── factories.py                    # NEW: test data creation helpers
├── recommendations/
│   ├── test_blender.py             # Existing: unit tests
│   ├── test_meme_queue.py          # Existing: mock-based tests
│   ├── test_lr_smoothed.py         # Existing
│   ├── test_selected_sources.py    # Existing
│   ├── test_engine_contracts.py    # NEW: parametrized across all engines
│   └── test_queue_correctness.py   # NEW: integration with Redis
├── tgbot/
│   ├── test_forwarded_meme_utils.py  # Existing
│   ├── test_reaction_flow.py         # NEW: hot path tests
│   └── test_onboarding.py            # NEW: /start flow
├── stats/
│   ├── test_meme.py                # Existing
│   ├── test_user_stats.py          # NEW
│   └── test_source_stats.py        # NEW
├── storage/
│   ├── test_dedup.py               # NEW
│   ├── test_etl.py                 # NEW
│   └── test_ad_filter.py           # NEW
├── test_redis.py                   # Existing
└── e2e/
    └── test_smoke.py               # NEW: Telethon smoke tests (nightly)
```
