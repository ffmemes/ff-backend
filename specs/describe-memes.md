# Describe Memes (Vision OCR)

## What It Does

Background Prefect flow that uses vision LLMs to analyze meme images. Populates `meme.ocr_result` JSONB with description, OCR text, language, model used, and timestamp.

Processes most-liked memes first (by `meme_stats.nlikes DESC`). Runs every 60 min, ~20 memes per batch.

## OpenRouter Free Tier Constraints

**Provider**: OpenRouter API (`openrouter.ai/api/v1`)

### Rate Limits (as of 2026-04)

| Account tier | RPM | Requests/day |
|-------------|-----|-------------|
| No purchases ever | 20 | **50** |
| >= $10 purchased (lifetime) | 20 | **1,000** |

- The $10 threshold is **lifetime total purchases**, not current balance.
- Once crossed, the 1,000/day limit is permanent even if balance drops.
- **If balance goes below $0, even free models return 402 errors.**
- Monitor balance at: https://openrouter.ai/settings/credits

### NEVER Add Paid Models

**Rule**: The `VISION_MODELS` list must contain ONLY `:free` models. No exceptions.

Why: If free models are rate-limited and the system falls through to paid models, each request costs money. If balance drops below $0, ALL models (including free) get blocked with 402. This creates a death spiral:

1. Free models hit daily rate limit
2. Paid fallbacks drain balance
3. Balance goes below $0
4. ALL models blocked → circuit breaker fires → describe_memes stops

This happened in April 2026 when AI agents added paid fallbacks during unsupervised operation.

## Model Chain (production)

```python
VISION_MODELS = [
    "google/gemma-4-31b-it:free",     # 262k context, primary
    "google/gemma-4-26b-a4b-it:free", # 262k context, MoE variant
]
```

Falls through sequentially on 403 (access denied), timeout, or bad response.
429 (rate limit) returns immediately — the 20 rpm limit is global across all free models, so trying the next model would also 429.

**Removed models** (Apr 2026): All `gemma-3-*:free` models delisted from OpenRouter ~2026-04-15, causing 48h+ outage (FFM-543). `gemma-4-*:free` models restored after earlier 403 issues (FFM-520).

### Available Free Vision Models (as of 2026-04-17)

| Model | Context | Notes |
|-------|---------|-------|
| `google/gemma-4-31b-it:free` | 262K | Primary, restored after earlier 403 issues |
| `google/gemma-4-26b-a4b-it:free` | 262K | MoE variant fallback |
| `google/gemma-3-27b-it:free` | 131K | **Delisted** ~2026-04-15 |
| `google/gemma-3-12b-it:free` | 32K | **Delisted** ~2026-04-15 |
| `google/gemma-3-4b-it:free` | 32K | **Delisted** ~2026-04-15 |
| `nvidia/nemotron-nano-12b-v2-vl:free` | 128K | **Removed** — returns 504s and invalid JSON/empty content |

Check current availability: `curl https://openrouter.ai/api/v1/models | jq '.data[] | select(.id | endswith(":free")) | select(.architecture.modality | contains("image")) | .id'`

## Output Schema

Stored in `meme.ocr_result` JSONB:

```json
{
  "model": "google/gemma-3-27b-it:free",
  "calculated_at": "2026-04-11T12:00:00+00:00",
  "raw_result": {
    "ocr_text": "когда узнал что...",
    "description": "A surprised cat looking at a phone screen...",
    "language": "ru"
  },
  "description": "A surprised cat looking at a phone screen...",
  "text": "когда узнал что...",
  "describe_failures": 0
}
```

- `calculated_at` is the monitoring field (NOT `meme.created_at`)
- `describe_failures` >= 3 → meme skipped permanently
- Language detection updates `meme.language_code` only for known languages

## Failure Handling

- **Per-meme**: 3 failures tracked in `ocr_result.describe_failures`, then skipped
- **Per-batch**: 3 consecutive failures → batch stops early
- **Quota exhausted**: HTTP 402 → immediate batch exit on first occurrence (no model fallback — 402 is account-wide)
- **Rate limit**: all models return 429 → batch stops, waits for next cron run
- **Circuit breaker**: Prefect automation pauses deployment after 3 flow failures/hour

## Monitoring

- Flow name: `Describe Memes (OpenRouter Vision)`
- Emits event: `ff.describe_memes.completed` with `{described: N, failed: N}`
- Healthy batch: 15-20 memes described, < 5 failures
- Check: `SELECT count(*) FROM meme WHERE ocr_result->>'calculated_at' > (now() - interval '1 hour')::text`

## Key Files

| File | Purpose |
|------|---------|
| `src/flows/storage/describe_memes.py` | Main flow + vision API client |
| `src/config.py` | `OPENROUTER_API_KEY` setting |
| `scripts/serve_flows.py` | Cron schedule (every 30 min) |

## Known Issues

1. **Free model churn**: OpenRouter frequently removes/changes free models. Gemma 3 → Gemma 4 → back to Gemma 3 happened within days (April 2026). Models need manual verification against the API.
2. **No balance monitoring**: No alerting when OpenRouter balance approaches $0.
3. **No daily request counter**: Can't tell if we're hitting the 1,000/day free limit vs getting rate-limited for other reasons.
4. **Fallback chain multiplies quota usage**: Each failed model attempt (403, timeout, bad response) counts toward the 1,000/day limit. A 5-model chain with 2 broken models wastes 40% of requests. Keep the chain short and remove models that consistently fail (FFM-520, Apr 2026).
