# Describe Memes

Vision OCR for memes. The flow extracts image text, language, and a short English description into `meme.ocr_result` for duplicate detection, upload moderation, search, stats, and product experiments.

## Business Goal

Use OpenRouter's free vision tier to process memes every day with **zero paid spend**. Throughput is useful, but consistency is the main goal: accept 429s/timeouts/invalid model output as normal free-tier backpressure, try another free model when possible, then retry later.

Current target is capped by an atomic shared Redis guard covering scheduled and
upload-time OCR together. Its ceiling is the sum of documented daily budgets
for distinct verified accounts: 900 attempts for each account with $10+ in
lifetime credits, or 45 below that threshold. This permits capacity from a
separate account without promising that platform capacity or rate limits double.

## Source Of Truth

| Topic | Link |
| --- | --- |
| Flow and OpenRouter client | [`src/flows/storage/describe_memes.py`](../src/flows/storage/describe_memes.py) |
| Prefect schedule | [`scripts/serve_flows.py`](../scripts/serve_flows.py) |
| Upload-time OCR callsite | [`src/tgbot/handlers/upload/moderation.py`](../src/tgbot/handlers/upload/moderation.py) |
| Dedup usage | [`src/storage/service.py`](../src/storage/service.py) |
| Parsing/storage context | [`specs/parsing-etl.md`](parsing-etl.md) |

## Production Settings

- Schedule: every 15 minutes, `batch_size=18` (`*/15 * * * *` London time).
- Daily target: `96 * 18 = 1,728` scheduled memes/day when two independently
  verified 900-attempt accounts are healthy; one account stops at its own guard.
- Queue selection weights are 5:2:1:1 across the repository's priority tiers.
- Shared Redis counter: `openrouter:free_requests:YYYY-MM-DD` (UTC, 48h TTL).
  This existing key is retained during rollout so the current day's protection is
  never reset; its per-request ceiling is the aggregate distinct-account budget.
  Per-account counters use
  `openrouter:free_requests:{account_hash}:YYYY-MM-DD`.
- Free-model RPM: stay below 20 rpm; code spaces meme attempts by at least 10 seconds.
- Circuit breaker: Prefect pauses the deployment after repeated failures.

## Free-Only Contract

`VISION_MODELS` must contain only OpenRouter model IDs ending in `:free`.

The client enforces this twice:

- import-time validation via `_validate_free_vision_models`;
- per-request validation before `POST /chat/completions`.

If Redis quota accounting fails, the client fails closed and does not call OpenRouter.

Set `OPENROUTER_API_KEY_SECONDARY` only for an independent account. Identical
primary and secondary values are deduplicated. Calls round-robin their preferred
account, but platform 429s set a shared model cooldown and are never treated as
a cue to evade a platform rate limit with another key.

Before each scheduled batch, the flow checks `GET /api/v1/key` and
`GET /api/v1/credits` for every configured key. A key failing authentication or
returning HTTP 402 is skipped while another usable key can continue. A
`limit=0, limit_remaining=0` key remains eligible for strictly `:free` calls;
production verification confirms this is a zero paid-spend cap, not a disabled
free-model key. The `/credits` `total_credits` threshold determines the local
per-account guard: 45 attempts below $10 lifetime credits and 900 at $10+.
If credits metadata is unavailable, the client safely uses 45. When OpenRouter
supplies `creator_user_id`, multiple keys from the same account are counted only
once. Without that identifier, only identical key values can be deduplicated.

When no configured key, usable key, or pending meme exists, the flow emits an
`ff.describe_memes.no_work` event with a reason and returns successfully. This
makes non-actionable completed Prefect runs observable without invoking the
failure notification hook.

## Model Chain

Current production chain:

```python
[
    "inclusionai/ling-3.0-flash-vl:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-26b-a4b-it:free",
    "dots-studio/dots-3-note-preview:free",
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

- A 429 on one model records `rate_limited`, sets an account-specific cooldown
  plus `openrouter:free_model_cooldown:global:{model_id}`, and tries the next
  free model. The shared cooldown prevents immediate key rotation around a
  platform-wide rate limit.
- Timeouts/request errors/HTTP 5xx/bad or invalid model responses also set short model cooldowns, because those are usually provider-window failures rather than meme-specific failures.
- If every usable model is cooled down/rate-limited, the batch stops without marking the meme failed.
- The next 15-minute scheduled run samples again. This intentionally discovers better low-contention windows over time.

## Monitoring

- Fresh OCR: `ocr_result->>'calculated_at'`, not `meme.created_at`.
- Healthy batch: up to 18 described, low failures. 429-only batches are acceptable.
- Daily attempts: inspect Redis key `openrouter:free_requests:YYYY-MM-DD`.
- Hourly model stats: inspect Redis hashes `openrouter:free_ocr_stats:{account_hash}:YYYY-MM-DD:HH` (UTC, 14d TTL). Fields are `{model_id}:{outcome}`, e.g. `...:success`, `...:rate_limited`, `...:timeout`.
- OpenRouter key health: check flow logs for `OpenRouter key health ok` or
  an account-specific health failure. A zero paid-spend limit is expected for
  free-only OCR; investigate actual HTTP 402 responses instead.
- Time-window tuning: compare hourly `success / attempt` by UTC hour, then shift the Prefect schedule or batch size if nights are consistently better.
- Resume paused deployment:

```bash
prefect deployment resume "Describe Memes (OpenRouter Vision)/Describe Memes (OpenRouter)"
```

Before resuming, check recent flow logs and confirm the root cause is fixed.
