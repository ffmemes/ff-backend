# ff-backend Agent Notes

## Automated parsing & Prefect storage flows
- The Prefect flows in [`src/flows/storage/memes.py`](src/flows/storage/memes.py) orchestrate ingestion from all automated sources:
  - `tg_meme_pipeline`, `vk_meme_pipeline`, and `ig_meme_pipeline` ETL raw posts collected from Telegram, VK, and Instagram tables, respectively. They download media, watermark images, push them into the storage bot chat, and (when enabled) trigger OCR before handing off to `final_meme_pipeline`.
  - `ocr_uploaded_memes` periodically re-downloads originals (either from cloud storage URLs or the uploader's Telegram file) to perform OCR on backlogged memes and then routes them into the final normalization step.
  - `final_meme_pipeline` performs duplicate checks via OCR text, normalizes captions, and promotes records by calling `update_meme_status_of_ready_memes`.
- OCR is globally toggled through `settings.OCR_ENABLED` (see [`src/config.py`](src/config.py)). Until the OCR service is restored, flows log that they are skipping OCR; flip the flag back to `True` once the Modal OCR endpoint is available again.

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
- OCR is optional while the external service is offline; leave `OCR_ENABLED=False` to avoid wasting quota. Once Modal OCR is healthy, update the environment variable (or `.env`) and redeploy.
- Weekly maintenance (Prefect flow health checks, data hygiene jobs, etc.) runs through the Prefect deployment definitions under `flow_deployments/`. Use Docker Compose (`docker-compose.yml`) plus Prefect CLI to register or trigger flows during scheduled operations.
- For ad-hoc debugging, remember that Prefect logs surface in the worker containers defined in the Compose stack; keep an eye on OCR warnings for signal that the toggle needs to flip back on.

## Key settings & environment toggles
- Redis, Postgres, and Telegram configuration live in [`src/config.py`](src/config.py). Update `.env` or deployment secrets with:
  - `DATABASE_URL` / pooling parameters for Postgres.
  - `REDIS_URL` and connection limits for the queue + cache layer.
  - `TELEGRAM_BOT_TOKEN`, `MEME_STORAGE_TELEGRAM_CHAT_ID`, and `UPLOADED_MEMES_REVIEW_CHAT_ID` for bot routing.
- When OCR support returns, enable it by setting `OCR_ENABLED=true` (environment variable) before restarting Prefect workers and bot services.
