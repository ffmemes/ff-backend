"""Metrics views (alembic 2026-11-02_metrics_views) on a tiny fixture."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.database import engine, experiment_assignment, user_deep_link_log, user_meme_reaction
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_user,
    create_user_language,
)

SHARER, FRIEND, BOT = 10501, 10502, 10503
T0 = datetime(2026, 10, 1, 12, 0)


@pytest.fixture(autouse=True)
async def fixture():
    async with engine.begin() as conn:
        await create_meme_source(conn, 10500)
        for meme_id in range(10500, 10510):
            await create_meme(conn, meme_id, 10500)
        for uid in (SHARER, FRIEND, BOT):
            await create_user(conn, uid)
            await create_user_language(conn, uid)
        await conn.execute(text('UPDATE "user" SET created_at = :t WHERE id >= 10501'), {"t": T0})
        await conn.execute(
            text("INSERT INTO analytics_excluded_user (user_id, reason) VALUES (:u, 'test')"),
            {"u": BOT},
        )
        await conn.execute(
            user_deep_link_log.insert(),
            [
                {"user_id": SHARER, "deep_link": None, "created_at": T0},
                {"user_id": FRIEND, "deep_link": f"m_{SHARER}_10500", "created_at": T0},
                {"user_id": SHARER, "deep_link": f"m_{SHARER}_10500", "created_at": T0},  # self
            ],
        )
        # SHARER: session 1 = 3 feed memes (2 likes), 2h gap, push reacted,
        # session 2 = 2 feed memes; day 2 one more feed meme.
        sends = [
            (10500, "lr_smoothed", T0, 1),
            (10501, "lr_smoothed", T0 + timedelta(minutes=1), 1),
            (10502, "lr_smoothed", T0 + timedelta(minutes=2), 2),
            (10503, "broadcast_reengagement_hq", T0 + timedelta(minutes=50), 1),
            (10504, "recently_liked", T0 + timedelta(hours=3), None),
            (10505, "recently_liked", T0 + timedelta(hours=3, minutes=1), 1),
            (10506, "lr_smoothed", T0 + timedelta(days=1, hours=1), 1),
        ]
        await conn.execute(
            user_meme_reaction.insert(),
            [
                {
                    "user_id": SHARER,
                    "meme_id": m,
                    "recommended_by": rb,
                    "sent_at": t,
                    "reaction_id": r,
                    "reacted_at": (T0 + timedelta(hours=3) if rb.startswith("broadcast") else t)
                    if r
                    else None,
                }
                for m, rb, t, r in sends
            ],
        )
        await conn.execute(
            experiment_assignment.insert(),
            {
                "experiment_id": "metrics_test",
                "user_id": SHARER,
                "variant": "control",
                "assigned_at": T0 - timedelta(minutes=1),
            },
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(
            experiment_assignment.delete().where(
                experiment_assignment.c.experiment_id == "metrics_test"
            )
        )
        await conn.execute(text("DELETE FROM analytics_excluded_user WHERE user_id >= 10500"))
        await conn.execute(user_meme_reaction.delete().where(user_meme_reaction.c.user_id >= 10500))
        await cleanup_test_data(conn)


async def _rows(sql: str) -> list[dict]:
    async with engine.connect() as conn:
        return [dict(r._mapping) for r in await conn.execute(text(sql))]


@pytest.mark.asyncio
async def test_metric_user_segments_and_channels():
    rows = await _rows("SELECT * FROM v_metric_user WHERE user_id >= 10501")
    rows = {r["user_id"]: r for r in rows}
    assert rows[SHARER]["segment"] == "user"
    assert rows[SHARER]["acquisition_channel"] == "organic"
    assert rows[FRIEND]["acquisition_channel"] == "share"
    assert rows[BOT]["segment"] == "excluded"
    assert rows[BOT]["acquisition_channel"] == "unknown"
    assert rows[SHARER]["languages"] == "ru"


@pytest.mark.asyncio
async def test_feed_sessions_split_on_30_min_gap():
    rows = await _rows(
        f"SELECT * FROM v_feed_session WHERE user_id = {SHARER} ORDER BY session_start"
    )
    assert [(r["memes_sent"], r["reactions"], r["likes"], r["started_by_push"]) for r in rows] == [
        (3, 3, 2, False),
        (2, 1, 1, True),
        (1, 1, 1, False),
    ]


@pytest.mark.asyncio
async def test_user_day_counts_non_self_shares():
    rows = await _rows(f"SELECT * FROM v_user_day WHERE user_id = {SHARER} ORDER BY day")
    day1 = rows[0]
    assert (day1["memes_sent"], day1["reactions"], day1["likes"]) == (6, 5, 4)
    assert (day1["sessions"], day1["shares"]) == (2, 1)
    assert rows[1]["sessions"] == 1


@pytest.mark.asyncio
async def test_new_user_and_experiment_user():
    nu = (await _rows(f"SELECT * FROM v_new_user WHERE user_id = {SHARER}"))[0]
    assert nu["got_first_meme"] and nu["first_tap"] and nu["first_like"]
    assert nu["reached_5_reactions"] and nu["d1_return"] and not nu["d7_return"]
    assert not nu["blocked_within_24h"]

    eu = (await _rows("SELECT * FROM v_experiment_user WHERE experiment_id = 'metrics_test'"))[0]
    assert (eu["memes_sent"], eu["reactions"], eu["likes"], eu["sessions"]) == (7, 6, 5, 3)
    assert eu["memes_per_session"] == 2
