# Describe Memes

Vision OCR for memes. The flow extracts image text, language, and a short English description into `meme.ocr_result` for duplicate detection, upload moderation, search, stats, and product experiments.

## Business Goal

Use OpenRouter's free vision tier to process memes every day with **zero paid spend**. Throughput is useful, but consistency is the main goal: accept 429s/timeouts/invalid model output as normal free-tier backpressure, try another free model when possible, then retry later.

Current target: **864 scheduled memes/day**, capped by a **900 OpenRouter-attempt/day Redis guard** so upload-time OCR and fallback attempts do not cross the 1,000/day free-model limit.

## Source Of Truth

| Topic | Link |
| --- | --- |
| Flow and OpenRouter client | [`src/flows/storage/describe_memes.py`](../src/flows/storage/describe_memes.py) |
| Prefect schedule | [`scripts/serve_flows.py`](../scripts/serve_flows.py) |
| Upload-time OCR callsite | [`src/tgbot/handlers/upload/moderation.py`](../src/tgbot/handlers/upload/moderation.py) |
| Dedup usage | [`src/storage/service.py`](../src/storage/service.py) |
| Parsing/storage context | [`specs/parsing-etl.md`](parsing-etl.md) |

## Production Settings

- Schedule: every 15 minutes, `batch_size=9` (`*/15 * * * *` London time).
- Daily target: `96 * 9 = 864` scheduled memes/day.
- Local free-tier budget: `OPENROUTER_FREE_DAILY_REQUEST_BUDGET = 900`.
- Redis counter: `openrouter:free_requests:YYYY-MM-DD` (UTC, 48h TTL).
- Free-model RPM: stay below 20 rpm; code spaces meme attempts by at least 10 seconds.
- Circuit breaker: Prefect pauses the deployment after repeated failures.

## Free-Only Contract

`VISION_MODELS` must contain only OpenRouter model IDs ending in `:free`.

The client enforces this twice:

- import-time validation via `_validate_free_vision_models`;
- per-request validation before `POST /chat/completions`.

If Redis quota accounting fails, the client fails closed and does not call OpenRouter.

Before each scheduled batch, the flow also checks `GET /api/v1/key`. If
OpenRouter reports an invalid key or a configured key limit with
`limit_remaining <= 0`, the batch stops before selecting memes. This does not
spend model quota and makes account/key exhaustion visible in flow logs.

## Model Chain

Current production chain:

```python
[
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-26b-a4b-it:free",
]
```

Gemma 3 free vision model IDs are intentionally excluded: they are no longer
listed by OpenRouter and create avoidable failed attempts under the daily free
quota.

`nvidia/nemotron-3.5-content-safety:free` is intentionally excluded because it
is a guardrail classifier, not a general OCR/description model.

`nex-agi/nex-n2-pro:free` was removed after it disappeared from the OpenRouter
free vision model list, creating avoidable failed attempts.

Do not add paid fallbacks. A paid fallback can spend the account below zero, after which OpenRouter returns 402 for all models, including free models.

429 handling:

- A 429 on one model records `rate_limited`, sets `openrouter:free_model_cooldown:{model_id}`, and tries the next free model.
- Timeouts/request errors/HTTP 5xx/bad or invalid model responses also set short model cooldowns, because those are usually provider-window failures rather than meme-specific failures.
- If every usable model is cooled down/rate-limited, the batch stops without marking the meme failed.
- The next 15-minute scheduled run samples again. This intentionally discovers better low-contention windows over time.

## Monitoring

- Fresh OCR: `ocr_result->>'calculated_at'`, not `meme.created_at`.
- Healthy batch: up to 9 described, low failures. 429-only batches are acceptable.
- Daily attempts: inspect Redis key `openrouter:free_requests:YYYY-MM-DD`.
- Hourly model stats: inspect Redis hashes `openrouter:free_ocr_stats:YYYY-MM-DD:HH` (UTC, 14d TTL). Fields are `{model_id}:{outcome}`, e.g. `...:success`, `...:rate_limited`, `...:timeout`.
- OpenRouter key health: check flow logs for `OpenRouter key health ok` or
  `OpenRouter key limit exhausted`. A limit-exhausted key requires raising or
  resetting the key credit limit, or rotating `OPENROUTER_API_KEY`.
- Time-window tuning: compare hourly `success / attempt` by UTC hour, then shift the Prefect schedule or batch size if nights are consistently better.
- Resume paused deployment:

```bash
prefect deployment resume "Describe Memes (OpenRouter Vision)/Describe Memes (OpenRouter)"
```

Before resuming, check recent flow logs and confirm the root cause is fixed.
