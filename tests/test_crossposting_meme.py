import math
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert

from src.crossposting import scoring
from src.crossposting.scoring import score
from src.crossposting.service import get_next_meme_for_channel, log_ranker_decision
from src.database import (
    crossposting,
    crossposting_decision_log,
    engine,
    meme_raw_telegram,
    user_deep_link_log,
)
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


def test_like_volume_factor_raises_score_for_more_likes():
    base = {
        "nlikes": 10,
        "ndislikes": 10,
        "nmemes_sent": 40,
        "raw_impr_rank": 0,
        "age_days": 3,
        "invited_count": 0,
        "src_signal": 10.0,
        "median_signal": 10.0,
        "caption": None,
    }
    v4 = score({**base, "nlikes": 80}, "tgchannelru", "v4")
    assert v4 > score(base, "tgchannelru", "v4")
    assert v4 / score({**base, "nlikes": 80}, "tgchannelru", "v2") == pytest.approx(math.log(81))


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

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked is not None, "Source B candidate should remain selectable"
    assert picked["id"] == 10004, (
        "diversity cap must exclude source 10001 and prefer source 10003 candidate"
    )
    assert decision is not None
    assert decision["picked_meme_id"] == 10004
    assert decision["candidates"][0]["meme_id"] == 10004
    assert decision["score_version"] == 4


@pytest.mark.asyncio
async def test_like_volume_prefers_higher_nlikes_same_source(clean_xpost):
    """score_version=4: ln(nlikes+1) re-ranks within equal quality."""
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10500, language_code="ru")
        await create_meme(
            conn, id=10501, meme_source_id=10500, language_code="ru", type="image", status="ok"
        )
        await create_meme(
            conn, id=10502, meme_source_id=10500, language_code="ru", type="image", status="ok"
        )
        # Same LR ~0.8; volume differs
        await create_meme_stats(conn, meme_id=10501, nlikes=8, ndislikes=2, nmemes_sent=20)
        await create_meme_stats(conn, meme_id=10502, nlikes=80, ndislikes=20, nmemes_sent=200)
        await conn.commit()

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked is not None
    assert picked["id"] == 10502
    assert decision["score_version"] == 4
    assert (
        decision["candidates"][0]["like_volume_factor"]
        > decision["candidates"][1]["like_volume_factor"]
    )


@pytest.mark.asyncio
async def test_live_edit_switches_picking_score(clean_xpost, monkeypatch):
    monkeypatch.setitem(scoring.LIVE, "tgchannelru", "v2")
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10510, language_code="ru")
        await create_meme(
            conn, id=10511, meme_source_id=10510, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10511, nlikes=20, ndislikes=5)
        await conn.commit()

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked is not None
    assert decision["score_version"] == 2
    assert decision["candidates"][0]["picked_by"] == "v2"
    assert decision["candidates"][0]["like_volume_enabled"] is False


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

    picked, decision = await get_next_meme_for_channel("tgchannelru")
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

    picked, decision = await get_next_meme_for_channel("tgchannelru")
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

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked is not None
    assert picked["id"] == 10301
    assert decision is not None
    # Cold-start: src_signal None → 0.5 (what the pre-refactor SQL ORDER BY applied:
    # GREATEST(0.5, NULL) = 0.5; the old logged breakdown wrongly said 1.0)
    only_candidate = decision["candidates"][0]
    assert only_candidate["src_signal"] is None
    assert only_candidate["src_quality_mult"] == 0.5


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

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked is not None
    assert picked["id"] == 10351
    assert decision is not None
    only_candidate = decision["candidates"][0]
    assert only_candidate["pre_inbot_share_clicks"] == 3
    assert only_candidate["pre_inbot_share_click_users"] == 2


@pytest.mark.asyncio
async def test_v5_shadow_logs_content_tags_from_ocr_result(clean_xpost):
    tags = {"format": "tweet_screenshot", "relatable": True, "politics_news": False}
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10700, language_code="ru")
        # A mature posted meme so the v5 enrichment has a forwards baseline.
        await create_meme(conn, id=10701, meme_source_id=10700)
        await _insert_crossposting(
            conn,
            "tgchannelru",
            10701,
            hours_ago=100,
            views=100,
            forwards=5,
            telegram_message_id=999701,
        )
        await create_meme(conn, id=10702, meme_source_id=10700, ocr_result=tags)
        await create_meme_stats(conn, meme_id=10702, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked["id"] == 10702
    cand = decision["candidates"][0]
    assert (cand["content_format"], cand["relatable"], cand["politics_news"]) == (
        "tweet_screenshot",
        True,
        False,
    )
    assert cand["score_v5c"] == round(cand["score_v5"] * 0.85**2, 6)
    assert cand["shadow_v5c_pick_meme_id"] == 10702


@pytest.mark.asyncio
async def test_v5f_shadow_logs_src_fwd_pct(clean_xpost):
    now = datetime.now(UTC).replace(tzinfo=None)
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10800, language_code="ru")
        await create_meme(conn, id=10801, meme_source_id=10800)
        await _insert_crossposting(
            conn,
            "tgchannelru",
            10801,
            hours_ago=100,
            views=100,
            forwards=5,
            telegram_message_id=999801,
        )
        # 11 source posts with a Telethon read; the candidate's own post has the top rate.
        await conn.execute(
            insert(meme_raw_telegram),
            [
                {
                    "id": 10810 + i,
                    "meme_source_id": 10800,
                    "post_id": i,
                    "url": f"https://t.me/x/{i}",
                    "date": now,
                    "views": 1000,
                    "forwards": i,
                    "stats_fetched_at": now,
                }
                for i in range(11)
            ],
        )
        await create_meme(conn, id=10802, meme_source_id=10800, raw_meme_id=10820)
        await create_meme_stats(conn, meme_id=10802, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_channel("tgchannelru")
    assert picked["id"] == 10802
    cand = decision["candidates"][0]
    assert cand["src_fwd_pct"] == 1.0
    assert cand["score_v5f"] == round(cand["score_v5"] * 1.5, 6)
    assert cand["shadow_v5f_pick_meme_id"] == 10802


@pytest.mark.asyncio
async def test_en_ranker_decision_log_has_shadow_share_fields(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10360, language_code="en")
        await create_meme(
            conn, id=10361, meme_source_id=10360, language_code="en", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10361, nlikes=10, ndislikes=2)
        await conn.commit()

    picked, decision = await get_next_meme_for_channel("tgchannelen")
    assert picked is not None
    assert picked["id"] == 10361
    assert decision is not None
    only_candidate = decision["candidates"][0]
    assert only_candidate["pre_inbot_share_clicks"] == 0
    assert only_candidate["pre_inbot_share_click_users"] == 0


@pytest.mark.asyncio
async def test_ranker_decision_log_records_top5(clean_xpost):
    """Decision log persists top-N candidates with full score breakdown for retro analysis."""
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10400, language_code="ru")
        # Create 7 eligible candidates from the same source (so all pass filters
        # and rank by score). log_top_n defaults to 5 → top-5 logged.
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

    picked, decision = await get_next_meme_for_channel("tgchannelru")
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
    assert row["score_version"] == 4
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
        "like_volume_factor",
        "like_volume_enabled",
        "final_score",
    }
    assert required_keys.issubset(row["candidates"][0].keys())
    assert row["candidates"][0]["like_volume_enabled"] is True
    assert row["candidates"][0]["like_volume_factor"] > 1.0
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
