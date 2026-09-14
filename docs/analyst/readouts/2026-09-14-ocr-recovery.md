# OCR recovery and free-model validation — 2026-09-14

## Corrections to September 13 diagnosis

The zero per-key monetary cap was a **local false rejection**, not evidence
that OpenRouter disallowed free inference. The primary account reports
`limit=0`, `limit_remaining=0` and a positive account balance. A direct request
using that same production key and `inclusionai/ling-3.0-flash-vl:free` returned
HTTP 200, usable OCR for meme 10205320, and `usage.cost=0` in 2.8 seconds.
No key spending limit was changed. Free-model enforcement remains mandatory.

Both configured account profiles have at least $10 lifetime credits according
to the authenticated credits API. `is_free_tier=false` alone does not prove
that threshold, and the deprecated `rate_limit` field is not a daily quota.
The additional key was stored in macOS Keychain and server runtime secret
`OPENROUTER_API_KEY_SECONDARY`; no secret values are recorded here.

## Scheduler investigation

Before recovery, all 34 deployments were NOT_READY; OCR last polled September
9. Both server and runner containers were still running. Server logs showed
PostgreSQL connection timeouts on September 9 and a later connection-lost
exception. The HTTP health route still returned 200.

Restarting the Prefect server on September 14 restored scheduling and runner
polling without restarting the runner. OCR became READY, new scheduled runs
appeared, and the 09:15 UTC run completed. That run still used the old OCR guard;
its Completed state is not evidence of an image being processed. The precise
internal failure of Prefect background services was not isolated, so database
errors are an observed precursor rather than a fully proved internal mechanism.

## Live model checks

Catalog queried via `GET /api/v1/models`; only explicit :free models with image
input and zero prompt/completion prices were considered. Tests used the actual
moderator-reported meme images, with no persistence or merge during these probes.

| Model | Result | Decision |
| --- | --- | --- |
| inclusionai/ling-3.0-flash-vl:free | 200, cost 0, usable OCR on both profiles | Add as preferred model; disable reasoning to avoid empty final content |
| dots-studio/dots-3-note-preview:free | 200, cost 0, usable OCR with a mixed-script typo | Add fallback; OCR remains imperfect |
| nex-agi/nex-n2.5-mini:free | 400 invalid request | Do not add |
| thinkingmachines/inkling-small:free | 403 restricted to supported agentic harnesses | Do not add; do not spoof client eligibility |
| google/gemma-4-31b-it:free | 429 upstream shared-pool capacity | Retain fallback with cooldown |

Ling consumed an 800-token allowance entirely on reasoning when reasoning was
not disabled; the successful probe used `reasoning.effort=none`, 2,000 output
tokens, temperature 0. Real results include occasional malformed JSON escapes,
so existing tolerant parsing and response validation remain required.

## Pre-deployment baseline

After scheduler recovery but before the code update, a database snapshot showed
3 saved descriptions in the trailing 24 hours, latest September 13 16:23:57 UTC.
This supersedes the previous-day zero-output snapshot. It does not prove the
old scheduled OCR guard worked: manual/upload paths can also persist OCR.

## Capacity limits

Two accounts do not guarantee twice the successful throughput. Official docs
state that extra accounts/keys do not expand globally governed capacity. Model
availability, per-account daily budgets, provider cooldowns, request pacing,
and per-image deadlines must still govern processing. A scheduled batch of 18
at 15-minute intervals creates an ideal ceiling of 1,728 completed images/day
before retries; this is a target, not measured output.

Sources: [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits),
[model catalog](https://openrouter.ai/api/v1/models), production admin API,
Prefect API/container logs, and authenticated key/credits APIs. No credentials,
private service addresses, or raw user-message history are included.

## Existing merge semantics (unchanged)

The existing resolver consolidates reactions, not an immutable event log. It
keeps one canonical row per user/meme and chat/user/meme; canonical-side state
wins on overlap. This avoids counting one user repeatedly because of reposts.
For the reported triple, a review snapshot found 293 delivery/reaction rows
across 163 users, with 25 users having conflicting explicit reactions. No chat
reactions were present. Lossless raw-event archival is a separate product/data
contract, not part of this OCR queue/key fix.

Canonical meme statistics recompute inside the merge transaction. Source stats
recompute separately hourly at :10; user/source affinity stats at :40 for users
with a reaction in the last seven days. Very old moved reactions can therefore
leave inactive users' materialized source preferences stale until they become
active again. The misleading five-minute docstring does not describe the
actual hourly schedule. No new merge algorithm or archive schema was added.
