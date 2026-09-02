# ff-backend Agent Notes

## Automated parsing & Prefect storage flows
- The Prefect flows in [`src/flows/storage/memes.py`](src/flows/storage/memes.py) orchestrate ingestion from automated sources:
  - `tg_meme_pipeline` and `vk_meme_pipeline` ETL raw posts, download media, watermark images, push them into the storage bot chat, and hand off to `final_meme_pipeline`.
  - `final_meme_pipeline` performs duplicate checks, normalizes captions, and promotes records by calling `update_meme_status_of_ready_memes`.
  - **Instagram pipeline is removed.** `meme_raw_ig` may still exist for historical rows; do not reintroduce `ig_meme_pipeline` without a product decision.
- Legacy Modal OCR has been removed. The active image analysis system is **Describe Memes** (see below).

## Manual upload & moderation workflow
- User uploads arrive via the upload handler, then `uploaded_meme_auto_review` in [`src/tgbot/handlers/upload/moderation.py`](src/tgbot/handlers/upload/moderation.py) downloads the submission, watermarks it, and sends it to the storage chat.
- After preprocessing, `send_uploaded_meme_to_manual_review` posts the media into the upload review chat (`settings.UPLOADED_MEMES_REVIEW_CHAT_ID`) with approve/reject buttons. People in that chat interact with the buttons to complete review.
- `handle_uploaded_meme_review_button` accepts review callbacks only from the upload review chat, updates meme status (`OK` or `REJECTED`), handles payouts, and sends outcome notifications back to the uploader. Approved memes automatically receive "like" reactions from both the uploader and reviewer to seed downstream stats.

## Moderator source scouting vocabulary
- The canonical domain vocabulary is in [`CONTEXT.md`](CONTEXT.md), in Russian. Use those terms when discussing moderator/community/source flows.
- Keep the moderator community chat (`TELEGRAM_MODERATOR_CHAT_ID`) separate from the upload review chat (`UPLOADED_MEMES_REVIEW_CHAT_ID`).
- The daily source-voting design is in [`specs/moderator-community-loop.md`](specs/moderator-community-loop.md). It uses "подготовленный источник": a `meme_source` parked in `in_moderation` with cached raw Telegram posts, not visible to users until the source vote passes.
- When implementing prepared sources, the Telegram ETL must only transform raw posts for `meme_source.status = 'parsing_enabled'`; this guard prevents pre-parsed candidates from leaking into recommendations before a successful vote.

## Recommendation queue generation
- Recommendation queues are stored in Redis; see [`src/recommendations/meme_queue.py`](src/recommendations/meme_queue.py).
  - `check_queue` refills when queue length drops to **≤ 8**; `generate_recommendations` runs `RecommendationBatchPipeline` (maturity plan from [`src/feed_turn/planner.py`](src/feed_turn/planner.py) + engines + blend).
  - Cold start is **3-phase** (`cold_start_explore` → `cold_start_adapt` → blend). Mature default weights live in `feed_turn.planner` (`MATURE_BLEND_WEIGHTS`); blender experiments must import that map for control.
  - Accepted recommendations are pushed to Redis with `add_memes_to_queue_by_key`; consumption pops entries one-by-one.
- User reactions are persisted through `create_user_meme_reaction` / `update_user_meme_reaction` (see [`src/recommendations/service.py`](src/recommendations/service.py)). These records drive stats aggregation and recommendation eligibility.
- Share attribution: deep links `s_{user_id}_{meme_id}` in `user_deep_link_log` — see `CONTEXT.md` **Share Attribution**. Growth thesis and measurement plan: [`docs/growth/virality-loop.md`](docs/growth/virality-loop.md).

## Operational notes
- Manual upload review happens entirely inside the designated Telegram upload review chat. Keep communications and escalations there for traceability.
- Weekly maintenance (Prefect flow health checks, data hygiene jobs, etc.) runs through Prefect deployment definitions. Use Prefect CLI to trigger flows during scheduled operations.
- Architecture decisions live in [`docs/adr/`](docs/adr/).
- Telegram-facing DB helpers are split under [`src/tgbot/repo/`](src/tgbot/repo/); [`src/tgbot/service.py`](src/tgbot/service.py) re-exports them for compatibility.

## Describe Memes (OpenRouter Vision)

The `describe_memes` flow (`src/flows/storage/describe_memes.py`) uses **FREE OpenRouter vision models only** to extract text and descriptions from meme images.

- **Schedule**: current deployment runs every 15 minutes, 9 memes/batch (about 864/day)
- **Priority**: processes recent user uploads first, then most-liked memes (`nlikes DESC`)
- **Storage**: writes to `meme.ocr_result` JSONB with `calculated_at` timestamp
- **Monitoring**: use `ocr_result->>'calculated_at'` to check recency, NOT `meme.created_at`
- **Circuit breaker**: auto-pauses after 3 failures in 1 hour
- **Quota guard**: Redis stops OpenRouter calls after 900 free-model attempts/day (UTC)
- **Backpressure strategy**: treat free-tier 429s/timeouts/invalid model output as normal; cool down that model in Redis and retry in later scheduled runs

### OpenRouter constraints (CRITICAL)

- **NEVER add paid models** to `VISION_MODELS` list — balance below $0 blocks ALL models (402)
- Need $10+ lifetime purchases for 1,000 req/day (otherwise only 50/day)
- Free model rate limit: 20 rpm
- `describe_memes` refuses model IDs that do not end in `:free`
- See [specs/describe-memes.md](specs/describe-memes.md) for full constraints

### Handling circuit breaker pauses

```bash
prefect deployment resume "Describe Memes (OpenRouter Vision)/Describe Memes (OpenRouter)"
```

Before resuming, verify the root cause is fixed (check recent flow run logs).

## Admin meme inspect (agents)

HTTP API for compact meme cards + media download (Telegram `file_id` needs the
production bot token). Auth: `ADMIN_API_TOKEN`.

- Docs: [`docs/admin-meme-inspect.md`](docs/admin-meme-inspect.md)
- `GET /admin/memes/{id}` — status, source, stats, OCR summary
- `GET /admin/memes/{id}/media` — raw image/video bytes
- OCR health SQL: [`docs/analyst/describe-memes-health.sql`](docs/analyst/describe-memes-health.sql)

## Key settings & environment toggles
- Redis, Postgres, and Telegram configuration live in [`src/config.py`](src/config.py).
- `OPENROUTER_API_KEY` — required for describe_memes. Balance must stay >= $0.
- `ADMIN_API_TOKEN` — shared secret for `/admin/*` inspect endpoints (optional; 503 if unset).

## Public repo hygiene
- This repository is public. Follow [`docs/public-repo-rule.md`](docs/public-repo-rule.md).
- Never commit production hostnames/IPs, Coolify app UUIDs, SSH recipes that grant access, or secret values. Use env var **names** only.
