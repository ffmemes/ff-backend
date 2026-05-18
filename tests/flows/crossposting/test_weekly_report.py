import pytest

from src.flows.crossposting import weekly_report


def test_format_report_includes_public_nicknames() -> None:
    text = weekly_report._format_report(
        {
            "minted": 5978,
            "spent": 23,
            "active_earners": 457,
            "total_supply": 533831,
            "top_earners": [
                {"nickname": "Alice & Bob", "earned": 1107},
                {"nickname": None, "earned": 1000},
            ],
        }
    )

    assert "🥇 Alice &amp; Bob: +1 107 🍔" in text
    assert "🥈 без /nickname: +1 000 🍔" in text


@pytest.mark.asyncio
async def test_weekly_burger_stats_queries_top_earner_nicknames(monkeypatch) -> None:
    async def fake_fetch_one(statement):
        sql = str(statement)
        if "SUM(ABS(amount))" in sql:
            return {"total": 23}
        if "COUNT(DISTINCT user_id)" in sql:
            return {"count": 457}
        return {"total": 5978}

    async def fake_fetch_all(statement):
        sql = str(statement)
        assert "u.nickname" in sql
        assert 'LEFT JOIN "user" u' in sql
        return [{"user_id": 10001, "nickname": "burger_ceo", "earned": 700}]

    monkeypatch.setattr(weekly_report, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(weekly_report, "fetch_all", fake_fetch_all)

    stats = await weekly_report._get_weekly_burger_stats()

    assert stats["top_earners"][0]["user_id"] == 10001
    assert stats["top_earners"][0]["nickname"] == "burger_ceo"
    assert stats["top_earners"][0]["earned"] == 700
