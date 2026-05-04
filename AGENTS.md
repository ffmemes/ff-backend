# ff-backend Agent Notes

## Automated parsing & Prefect storage flows
- The Prefect flows in [`src/flows/storage/memes.py`](src/flows/storage/memes.py) orchestrate ingestion from all automated sources:
  - `tg_meme_pipeline`, `vk_meme_pipeline`, and `ig_meme_pipeline` ETL raw posts, download media, watermark images, push them into the storage bot chat, and hand off to `final_meme_pipeline`.
  - `final_meme_pipeline` performs duplicate checks, normalizes captions, and promotes records by calling `update_meme_status_of_ready_memes`.
- Legacy Modal OCR has been removed. The active image analysis system is **Describe Memes** (see below).

## Manual upload & moderation workflow
- User uploads arrive via the upload handler, then `uploaded_meme_auto_review` in [`src/tgbot/handlers/upload/moderation.py`](src/tgbot/handlers/upload/moderation.py) downloads the submission, watermarks it, and sends it to the storage chat.
- After preprocessing, `send_uploaded_meme_to_manual_review` posts the media into the moderator chat (`settings.UPLOADED_MEMES_REVIEW_CHAT_ID`) with approve/reject buttons. Moderators interact in that chat to complete review.
- `handle_uploaded_meme_review_button` enforces moderator-only review, updates meme status (`OK` or `REJECTED`), handles payouts, and sends outcome notifications back to the uploader. Approved memes automatically receive "like" reactions from both the uploader and reviewer to seed downstream stats.

## Recommendation queue generation
- Recommendation queues are stored in Redis; see [`src/recommendations/meme_queue.py`](src/recommendations/meme_queue.py) for helper utilities.
  - `check_queue` and `generate_recommendations` refill a user's queue when it drops to two items, blending candidate sources via the `CandidatesRetriever` and `blend` helper.
  - Cold-start users (<30 memes sent) fall back to `best_uploaded_memes`, `fast_dopamine`, and curated source lists; more engaged users use weighted blends that may include long-tail boosters.
  - Accepted recommendations are pushed to Redis with `add_memes_to_queue_by_key`; consumption pops entries one-by-one.
- User reactions are persisted through `create_user_meme_reaction` / `update_user_meme_reaction` (see [`src/recommendations/service.py`](src/recommendations/service.py)). These records drive `calculate_meme_reactions_stats` and related counters, which in turn update meme statuses and recommendation eligibility.

## Operational notes
- Manual review happens entirely inside the designated Telegram moderator chat. Keep communications and escalations there for traceability.
- Weekly maintenance (Prefect flow health checks, data hygiene jobs, etc.) runs through Prefect deployment definitions. Use Prefect CLI to trigger flows during scheduled operations.

## Describe Memes (OpenRouter Vision)

The `describe_memes` flow (`src/flows/storage/describe_memes.py`) uses **FREE OpenRouter vision models only** to extract text and descriptions from meme images.

- **Schedule**: current deployment runs every 30 minutes, 18 memes/batch (about 864/day)
- **Priority**: processes recent user uploads first, then most-liked memes (`nlikes DESC`)
- **Storage**: writes to `meme.ocr_result` JSONB with `calculated_at` timestamp
- **Monitoring**: use `ocr_result->>'calculated_at'` to check recency, NOT `meme.created_at`
- **Circuit breaker**: auto-pauses after 3 failures in 1 hour
- **Quota guard**: Redis stops OpenRouter calls after 900 free-model attempts/day (UTC)

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

## Key settings & environment toggles
- Redis, Postgres, and Telegram configuration live in [`src/config.py`](src/config.py).
- `OPENROUTER_API_KEY` — required for describe_memes. Balance must stay >= $0.
