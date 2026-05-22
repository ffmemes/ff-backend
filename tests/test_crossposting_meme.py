from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert

from src.crossposting.service import (
    get_next_meme_for_tgchannelen,
    get_next_meme_for_tgchannelru,
    get_next_share_max_meme_for_tgchannelen,
    get_next_share_max_meme_for_tgchannelru,
    log_ranker_decision,
)
from src.database import crossposting, crossposting_decision_log, engine, user_deep_link_log
from src.flows.crossposting.meme import _clean_caption
from tests.factories import (
    TEST_ID_START,
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_user,
)


def test_strips_reddit_url():
    assert _clean_caption("https://redd.it/1rzi593") == ""


def test_strips_reddit_com_url():
    assert _clean_caption("https://www.reddit.com/r/me_irl/comments/abc") == ""


def test_strips_tg_handle():
    assert _clean_caption("@r_me_irl") == ""


def test_strips_subreddit_name():
    assert _clean_caption("me_irl") == ""


def test_strips_all_attribution_lines():
    caption = "me_irl\nhttps://redd.it/1rzi593\n@r_me_irl"
    assert _clean_caption(caption) == ""


def test_preserves_real_caption():
    caption = "When you finally fix the bug after 3 hours"
    assert _clean_caption(caption) == caption


def test_strips_attribution_preserves_real_content():
    caption = "me_irl\nhttps://redd.it/abc\n@r_me_irl\nThis is a real caption with multiple words"
    assert _clean_caption(caption) == "This is a real caption with multiple words"


def test_empty_string():
    assert _clean_caption("") == ""


def test_whitespace_only():
    assert _clean_caption("  \n  ") == ""


# ── Integration tests for get_next_meme_for_tgchannelru ranker ───────────


async def _wipe(conn):
    await conn.execute(delete(crossposting).where(crossposting.c.meme_id >= TEST_ID_START))
    await conn.execute(
        delete(crossposting_decision_log).where(
            crossposting_decision_log.c.picked_meme_id >= TEST_ID_START
        )
    )
    await cleanup_test_data(conn)
    await conn.commit()


async def _insert_crossposting(
    conn,
    channel: str,
    meme_id: int,
    hours_ago: int,
    views: int = 0,
    forwards: int = 0,
    telegram_message_id: int | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO crossposting "
            "(channel, meme_id, created_at, views, forwards, telegram_message_id) "
            f"VALUES (:channel, :meme_id, NOW() - INTERVAL '{hours_ago} hours', "
            ":views, :forwards, :tmid) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "channel": channel,
            "meme_id": meme_id,
            "views": views,
            "forwards": forwards,
            "tmid": telegram_message_id,
        },
    )


@pytest_asyncio.fixture()
async def clean_xpost():
    async with engine.connect() as conn:
        await _wipe(conn)
    yield
    async with engine.connect() as conn:
        await _wipe(conn)


@pytest.mark.asyncio
async def test_select_excludes_source_posted_within_24h(clean_xpost):
    async with engine.connect() as conn:
        # Source A: posted within 24h → must be excluded by diversity cap
        await create_meme_source(conn, id=10001, language_code="ru")
        await create_meme(
            conn, id=10001, meme_source_id=10001, language_code="ru", type="image", status="ok"
        )
        await create_meme(
            conn, id=10002, meme_source_id=10001, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10001, nlikes=10, ndislikes=2)
        await create_meme_stats(conn, meme_id=10002, nlikes=10, ndislikes=2)
        await _insert_crossposting(
            conn,
            "tgchannelru",
            10001,
            hours_ago=1,
            views=200,
            forwards=20,
            telegram_message_id=999001,
        )

        # Source B: not posted recently → must be selected over Source A
        await create_meme_source(conn, id=10003, language_code="ru")
        await create_meme(
            conn, id=10004, meme_source_id=10003, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10004, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelru()
    assert picked is not None, "Source B candidate should remain selectable"
    assert picked["id"] == 10004, (
        "diversity cap must exclude source 10001 and prefer source 10003 candidate"
    )
    assert decision is not None
    assert decision["picked_meme_id"] == 10004
    assert decision["candidates"][0]["meme_id"] == 10004


@pytest.mark.asyncio
async def test_select_returns_none_when_all_filtered(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10010, language_code="ru")
        # Below nlikes threshold
        await create_meme(
            conn, id=10011, meme_source_id=10010, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10011, nlikes=2, ndislikes=0)
        # Wrong type (video filtered out)
        await create_meme(
            conn, id=10012, meme_source_id=10010, language_code="ru", type="video", status="ok"
        )
        await create_meme_stats(conn, meme_id=10012, nlikes=10, ndislikes=0)
        # Already in crossposting (CP.meme_id IS NULL filter excludes it)
        await create_meme(
            conn, id=10013, meme_source_id=10010, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10013, nlikes=10, ndislikes=0)
        await _insert_crossposting(conn, "tgchannelru", 10013, hours_ago=72, views=100, forwards=5)
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelru()
    assert picked is None
    assert decision is None


@pytest.mark.asyncio
async def test_source_quality_applied_when_n_above_threshold(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10100, language_code="ru", url="https://t.me/good_src")
        await create_meme_source(conn, id=10200, language_code="ru", url="https://t.me/bad_src")

        # 5 mature posts per source (>48h, <30d, image, views>0) so src_quality CTE picks them up
        for i in range(5):
            good_id = 10101 + i
            await create_meme(
                conn,
                id=good_id,
                meme_source_id=10100,
                language_code="ru",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=good_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelru", good_id, hours_ago=24 * 5, views=200, forwards=20
            )

            bad_id = 10201 + i
            await create_meme(
                conn,
                id=bad_id,
                meme_source_id=10200,
                language_code="ru",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=bad_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelru", bad_id, hours_ago=24 * 5, views=50, forwards=2
            )

        # Fresh candidates not in crossposting — one per source
        await create_meme(
            conn, id=10150, meme_source_id=10100, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10150, nlikes=10, ndislikes=2)
        await create_meme(
            conn, id=10250, meme_source_id=10200, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10250, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelru()
    assert picked is not None
    assert picked["id"] == 10150, (
        "good_source candidate should outrank bad_source via SQ multiplier"
    )
    # Decision log captures both candidates with their src_quality_mult
    assert decision is not None
    candidate_meme_ids = [c["meme_id"] for c in decision["candidates"]]
    assert 10150 in candidate_meme_ids and 10250 in candidate_meme_ids
    picked_breakdown = decision["candidates"][0]
    other_breakdown = next(c for c in decision["candidates"] if c["meme_id"] == 10250)
    assert picked_breakdown["src_quality_mult"] > other_breakdown["src_quality_mult"], (
        "good_source mult must exceed bad_source mult"
    )


@pytest.mark.asyncio
async def test_source_quality_neutral_when_no_snapshots(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10300, language_code="ru")
        await create_meme(
            conn, id=10301, meme_source_id=10300, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10301, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelru()
    assert picked is not None
    assert picked["id"] == 10301
    assert decision is not None
    # Cold-start: src_signal None and src_quality_mult falls through to neutral 1.0
    only_candidate = decision["candidates"][0]
    assert only_candidate["src_signal"] is None
    assert only_candidate["src_quality_mult"] == 1.0


@pytest.mark.asyncio
async def test_decision_log_shadow_counts_pre_posting_share_clicks(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10350, language_code="ru")
        await create_meme(
            conn, id=10351, meme_source_id=10350, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10351, nlikes=10, ndislikes=2)

        for user_id in (10051, 10052, 10053, 10054):
            await create_user(conn, id=user_id)

        now = datetime.now(UTC).replace(tzinfo=None)
        await conn.execute(
            insert(user_deep_link_log),
            [
                {
                    "user_id": 10052,
                    "deep_link": "s_10051_10351",
                    "created_at": now - timedelta(hours=2),
                },
                {
                    "user_id": 10052,
                    "deep_link": "s_10051_10351",
                    "created_at": now - timedelta(hours=1),
                },
                {
                    "user_id": 10053,
                    "deep_link": "s_10051_10351",
                    "created_at": now - timedelta(hours=1),
                },
                {
                    "user_id": 10051,
                    "deep_link": "s_10051_10351",
                    "created_at": now - timedelta(hours=1),
                },
                {
                    "user_id": 10051,
                    "deep_link": "s_00010051_10351",
                    "created_at": now - timedelta(minutes=45),
                },
                {
                    "user_id": 10054,
                    "deep_link": "not_a_share_link",
                    "created_at": now - timedelta(minutes=30),
                },
                {
                    "user_id": 10054,
                    "deep_link": "s_999999999999999999999_10351",
                    "created_at": now - timedelta(minutes=30),
                },
                {
                    "user_id": 10054,
                    "deep_link": "s_9999999999999999999_10351",
                    "created_at": now - timedelta(minutes=30),
                },
                {
                    "user_id": 10054,
                    "deep_link": "s_10051_99999",
                    "created_at": now - timedelta(minutes=30),
                },
                {
                    "user_id": 10054,
                    "deep_link": "s_10053_10351",
                    "created_at": now + timedelta(hours=1),
                },
                {
                    "user_id": 10054,
                    "deep_link": "s_lang_10351",
                    "created_at": now - timedelta(hours=1),
                },
            ],
        )
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelru()
    assert picked is not None
    assert picked["id"] == 10351
    assert decision is not None
    only_candidate = decision["candidates"][0]
    assert only_candidate["pre_inbot_share_clicks"] == 3
    assert only_candidate["pre_inbot_share_click_users"] == 2


@pytest.mark.asyncio
async def test_en_ranker_decision_log_has_shadow_share_fields(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10360, language_code="en")
        await create_meme(
            conn, id=10361, meme_source_id=10360, language_code="en", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10361, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelen()
    assert picked is not None
    assert picked["id"] == 10361
    assert decision is not None
    only_candidate = decision["candidates"][0]
    assert only_candidate["pre_inbot_share_clicks"] == 0
    assert only_candidate["pre_inbot_share_click_users"] == 0


@pytest.mark.asyncio
async def test_ru_share_max_picker_boosts_prior_inbot_shares(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10370, language_code="ru")
        await create_meme_source(conn, id=10380, language_code="ru")
        await create_meme(
            conn, id=10371, meme_source_id=10370, language_code="ru", type="image", status="ok"
        )
        await create_meme(
            conn, id=10381, meme_source_id=10380, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10371, nlikes=10, ndislikes=2)
        await create_meme_stats(conn, meme_id=10381, nlikes=10, ndislikes=2)
        for i in range(5):
            left_id = 10372 + i
            right_id = 10382 + i
            await create_meme(
                conn,
                id=left_id,
                meme_source_id=10370,
                language_code="ru",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=left_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelru", left_id, hours_ago=24 * 5, views=100, forwards=5
            )
            await create_meme(
                conn,
                id=right_id,
                meme_source_id=10380,
                language_code="ru",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=right_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelru", right_id, hours_ago=24 * 5, views=100, forwards=5
            )
        for user_id in (10071, 10072):
            await create_user(conn, id=user_id)
        await conn.execute(
            insert(user_deep_link_log),
            [
                {
                    "user_id": 10072,
                    "deep_link": "s_10071_10381",
                    "created_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
                },
            ],
        )
        await conn.commit()

    picked, decision = await get_next_share_max_meme_for_tgchannelru()
    assert picked is not None
    assert decision is not None
    debug_candidates = [
        (
            c["meme_id"],
            c["pre_inbot_share_click_users"],
            c["share_user_boost"],
            c["share_max_base_score"],
            c["share_max_score"],
        )
        for c in decision["candidates"]
    ]
    assert picked["id"] == 10381, debug_candidates
    assert decision["score_version"] == 3
    top_candidate = decision["candidates"][0]
    assert top_candidate["pre_inbot_share_click_users"] == 1
    assert top_candidate["share_user_boost"] == 1.5
    assert top_candidate["share_max_score"] > top_candidate["share_max_base_score"]


@pytest.mark.asyncio
async def test_ru_share_max_picker_keeps_cold_sources_in_pool(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10330, language_code="ru")
        await create_meme_source(conn, id=10340, language_code="ru")
        await create_meme(
            conn, id=10331, meme_source_id=10330, language_code="ru", type="image", status="ok"
        )
        await create_meme(
            conn, id=10341, meme_source_id=10340, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10331, nlikes=10, ndislikes=2)
        await create_meme_stats(conn, meme_id=10341, nlikes=10, ndislikes=2, invited_count=5)
        await conn.commit()

    picked, decision = await get_next_share_max_meme_for_tgchannelru()
    assert picked is not None
    assert picked["id"] == 10341
    assert decision is not None
    assert decision["candidate_pool_size"] == 2
    candidate_ids = {c["meme_id"] for c in decision["candidates"]}
    assert candidate_ids == {10331, 10341}
    assert all(c["share_source_base"] == 1.0 for c in decision["candidates"])


@pytest.mark.asyncio
async def test_en_share_max_picker_logs_but_does_not_boost_prior_shares(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10390, language_code="en")
        await create_meme_source(conn, id=10410, language_code="en")
        await create_meme(
            conn, id=10391, meme_source_id=10390, language_code="en", type="image", status="ok"
        )
        await create_meme(
            conn, id=10411, meme_source_id=10410, language_code="en", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10391, nlikes=10, ndislikes=2)
        await create_meme_stats(conn, meme_id=10411, nlikes=10, ndislikes=2)
        for i in range(5):
            left_id = 10392 + i
            right_id = 10412 + i
            await create_meme(
                conn,
                id=left_id,
                meme_source_id=10390,
                language_code="en",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=left_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelen", left_id, hours_ago=24 * 5, views=100, forwards=5
            )
            await create_meme(
                conn,
                id=right_id,
                meme_source_id=10410,
                language_code="en",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=right_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelen", right_id, hours_ago=24 * 5, views=100, forwards=5
            )
        for user_id in (10091, 10092):
            await create_user(conn, id=user_id)
        await conn.execute(
            insert(user_deep_link_log),
            [
                {
                    "user_id": 10092,
                    "deep_link": "s_10091_10411",
                    "created_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
                },
            ],
        )
        await conn.commit()

    picked, decision = await get_next_share_max_meme_for_tgchannelen()
    assert picked is not None
    assert picked["id"] == 10391
    assert decision is not None
    assert decision["score_version"] == 3
    shared_candidate = next(c for c in decision["candidates"] if c["meme_id"] == 10411)
    assert shared_candidate["pre_inbot_share_click_users"] == 1
    assert shared_candidate["share_user_boost"] == 1.0
    assert shared_candidate["share_max_score"] == shared_candidate["share_max_base_score"]


@pytest.mark.asyncio
async def test_ranker_decision_log_records_top5(clean_xpost):
    """Decision log persists top-N candidates with full score breakdown for retro analysis."""
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10400, language_code="ru")
        # Create 7 eligible candidates from the same source (so all pass filters
        # and rank by score). LIMIT in get_next_meme_for_tgchannelru is 5 → top-5 logged.
        for i in range(7):
            mid = 10401 + i
            await create_meme(
                conn,
                id=mid,
                meme_source_id=10400,
                language_code="ru",
                type="image",
                status="ok",
            )
            # Different nlikes so the ranker has a deterministic ordering
            await create_meme_stats(conn, meme_id=mid, nlikes=20 - i, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_tgchannelru()
    assert picked is not None
    assert decision is not None
    # Persist via the actual logger (exercising the SQL path)
    await log_ranker_decision(**decision)

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT channel, picked_meme_id, score_version, candidate_pool_size, "
                        "candidates FROM crossposting_decision_log WHERE picked_meme_id >= :s "
                        "ORDER BY decided_at DESC LIMIT 1"
                    ),
                    {"s": TEST_ID_START},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row["channel"] == "tgchannelru"
    assert row["picked_meme_id"] == picked["id"]
    assert row["score_version"] == 2
    assert row["candidate_pool_size"] == 7  # 7 eligible memes
    assert len(row["candidates"]) == 5  # top-5 logged (LIMIT 5)
    # Each entry has the documented score breakdown keys
    required_keys = {
        "rank",
        "meme_id",
        "source_id",
        "nlikes",
        "ndislikes",
        "raw_impr_rank",
        "age_days",
        "nmemes_sent",
        "invited_count",
        "pre_inbot_share_clicks",
        "pre_inbot_share_click_users",
        "caption_present",
        "src_signal",
        "src_quality_mult",
        "lr_factor",
        "impr_factor",
        "age_factor",
        "caption_factor",
        "sent_factor",
        "invited_boost",
        "final_score",
    }
    assert required_keys.issubset(row["candidates"][0].keys())
    # Rank order matches list order
    ranks = [c["rank"] for c in row["candidates"]]
    assert ranks == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_ranker_decision_log_does_not_propagate_db_errors(clean_xpost):
    """Caller wraps log_ranker_decision in try/except. Smoke-test that obviously
    invalid args (missing required key) raise — caller is responsible for catching.
    Ensures the logger doesn't silently swallow programmer errors."""
    with pytest.raises(Exception):
        # Missing channel — DB-level NOT NULL violation
        await log_ranker_decision(
            channel=None,  # type: ignore[arg-type]
            picked_meme_id=99999,
            score_version=2,
            median_signal=1.0,
            pool_size=1,
            candidates=[{"rank": 1, "meme_id": 99999}],
        )
