import hashlib
import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Sequence

import httpx

from src.config import settings
from src.redis import redis_client

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_HEALTH_TIMEOUT_SECONDS = 10.0
OPENROUTER_FREE_DAILY_REQUEST_LIMIT = 1000
OPENROUTER_FREE_DAILY_REQUEST_BUDGET = 900
OPENROUTER_FREE_TIER_DAILY_REQUEST_LIMIT = 50
OPENROUTER_FREE_TIER_DAILY_REQUEST_BUDGET = 45
OPENROUTER_FREE_REQUEST_COUNTER_TTL_SECONDS = 60 * 60 * 48
OPENROUTER_FREE_STATS_TTL_SECONDS = 60 * 60 * 24 * 14
OPENROUTER_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60 * 15
OPENROUTER_MAX_RATE_LIMIT_COOLDOWN_SECONDS = 60 * 60
OPENROUTER_TRANSIENT_MODEL_COOLDOWN_SECONDS = 60 * 15
OPENROUTER_FORBIDDEN_MODEL_COOLDOWN_SECONDS = 60 * 60 * 6

# FREE models only. Never add paid models here — spending balance below $0
# blocks ALL models (even free ones) with HTTP 402. Free tier requires $10+
# lifetime purchases for 1,000 req/day (vs 50/day without).
# See specs/describe-memes.md for full OpenRouter constraints.
#
# Verified available on OpenRouter API as of 2026-07-09.
# Ordered by preference. Falls back to next model on 429/403/timeout/bad response.
# Transient failures set Redis cooldowns so later memes/runs try other free models.
VISION_MODELS = [
    "inclusionai/ling-3.0-flash-vl:free",  # verified OCR; requires reasoning disabled
    "google/gemma-4-31b-it:free",  # 262k context, primary
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # 256k context, multimodal
    "google/gemma-4-26b-a4b-it:free",  # 262k context, MoE variant
    "dots-studio/dots-3-note-preview:free",  # verified OCR fallback
    # Gemma 3 free vision fallbacks are no longer listed by OpenRouter.
    # nex-agi/nex-n2-pro:free is no longer listed by OpenRouter.
    # nvidia/nemotron-3.5-content-safety:free is a guardrail classifier, not
    # a general OCR/description model.
    # nvidia/nemotron-nano-12b-v2-vl:free removed — returns 504s and invalid
    # JSON/empty content (see specs/describe-memes.md).
]

DESCRIBE_PROMPT = (
    "You are analyzing a meme image. Extract the following:\n\n"
    "1. OCR_TEXT: ALL text visible in the image, exactly as written. "
    "Preserve original language and line breaks. "
    "If no text, return empty string.\n\n"
    "2. DESCRIPTION: Describe the meme in 1-3 sentences in English. "
    "What's happening visually? What's the joke? "
    "Be specific (panels, characters, reactions, meme format).\n\n"
    "3. LANGUAGE: Primary language of the meme text as ISO 639-1 code "
    '(e.g. "ru", "en"). If no text, return "en". '
    "If mixed, return dominant language.\n\n"
    "Respond with ONLY valid JSON, no markdown fences:\n"
    '{"ocr_text": "...", "description": "...", "language": "..."}'
)

RATE_LIMITED = "__rate_limited"
ALL_FAILED = "__all_failed"
QUOTA_EXHAUSTED = "__quota_exhausted"
DAILY_BUDGET_EXHAUSTED = "__daily_budget_exhausted"
TRY_NEXT_MODEL = "__try_next_model"
TRY_NEXT_KEY = "__try_next_key"


@dataclass(frozen=True)
class OpenRouterKey:
    """One configured key, with a non-secret identifier for Redis accounting."""

    label: str
    secret: str = field(repr=False)
    account_id: str
    daily_budget: int = OPENROUTER_FREE_TIER_DAILY_REQUEST_BUDGET


def get_configured_openrouter_keys() -> tuple[OpenRouterKey, ...]:
    """Return distinct configured keys without ever exposing their values in logs."""
    configured = (
        ("primary", settings.OPENROUTER_API_KEY),
        ("secondary", settings.OPENROUTER_API_KEY_SECONDARY),
    )
    keys: list[OpenRouterKey] = []
    seen: set[str] = set()
    for label, value in configured:
        secret = (value or "").strip()
        if not secret or secret in seen:
            continue
        seen.add(secret)
        account_id = hashlib.blake2s(secret.encode(), digest_size=8).hexdigest()
        keys.append(OpenRouterKey(label=label, secret=secret, account_id=account_id))
    return tuple(keys)


class UnsafeOpenRouterModelError(ValueError):
    """Raised when a non-free OpenRouter model is configured."""


def _validate_free_vision_models(model_ids: list[str]) -> None:
    paid_model_ids = [model_id for model_id in model_ids if not model_id.endswith(":free")]
    if paid_model_ids:
        raise UnsafeOpenRouterModelError(
            "OpenRouter paid models are forbidden in VISION_MODELS: " + ", ".join(paid_model_ids)
        )


def _validate_openrouter_free_budget() -> None:
    if OPENROUTER_FREE_DAILY_REQUEST_BUDGET >= OPENROUTER_FREE_DAILY_REQUEST_LIMIT:
        raise ValueError(
            "OpenRouter local safety budget must stay below the documented "
            f"{OPENROUTER_FREE_DAILY_REQUEST_LIMIT}/day free-model cap"
        )


def _openrouter_free_request_counter_key(now: datetime | None = None) -> str:
    """Shared budget used by scheduled and upload-time OCR across every key."""
    now = now or datetime.now(timezone.utc)
    return f"openrouter:free_requests:{now.date().isoformat()}"


def _openrouter_account_request_counter_key(account_id: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"openrouter:free_requests:{account_id}:{now.date().isoformat()}"


def _openrouter_key_rotation_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"openrouter:free_key_rotation:{now.date().isoformat()}"


def _openrouter_stats_key(account_id: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"openrouter:free_ocr_stats:{account_id}:{now.strftime('%Y-%m-%d:%H')}"


def _openrouter_model_cooldown_key(account_id: str, model_id: str) -> str:
    return f"openrouter:free_model_cooldown:{account_id}:{model_id}"


def _openrouter_global_model_cooldown_key(model_id: str) -> str:
    return f"openrouter:free_model_cooldown:global:{model_id}"


def _openrouter_key_cooldown_key(account_id: str) -> str:
    return f"openrouter:free_key_cooldown:{account_id}"


def _normalize_retry_after(raw_retry_after: float | None) -> float | None:
    if raw_retry_after is None:
        return None
    if raw_retry_after > 60 * 60 * 24:
        return max(0.0, raw_retry_after - time.time())
    return max(0.0, raw_retry_after)


def _rate_limit_cooldown_seconds(raw_retry_after: float | None) -> int:
    retry_after = _normalize_retry_after(raw_retry_after)
    if retry_after is None:
        return OPENROUTER_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
    return int(
        min(
            max(retry_after, 60.0),
            OPENROUTER_MAX_RATE_LIMIT_COOLDOWN_SECONDS,
        )
    )


_RESERVE_OPENROUTER_FREE_REQUEST_LUA = """
local global_current = tonumber(redis.call("GET", KEYS[1]) or "0")
local account_current = tonumber(redis.call("GET", KEYS[2]) or "0")
local global_budget = tonumber(ARGV[1])
local account_budget = tonumber(ARGV[2])
if global_current >= global_budget then
    return {0, global_current, account_current, "global"}
end
if account_current >= account_budget then
    return {0, global_current, account_current, "account"}
end

global_current = redis.call("INCR", KEYS[1])
account_current = redis.call("INCR", KEYS[2])
if global_current == 1 then
    redis.call("EXPIRE", KEYS[1], tonumber(ARGV[3]))
end
if account_current == 1 then
    redis.call("EXPIRE", KEYS[2], tonumber(ARGV[3]))
end

return {1, global_current, account_current, "reserved"}
"""


async def _reserve_openrouter_free_request(
    key: OpenRouterKey,
    log,
    *,
    global_daily_budget: int,
) -> tuple[bool, int, int, str]:
    """Reserve one daily free-model request attempt.

    OpenRouter counts failed attempts toward the daily free quota, so we reserve
    before every model attempt, including fallbacks. If Redis is unavailable, fail
    closed and do not call OpenRouter.
    """
    global_counter_key = _openrouter_free_request_counter_key()
    account_counter_key = _openrouter_account_request_counter_key(key.account_id)
    try:
        reserved, used_today, used_by_account, scope = await redis_client.eval(
            _RESERVE_OPENROUTER_FREE_REQUEST_LUA,
            2,
            global_counter_key,
            account_counter_key,
            global_daily_budget,
            key.daily_budget,
            OPENROUTER_FREE_REQUEST_COUNTER_TTL_SECONDS,
        )
        return bool(int(reserved)), int(used_today), int(used_by_account), str(scope)
    except Exception as e:
        log.error("OpenRouter quota guard failed via Redis; refusing request: %s", e)
        return False, -1, -1, "unavailable"


async def _record_openrouter_metric(key: OpenRouterKey, model_id: str, outcome: str) -> None:
    stats_key = _openrouter_stats_key(key.account_id)
    field = f"{model_id}:{outcome}"
    try:
        async with redis_client.pipeline(transaction=True) as pipe:
            await pipe.hincrby(stats_key, field, 1)
            await pipe.expire(stats_key, OPENROUTER_FREE_STATS_TTL_SECONDS)
            await pipe.execute()
    except Exception:
        pass


async def _get_openrouter_model_cooldown(key: OpenRouterKey, model_id: str) -> int:
    try:
        account_ttl, global_ttl = (
            await redis_client.ttl(_openrouter_model_cooldown_key(key.account_id, model_id)),
            await redis_client.ttl(_openrouter_global_model_cooldown_key(model_id)),
        )
    except Exception:
        return 0
    return max(
        int(account_ttl) if account_ttl and account_ttl > 0 else 0,
        int(global_ttl) if global_ttl and global_ttl > 0 else 0,
    )


async def _cool_down_openrouter_model(
    key: OpenRouterKey,
    model_id: str,
    seconds: int,
    reason: str,
    *,
    shared: bool = False,
) -> None:
    try:
        await redis_client.set(
            _openrouter_model_cooldown_key(key.account_id, model_id),
            reason,
            ex=max(1, int(seconds)),
        )
        if shared:
            await redis_client.set(
                _openrouter_global_model_cooldown_key(model_id),
                reason,
                ex=max(1, int(seconds)),
            )
    except Exception:
        pass


async def _cool_down_transient_openrouter_model(
    key: OpenRouterKey,
    model_id: str,
    reason: str,
) -> float:
    await _cool_down_openrouter_model(
        key,
        model_id,
        OPENROUTER_TRANSIENT_MODEL_COOLDOWN_SECONDS,
        reason,
    )
    return float(OPENROUTER_TRANSIENT_MODEL_COOLDOWN_SECONDS)


async def _get_openrouter_key_cooldown(key: OpenRouterKey) -> int:
    try:
        ttl = await redis_client.ttl(_openrouter_key_cooldown_key(key.account_id))
    except Exception:
        return 0
    return int(ttl) if ttl and ttl > 0 else 0


async def _cool_down_openrouter_key(key: OpenRouterKey, seconds: int, reason: str) -> None:
    try:
        await redis_client.set(
            _openrouter_key_cooldown_key(key.account_id),
            reason,
            ex=max(1, int(seconds)),
        )
    except Exception:
        pass


async def _rotate_openrouter_keys(keys: tuple[OpenRouterKey, ...]) -> tuple[OpenRouterKey, ...]:
    """Round-robin the preferred account without using a key value as state."""
    if len(keys) < 2:
        return keys
    try:
        turn = int(await redis_client.incr(_openrouter_key_rotation_key()))
        if turn == 1:
            await redis_client.expire(
                _openrouter_key_rotation_key(), OPENROUTER_FREE_REQUEST_COUNTER_TTL_SECONDS
            )
    except Exception:
        return keys
    offset = (turn - 1) % len(keys)
    return keys[offset:] + keys[:offset]


def _shared_daily_budget(keys: Sequence[OpenRouterKey]) -> int:
    """Aggregate verified distinct accounts without crediting duplicate keys twice."""
    by_account: dict[str, int] = {}
    for key in keys:
        by_account[key.account_id] = max(by_account.get(key.account_id, 0), key.daily_budget)
    return sum(by_account.values())


def _is_exhausted_key_limit(limit: object, limit_remaining: object) -> bool:
    """Return whether a positive configured spend limit has no credit left.

    OpenRouter's ``limit=0, limit_remaining=0`` permits free-model requests;
    it means the key cannot spend paid credits, rather than that it is disabled.
    """
    if limit is None or limit_remaining is None:
        return False

    try:
        return float(limit) > 0 and float(limit_remaining) <= 0
    except (TypeError, ValueError):
        return False


def _daily_budget_from_total_credits(total_credits: object) -> int:
    """Use OpenRouter's lifetime-credit threshold, never an account-count guess."""
    try:
        return (
            OPENROUTER_FREE_DAILY_REQUEST_BUDGET
            if float(total_credits) >= 10
            else OPENROUTER_FREE_TIER_DAILY_REQUEST_BUDGET
        )
    except (TypeError, ValueError):
        # The health endpoint can be unavailable independently of model serving.
        # Preserve availability while using the lower documented free-tier cap.
        return OPENROUTER_FREE_TIER_DAILY_REQUEST_BUDGET


async def _check_openrouter_key_health(key: OpenRouterKey, log) -> OpenRouterKey | None:
    """Check whether one configured OpenRouter key can make free-model requests.

    This endpoint does not spend model quota. If the check itself is unavailable,
    fail open so a transient OpenRouter metadata outage does not stop OCR.
    """
    headers = {"Authorization": f"Bearer {key.secret}"}

    try:
        async with httpx.AsyncClient(timeout=OPENROUTER_KEY_HEALTH_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{OPENROUTER_BASE_URL}/key", headers=headers)
    except httpx.RequestError as e:
        log.warning(
            "OpenRouter key health check unavailable (%s); continuing with model calls.",
            type(e).__name__,
        )
        return key

    if response.status_code in {401, 403}:
        log.error(
            "OpenRouter %s key health check failed with HTTP %s; key is invalid or unauthorized.",
            key.label,
            response.status_code,
        )
        return None

    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPStatusError, json.JSONDecodeError) as e:
        log.warning("OpenRouter key health check returned unusable response: %s", e)
        return key

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    limit = data.get("limit")
    limit_remaining = data.get("limit_remaining")
    limit_reset = data.get("limit_reset")
    is_free_tier = data.get("is_free_tier")

    if _is_exhausted_key_limit(limit, limit_remaining):
        log.error(
            "OpenRouter %s key spend limit exhausted (limit=%s, limit_remaining=%s, "
            "limit_reset=%s). Trying another configured key if available.",
            key.label,
            limit,
            limit_remaining,
            limit_reset or "never",
        )
        return None

    total_credits = None
    try:
        async with httpx.AsyncClient(timeout=OPENROUTER_KEY_HEALTH_TIMEOUT_SECONDS) as client:
            credits_response = await client.get(f"{OPENROUTER_BASE_URL}/credits", headers=headers)
        credits_response.raise_for_status()
        credits_payload = credits_response.json()
        credits_data = credits_payload.get("data", {}) if isinstance(credits_payload, dict) else {}
        total_credits = credits_data.get("total_credits")
    except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as e:
        log.warning(
            "OpenRouter %s key credits check unavailable (%s); using the 50/day free-tier guard.",
            key.label,
            type(e).__name__,
        )

    creator_user_id = data.get("creator_user_id")
    account_id = key.account_id
    if creator_user_id is not None:
        account_id = hashlib.blake2s(str(creator_user_id).encode(), digest_size=8).hexdigest()
    checked_key = replace(
        key,
        account_id=account_id,
        daily_budget=_daily_budget_from_total_credits(total_credits),
    )

    log.info(
        "OpenRouter %s key health ok (limit=%s, limit_remaining=%s, limit_reset=%s, "
        "is_free_tier=%s, daily_budget=%s).",
        key.label,
        limit if limit is not None else "unlimited",
        limit_remaining if limit_remaining is not None else "unlimited",
        limit_reset or "never",
        is_free_tier,
        checked_key.daily_budget,
    )
    return checked_key


async def check_openrouter_key_health(log) -> bool:
    """Backward-compatible health check for the configured primary key."""
    keys = get_configured_openrouter_keys()
    primary = next((key for key in keys if key.label == "primary"), None)
    return primary is not None and await _check_openrouter_key_health(primary, log) is not None


async def get_usable_openrouter_keys(log) -> tuple[OpenRouterKey, ...]:
    """Probe every distinct configured key and retain only usable accounts."""
    usable: list[OpenRouterKey] = []
    seen_accounts: set[str] = set()
    for key in get_configured_openrouter_keys():
        checked_key = await _check_openrouter_key_health(key, log)
        if checked_key is not None and checked_key.account_id not in seen_accounts:
            usable.append(checked_key)
            seen_accounts.add(checked_key.account_id)
        elif checked_key is not None:
            log.info(
                "Skipping OpenRouter %s key: it belongs to an already configured account.",
                key.label,
            )
    return tuple(usable)


def _parse_vision_response(raw_content: str) -> dict:
    """Parse JSON from model response, stripping markdown fences if present."""
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    try:
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", content)
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    result = {}
    for key in ("ocr_text", "description", "language"):
        match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
        if match:
            try:
                result[key] = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                result[key] = match.group(1)
    if result:
        return result

    raise json.JSONDecodeError("Could not parse model response", content, 0)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Extract retry delay from Retry-After header or response body."""
    header = response.headers.get("retry-after") or response.headers.get("x-ratelimit-reset")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        body = response.json()
        if "error" in body and "metadata" in body["error"]:
            reset = body["error"]["metadata"].get("ratelimit_reset")
            if reset:
                return float(reset)
    except Exception:
        pass
    return None


async def call_openrouter_vision(
    image_b64: str,
    log,
    *,
    deadline: float | None = None,
    keys: Sequence[OpenRouterKey] | None = None,
) -> dict:
    """Call OpenRouter vision model with fallback chain.

    Args:
        deadline: monotonic timestamp after which we stop trying models.

    Returns:
        dict with result on success, or {RATE_LIMITED: True} / {ALL_FAILED: True}
    """
    keys = tuple(keys) if keys is not None else get_configured_openrouter_keys()
    if not keys:
        return {ALL_FAILED: True}
    keys = await _rotate_openrouter_keys(keys)
    global_daily_budget = _shared_daily_budget(keys)
    next_retry_after: float | None = None
    tried_models = 0
    saw_quota_exhausted = False
    saw_account_budget_exhausted = False

    async with httpx.AsyncClient(timeout=30.0) as client:
        for key in keys:
            if await _get_openrouter_key_cooldown(key) > 0:
                continue
            headers = {"Authorization": f"Bearer {key.secret}", "Content-Type": "application/json"}
            for model_id in VISION_MODELS:
                if not model_id.endswith(":free"):
                    raise UnsafeOpenRouterModelError(
                        f"Refusing non-free OpenRouter model: {model_id}"
                    )

                cooldown_ttl = await _get_openrouter_model_cooldown(key, model_id)
                if cooldown_ttl > 0:
                    log.info(
                        "Skipping %s — free-model cooldown has %ss remaining.",
                        model_id,
                        cooldown_ttl,
                    )
                    if next_retry_after is None or cooldown_ttl < next_retry_after:
                        next_retry_after = float(cooldown_ttl)
                    continue

                if deadline is not None and time.monotonic() > deadline - 35:
                    log.warning("Skipping remaining models — approaching deadline")
                    break

                payload = {
                    "model": model_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": DESCRIBE_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}",
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 2000,
                    "temperature": 0.2,
                    "reasoning": {"effort": "none"},
                }

                try:
                    (
                        reserved,
                        used_today,
                        account_used,
                        budget_scope,
                    ) = await _reserve_openrouter_free_request(
                        key, log, global_daily_budget=global_daily_budget
                    )
                    if not reserved:
                        if budget_scope == "account":
                            saw_account_budget_exhausted = True
                            log.info(
                                "OpenRouter %s account guard exhausted (%s/%s attempts); "
                                "trying another key.",
                                key.label,
                                account_used if account_used >= 0 else "unknown",
                                key.daily_budget,
                            )
                            break
                        log.warning(
                            "OpenRouter free-model daily safety budget exhausted "
                            "(%s/%s attempts). Refusing request.",
                            used_today if used_today >= 0 else "unknown",
                            global_daily_budget,
                        )
                        return {DAILY_BUDGET_EXHAUSTED: True, "__used_today": used_today}
                    tried_models += 1
                    await _record_openrouter_metric(key, model_id, "attempt")

                    response = await client.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                    status_result = await _handle_status_response(response, key, model_id, log)
                    if status_result is not None:
                        if status_result.get(TRY_NEXT_KEY):
                            saw_quota_exhausted = saw_quota_exhausted or status_result.get(
                                QUOTA_EXHAUSTED, False
                            )
                            break
                        if status_result.get(TRY_NEXT_MODEL):
                            continue
                        if status_result.get(RATE_LIMITED):
                            cooldown = status_result["__retry_after"]
                            if next_retry_after is None or cooldown < next_retry_after:
                                next_retry_after = float(cooldown)
                            continue
                        return status_result

                    response.raise_for_status()
                    result = await _parse_success_response(response, key, model_id, log)
                    if result is not None:
                        return result

                    if next_retry_after is None:
                        next_retry_after = float(OPENROUTER_TRANSIENT_MODEL_COOLDOWN_SECONDS)
                    continue

                except json.JSONDecodeError as e:
                    await _record_openrouter_metric(key, model_id, "invalid_json")
                    retry_after = await _cool_down_transient_openrouter_model(
                        key, model_id, "invalid_json"
                    )
                    if next_retry_after is None or retry_after < next_retry_after:
                        next_retry_after = retry_after
                    log.warning("Model %s invalid JSON: %s", model_id, e)
                    continue
                except httpx.HTTPStatusError as e:
                    await _record_openrouter_metric(key, model_id, f"http_{e.response.status_code}")
                    if e.response.status_code >= 500:
                        retry_after = await _cool_down_transient_openrouter_model(
                            key,
                            model_id,
                            f"http_{e.response.status_code}",
                        )
                        if next_retry_after is None or retry_after < next_retry_after:
                            next_retry_after = retry_after
                    log.warning("Model %s HTTP %s", model_id, e.response.status_code)
                    continue
                except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    await _record_openrouter_metric(key, model_id, "timeout")
                    retry_after = await _cool_down_transient_openrouter_model(
                        key, model_id, "timeout"
                    )
                    if next_retry_after is None or retry_after < next_retry_after:
                        next_retry_after = retry_after
                    log.warning("Model %s timeout: %s", model_id, type(e).__name__)
                    continue
                except httpx.RequestError as e:
                    await _record_openrouter_metric(key, model_id, "request_error")
                    retry_after = await _cool_down_transient_openrouter_model(
                        key, model_id, "request_error"
                    )
                    if next_retry_after is None or retry_after < next_retry_after:
                        next_retry_after = retry_after
                    log.warning("Model %s request error: %s", model_id, type(e).__name__)
                    continue
                except Exception as e:
                    await _record_openrouter_metric(key, model_id, "error")
                    log.warning("Model %s error: %s", model_id, e)
                    continue

    if saw_quota_exhausted:
        return {QUOTA_EXHAUSTED: True}
    if saw_account_budget_exhausted:
        return {DAILY_BUDGET_EXHAUSTED: True}
    if tried_models == 0 or next_retry_after is not None:
        return {RATE_LIMITED: True, "__retry_after": next_retry_after}

    return {ALL_FAILED: True}


async def _handle_status_response(
    response: httpx.Response,
    key: OpenRouterKey,
    model_id: str,
    log,
) -> dict | None:
    if response.status_code == 402:
        log.warning(
            "OpenRouter %s key returned HTTP 402; trying another configured key.",
            key.label,
        )
        await _record_openrouter_metric(key, model_id, "quota_exhausted")
        await _cool_down_openrouter_key(
            key, OPENROUTER_FORBIDDEN_MODEL_COOLDOWN_SECONDS, "quota_exhausted"
        )
        return {QUOTA_EXHAUSTED: True, TRY_NEXT_KEY: True}

    if response.status_code == 401:
        await _record_openrouter_metric(key, model_id, "unauthorized")
        await _cool_down_openrouter_key(
            key, OPENROUTER_FORBIDDEN_MODEL_COOLDOWN_SECONDS, "unauthorized"
        )
        return {TRY_NEXT_KEY: True}

    if response.status_code == 429:
        raw_retry_after = _parse_retry_after(response)
        retry_after = _normalize_retry_after(raw_retry_after)
        cooldown = _rate_limit_cooldown_seconds(raw_retry_after)
        await _record_openrouter_metric(key, model_id, "rate_limited")
        await _cool_down_openrouter_model(key, model_id, cooldown, "rate_limited", shared=True)
        log.info(
            "Rate-limited (429) on %s (retry-after: %ss, cooldown: %ss)",
            model_id,
            retry_after or "unknown",
            cooldown,
        )
        return {RATE_LIMITED: True, "__retry_after": cooldown}

    if response.status_code == 403:
        await _record_openrouter_metric(key, model_id, "forbidden")
        await _cool_down_openrouter_model(
            key,
            model_id,
            OPENROUTER_FORBIDDEN_MODEL_COOLDOWN_SECONDS,
            "forbidden",
        )
        log.warning("Model %s HTTP 403 (access denied), trying next...", model_id)
        return {TRY_NEXT_MODEL: True}

    return None


async def _parse_success_response(
    response: httpx.Response,
    key: OpenRouterKey,
    model_id: str,
    log,
) -> dict | None:
    body = response.text.strip()
    json_start = body.find("{")
    if json_start < 0:
        await _record_bad_response(
            key, model_id, log, "bad_response", "returned no JSON", body[:100]
        )
        return None

    data = json.loads(body[json_start:])
    if "choices" not in data:
        await _record_bad_response(
            key, model_id, log, "bad_response", "no choices", str(data)[:200]
        )
        return None

    content = data["choices"][0]["message"]["content"]
    if not content:
        await _record_bad_response(key, model_id, log, "empty_content", "empty content", "")
        return None

    result = _parse_vision_response(content)
    if "description" not in result and "ocr_text" not in result:
        await _record_bad_response(key, model_id, log, "bad_json", "bad JSON", str(result)[:200])
        return None

    result["__model"] = model_id
    await _record_openrouter_metric(key, model_id, "success")
    return result


async def _record_bad_response(
    key: OpenRouterKey,
    model_id: str,
    log,
    metric: str,
    message: str,
    detail: str,
) -> None:
    await _record_openrouter_metric(key, model_id, metric)
    await _cool_down_transient_openrouter_model(key, model_id, metric)
    log.warning("Model %s %s: %s", model_id, message, detail)


_validate_free_vision_models(VISION_MODELS)
_validate_openrouter_free_budget()
