import pytest

from src.recommendations import candidates


@pytest.mark.asyncio
async def test_goat_recently_seen_filter_uses_sent_at(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, params):
        return {"pool_size": 0}

    async def fake_fetch_all(query, params):
        captured["query"] = str(query)
        captured["params"] = params
        return []

    monkeypatch.setattr(candidates, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(candidates, "fetch_all", fake_fetch_all)

    await candidates.goat(user_id=10001, limit=5)

    query = captured["query"]
    assert "umr.sent_at > NOW() - (:goat_recently_sent_window_days * INTERVAL '1 day')" in query
    assert "umr.sent_at > NOW() - INTERVAL '30 days'" not in query
    assert "umr.reacted_at" not in query
    assert captured["params"] == {
        "user_id": 10001,
        "limit": 5,
        "goat_recently_sent_window_days": candidates.GOAT_RECENTLY_SENT_WINDOW_DAYS,
    }
