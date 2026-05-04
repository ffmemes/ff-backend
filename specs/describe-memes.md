# Describe Memes

Vision OCR for memes. The flow extracts image text, language, and a short English description into `meme.ocr_result` for duplicate detection, upload moderation, search, stats, and product experiments.

## Business Goal

Use OpenRouter's free vision tier to process hundreds of memes/day without paid spend. The current target is **864 scheduled memes/day**, capped by a **900 OpenRouter-attempt/day Redis guard** so upload-time OCR and fallback attempts do not cross the 1,000/day free-model limit.

## Source Of Truth

| Topic | Link |
| --- | --- |
| Flow and OpenRouter client | [`src/flows/storage/describe_memes.py`](../src/flows/storage/describe_memes.py) |
| Prefect schedule | [`scripts/serve_flows.py`](../scripts/serve_flows.py) |
| Upload-time OCR callsite | [`src/tgbot/handlers/upload/moderation.py`](../src/tgbot/handlers/upload/moderation.py) |
| Dedup usage | [`src/storage/service.py`](../src/storage/service.py) |
| Parsing/storage context | [`specs/parsing-etl.md`](parsing-etl.md) |

## Production Settings

- Schedule: every 30 minutes, `batch_size=18` (`15,45 * * * *` London time).
- Daily target: `48 * 18 = 864` scheduled memes/day.
- Local free-tier budget: `OPENROUTER_FREE_DAILY_REQUEST_BUDGET = 900`.
- Redis counter: `openrouter:free_requests:YYYY-MM-DD` (UTC, 48h TTL).
- Free-model RPM: stay below 20 rpm; code spaces attempts by at least 4 seconds.
- Circuit breaker: Prefect pauses the deployment after repeated failures.

## Free-Only Contract

`VISION_MODELS` must contain only OpenRouter model IDs ending in `:free`.

The client enforces this twice:

- import-time validation via `_validate_free_vision_models`;
- per-request validation before `POST /chat/completions`.

If Redis quota accounting fails, the client fails closed and does not call OpenRouter.

## Model Chain

Current production chain:

```python
[
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
]
```

Do not add paid fallbacks. A paid fallback can spend the account below zero, after which OpenRouter returns 402 for all models, including free models.

## Monitoring

- Fresh OCR: `ocr_result->>'calculated_at'`, not `meme.created_at`.
- Healthy batch: up to 18 described, low failures.
- Daily attempts: inspect Redis key `openrouter:free_requests:YYYY-MM-DD`.
- Resume paused deployment:

```bash
prefect deployment resume "Describe Memes (OpenRouter Vision)/Describe Memes (OpenRouter)"
```

Before resuming, check recent flow logs and confirm the root cause is fixed.
