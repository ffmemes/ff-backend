# Describe Memes

Vision OCR for memes. The flow extracts image text, language, and a short English description into `meme.ocr_result` for duplicate detection, upload moderation, search, stats, and product experiments.

`ocr_result.language` is the meme text language (ISO 639-1) or `"none"` when
the image has no text. Rows described before 2026-10-30 lack the key; read
`raw_result.language` as a fallback. `meme.language_code` is only updated for
known languages, never from a text-free image.

Since 2026-10-31, `ocr_result` also stores three content tags for the crosspost
experiment (`experiments/active/2026-10-31-crosspost-content-tags.md`):
- `format`: one of single_caption, multi_panel, tweet_screenshot, chat_screenshot,
  photo_no_text, drawing_comic, other;
- `relatable`: bool;
- `politics_news`: bool.

Missing or invalid values are stored as null. Older rows do not have these keys.

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
  Memes with status `ok` **and** `published` are eligible (crossposting sets
  `published`); the backlog tier serves `published` memes first, then the oldest
  pending image. Index: `ix_meme_describe_pending_published_created_at`.
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

Current production chain (re-benchmarked 2026-10-30):

```python
[
    "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]
```

Benchmark: every free image-input model from `GET /api/v1/models`
(`pricing.prompt == pricing.completion == 0`), 10 real memes (5 Russian,
4 English, 1 text-free), production prompt and payload. Accuracy is
normalized character similarity to hand-checked text, watermark excluded.

| Model | HTTP 200 | Strict JSON | OCR sim (ru / en) | Language | p50 latency |
| --- | --- | --- | --- | --- | --- |
| dots-3-note-preview | 10/10 | 10/10 | 0.99 / 0.98 | 9/10 | 4.5s |
| nemotron-3.5-super-vl | 10/10 | 9/10 | 0.90 / 0.95 | 8/10 | 2.5s |
| nemotron-3-nano-omni | 10/10 | 8/10 | 0.98 / 1.00 | 7/10 | 2.9s |
| gemma-4-31b-it / 26b-a4b-it | 0/10 (429) | - | - | - | - |
| inkling / inkling-small | 0/10 (403) | - | - | - | - |

dots is first: best accuracy, keeps intentional misspellings, always valid JSON.
super-vl is the reliable fast fallback, though it "corrects" misspelled
Cyrillic text. nano-omni is accurate but often emits malformed JSON (each bad
response burns a request). Gemma stays last for off-peak windows.

Excluded: `inclusionai/ling-3.0-flash-vl:free` (HTTP 404 since 2026-09-24;
it was first in the chain and wasted ~45% of daily attempts),
`thinkingmachines/inkling*:free` (403, "only available on agentic harnesses"),
`nvidia/nemotron-3.5-content-safety:free` (guardrail classifier), Gemma 3 and
`nex-agi/nex-n2-pro:free` (no longer listed).

Do not add paid fallbacks. A paid fallback can spend the account below zero, after which OpenRouter returns 402 for all models, including free models.

429 handling:

- A 429 on one model records `rate_limited`, sets an account-specific cooldown
  plus `openrouter:free_model_cooldown:global:{model_id}`, and tries the next
  free model. The shared cooldown prevents immediate key rotation around a
  platform-wide rate limit.
- HTTP 403 (access denied) and 404 (model removed) set a 6-hour model cooldown.
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
