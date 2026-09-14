import httpx
import pytest

from src.flows.storage import openrouter_vision


class _Log:
    def __init__(self):
        self.messages = []

    def error(self, message, *args):
        self.messages.append(("error", message % args if args else message))

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def warning(self, message, *args):
        self.messages.append(("warning", message % args if args else message))


class _FakeAsyncClient:
    def __init__(self, response=None, error=None, **_kwargs):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def _response(status_code: int, payload: dict):
    request = httpx.Request("GET", "https://openrouter.ai/api/v1/key")
    return httpx.Response(status_code, json=payload, request=request)


class _KeyHealthClient:
    def __init__(self, responses, **_kwargs):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, *, headers):
        return self.responses[(headers["Authorization"], url.rsplit("/", 1)[-1])]


class _VisionClient:
    def __init__(self, response, captured, **_kwargs):
        self.response = response
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, *, headers, json):
        self.captured["headers"] = headers
        self.captured["json"] = json
        return self.response


@pytest.mark.asyncio
async def test_check_openrouter_key_health_blocks_exhausted_key(monkeypatch):
    response = _response(
        200,
        {"data": {"limit": 1, "limit_remaining": 0, "limit_reset": "monthly"}},
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    log = _Log()

    assert await openrouter_vision.check_openrouter_key_health(log) is False
    assert any("limit exhausted" in message for level, message in log.messages if level == "error")


@pytest.mark.asyncio
async def test_check_openrouter_key_health_allows_unlimited_key(monkeypatch):
    response = _response(
        200,
        {"data": {"limit": None, "limit_remaining": None, "limit_reset": None}},
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    assert await openrouter_vision.check_openrouter_key_health(_Log()) is True


@pytest.mark.asyncio
async def test_check_openrouter_key_health_allows_zero_paid_limit_for_free_models(monkeypatch):
    response = _response(
        200,
        {"data": {"limit": 0, "limit_remaining": 0, "limit_reset": None}},
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(response=response, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    assert await openrouter_vision.check_openrouter_key_health(_Log()) is True


@pytest.mark.asyncio
async def test_check_openrouter_key_health_fails_open_when_probe_unavailable(monkeypatch):
    error = httpx.ConnectError(
        "unavailable",
        request=httpx.Request("GET", "https://openrouter.ai/api/v1/key"),
    )
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(error=error, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "test-key")

    assert await openrouter_vision.check_openrouter_key_health(_Log()) is True


def test_is_exhausted_key_limit_ignores_unlimited_or_unknown_values():
    assert openrouter_vision._is_exhausted_key_limit(None, None) is False
    assert openrouter_vision._is_exhausted_key_limit(1, "not-a-number") is False
    assert openrouter_vision._is_exhausted_key_limit(1, 0) is True
    assert openrouter_vision._is_exhausted_key_limit(0, 0) is False


def test_configured_openrouter_keys_deduplicates_identical_values(monkeypatch):
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "same-key")
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY_SECONDARY", "same-key")

    keys = openrouter_vision.get_configured_openrouter_keys()

    assert [key.label for key in keys] == ["primary"]
    assert keys[0].secret == "same-key"


@pytest.mark.parametrize(
    ("total_credits", "expected_budget"),
    [(None, 45), (9.99, 45), (10, 900), (40, 900)],
)
def test_daily_budget_uses_documented_lifetime_credit_threshold(total_credits, expected_budget):
    assert openrouter_vision._daily_budget_from_total_credits(total_credits) == expected_budget


@pytest.mark.asyncio
async def test_secondary_health_survives_primary_unauthorized(monkeypatch):
    primary = "Bearer primary-key"
    secondary = "Bearer secondary-key"
    responses = {
        (primary, "key"): _response(401, {}),
        (secondary, "key"): _response(200, {"data": {"limit": 0, "limit_remaining": 0}}),
        (secondary, "credits"): _response(200, {"data": {"total_credits": 10}}),
    }
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _KeyHealthClient(responses, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "primary-key")
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY_SECONDARY", "secondary-key")

    usable = await openrouter_vision.get_usable_openrouter_keys(_Log())

    assert [key.label for key in usable] == ["secondary"]
    assert usable[0].daily_budget == 900


@pytest.mark.asyncio
async def test_model_cooldowns_are_account_scoped(monkeypatch):
    calls = []

    class _Redis:
        async def ttl(self, redis_key):
            calls.append(redis_key)
            return 0

    first = openrouter_vision.OpenRouterKey("primary", "one", "first")
    second = openrouter_vision.OpenRouterKey("secondary", "two", "second")
    monkeypatch.setattr(openrouter_vision, "redis_client", _Redis())

    await openrouter_vision._get_openrouter_model_cooldown(first, "model:free")
    await openrouter_vision._get_openrouter_model_cooldown(second, "model:free")

    assert "openrouter:free_model_cooldown:first:model:free" in calls
    assert "openrouter:free_model_cooldown:second:model:free" in calls


@pytest.mark.asyncio
async def test_key_rotation_alternates_preferred_account(monkeypatch):
    class _Redis:
        def __init__(self):
            self.turn = 0

        async def incr(self, _key):
            self.turn += 1
            return self.turn

        async def expire(self, _key, _ttl):
            return True

    monkeypatch.setattr(openrouter_vision, "redis_client", _Redis())
    first = openrouter_vision.OpenRouterKey("primary", "one", "first")
    second = openrouter_vision.OpenRouterKey("secondary", "two", "second")

    first_turn = await openrouter_vision._rotate_openrouter_keys((first, second))
    second_turn = await openrouter_vision._rotate_openrouter_keys((first, second))

    assert [key.label for key in first_turn] == ["primary", "secondary"]
    assert [key.label for key in second_turn] == ["secondary", "primary"]


@pytest.mark.asyncio
async def test_quota_reservation_keeps_existing_shared_counter_and_adds_account_counter(
    monkeypatch,
):
    captured = {}

    class _Redis:
        async def eval(self, _script, key_count, *args):
            captured["key_count"] = key_count
            captured["args"] = args
            return 1, 7, 3, "reserved"

    monkeypatch.setattr(openrouter_vision, "redis_client", _Redis())
    key = openrouter_vision.OpenRouterKey("primary", "one", "account", daily_budget=900)

    assert await openrouter_vision._reserve_openrouter_free_request(
        key, _Log(), global_daily_budget=900
    ) == (
        True,
        7,
        3,
        "reserved",
    )
    assert captured["key_count"] == 2
    assert captured["args"][0].startswith("openrouter:free_requests:")
    assert captured["args"][1].startswith("openrouter:free_requests:account:")


def test_shared_daily_budget_sums_distinct_accounts_only():
    keys = (
        openrouter_vision.OpenRouterKey("primary", "one", "account-a", daily_budget=900),
        openrouter_vision.OpenRouterKey("secondary", "two", "account-b", daily_budget=900),
    )

    assert openrouter_vision._shared_daily_budget(keys) == 1800
    assert openrouter_vision._shared_daily_budget((keys[0], keys[0])) == 900


@pytest.mark.asyncio
async def test_health_deduplicates_distinct_keys_for_the_same_creator_account(monkeypatch):
    primary = "Bearer primary-key"
    secondary = "Bearer secondary-key"
    responses = {
        (primary, "key"): _response(
            200, {"data": {"limit": 0, "limit_remaining": 0, "creator_user_id": 123}}
        ),
        (primary, "credits"): _response(200, {"data": {"total_credits": 10}}),
        (secondary, "key"): _response(
            200, {"data": {"limit": 0, "limit_remaining": 0, "creator_user_id": 123}}
        ),
        (secondary, "credits"): _response(200, {"data": {"total_credits": 10}}),
    }
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _KeyHealthClient(responses, **kwargs),
    )
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY", "primary-key")
    monkeypatch.setattr(openrouter_vision.settings, "OPENROUTER_API_KEY_SECONDARY", "secondary-key")

    usable = await openrouter_vision.get_usable_openrouter_keys(_Log())

    assert [key.label for key in usable] == ["primary"]


@pytest.mark.asyncio
async def test_vision_request_disables_reasoning_and_uses_larger_token_budget(monkeypatch):
    key = openrouter_vision.OpenRouterKey("primary", "key", "account", daily_budget=900)
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": '{"ocr_text":"x","description":"y"}'}}]},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    captured = {}
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _VisionClient(response, captured, **kwargs),
    )

    async def reserve(*_args, **_kwargs):
        return True, 1, 1, "reserved"

    async def no_cooldown(*_args):
        return 0

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(openrouter_vision, "_reserve_openrouter_free_request", reserve)
    monkeypatch.setattr(openrouter_vision, "_get_openrouter_model_cooldown", no_cooldown)
    monkeypatch.setattr(openrouter_vision, "_get_openrouter_key_cooldown", no_cooldown)
    monkeypatch.setattr(openrouter_vision, "_record_openrouter_metric", no_op)
    monkeypatch.setattr(
        openrouter_vision, "_rotate_openrouter_keys", lambda keys: _return_keys(keys)
    )

    result = await openrouter_vision.call_openrouter_vision("image", _Log(), keys=(key,))

    assert result["ocr_text"] == "x"
    assert captured["json"]["max_tokens"] == 2000
    assert captured["json"]["reasoning"] == {"effort": "none"}


@pytest.mark.asyncio
async def test_all_account_guards_exhausted_stops_without_marking_a_meme_failed(monkeypatch):
    key = openrouter_vision.OpenRouterKey("primary", "key", "account", daily_budget=900)
    monkeypatch.setattr(
        openrouter_vision.httpx,
        "AsyncClient",
        lambda **kwargs: _VisionClient(None, {}, **kwargs),
    )

    async def account_exhausted(*_args, **_kwargs):
        return False, 900, 900, "account"

    async def no_cooldown(*_args):
        return 0

    monkeypatch.setattr(openrouter_vision, "_reserve_openrouter_free_request", account_exhausted)
    monkeypatch.setattr(openrouter_vision, "_get_openrouter_model_cooldown", no_cooldown)
    monkeypatch.setattr(openrouter_vision, "_get_openrouter_key_cooldown", no_cooldown)
    monkeypatch.setattr(
        openrouter_vision, "_rotate_openrouter_keys", lambda keys: _return_keys(keys)
    )

    result = await openrouter_vision.call_openrouter_vision("image", _Log(), keys=(key,))

    assert result[openrouter_vision.DAILY_BUDGET_EXHAUSTED] is True


async def _return_keys(keys):
    return keys
