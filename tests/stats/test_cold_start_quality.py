from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_reaction,
    create_user,
)

from src.database import engine, fetch_all
from src.stats.cold_start_quality import (
    ReadoutSection,
    build_cold_start_first10_quality_query,
    cold_start_first10_quality_params,
)

T0 = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)


@pytest_asyncio.fixture()
async def cold_start_readout_data():
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10001, url="https://t.me/source_ru", language_code="ru")
        await create_meme_source(conn, id=10002, url="https://t.me/source_en", language_code="en")

        for meme_id in range(10001, 10021):
            source_id = 10001 if meme_id % 2 else 10002
            language_code = "ru" if source_id == 10001 else "en"
            meme_type = "image" if meme_id % 3 else "animation"
            await create_meme(
                conn,
                id=meme_id,
                meme_source_id=source_id,
                type=meme_type,
                language_code=language_code,
            )
            await create_meme_stats(
                conn,
                meme_id=meme_id,
                lr_smoothed=0.1 * (meme_id - 10000),
                engagement_score=0.05 * (meme_id - 10000),
            )

        for user_id in range(10001, 10005):
            await create_user(conn, id=user_id)

        user_10001_reactions = [1, 2, None, 1, 2, 1, 2, 1, 2, 1]
        for index, reaction_id in enumerate(user_10001_reactions, start=1):
            sent_at = T0 + timedelta(minutes=index - 1)
            if index >= 6:
                sent_at = T0 + timedelta(minutes=39 + index)
            reacted_at = None
            if reaction_id is not None:
                seconds_to_react = 2 if index == 5 else 5
                reacted_at = sent_at + timedelta(seconds=seconds_to_react)
            await create_reaction(
                conn,
                user_id=10001,
                meme_id=10000 + index,
                reaction_id=reaction_id,
                recommended_by="cold_start_explore" if index <= 5 else "cold_start_adapt",
                sent_at=sent_at,
                reacted_at=reacted_at,
            )

        for index, reaction_id in enumerate([2, 1], start=1):
            sent_at = T0 + timedelta(hours=2, minutes=index)
            await create_reaction(
                conn,
                user_id=10002,
                meme_id=10000 + index,
                reaction_id=reaction_id,
                recommended_by="cold_start_explore",
                sent_at=sent_at,
                reacted_at=sent_at + timedelta(seconds=5),
            )

        old_sent_at = T0 - timedelta(days=40)
        await create_reaction(
            conn,
            user_id=10003,
            meme_id=10020,
            reaction_id=1,
            recommended_by="goat",
            sent_at=old_sent_at,
            reacted_at=old_sent_at + timedelta(seconds=5),
        )
        await create_reaction(
            conn,
            user_id=10003,
            meme_id=10001,
            reaction_id=1,
            recommended_by="cold_start_explore",
            sent_at=T0 + timedelta(hours=3),
            reacted_at=T0 + timedelta(hours=3, seconds=5),
        )

        await create_reaction(
            conn,
            user_id=10004,
            meme_id=10020,
            reaction_id=1,
            recommended_by="share_link",
            sent_at=T0 + timedelta(hours=4),
            reacted_at=T0 + timedelta(hours=4, seconds=5),
        )
        await create_reaction(
            conn,
            user_id=10004,
            meme_id=10002,
            reaction_id=1,
            recommended_by="cold_start_explore",
            sent_at=T0 + timedelta(hours=4, minutes=1),
            reacted_at=T0 + timedelta(hours=4, minutes=1, seconds=5),
        )

        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)
        await conn.commit()


async def _fetch_section(section: ReadoutSection, **params):
    readout_params = cold_start_first10_quality_params(
        lookback_days=14,
        min_candidate_sends=params.get("min_candidate_sends", 1),
        candidate_limit=params.get("candidate_limit", 5),
    )
    return await fetch_all(build_cold_start_first10_quality_query(section), readout_params)


@pytest.mark.asyncio
async def test_summary_uses_true_new_cold_start_cohort(cold_start_readout_data):
    rows = await _fetch_section("summary")

    assert len(rows) == 1
    summary = rows[0]
    assert summary["cohort_users"] == 2
    assert summary["first_meme_sends"] == 2
    assert float(summary["first_meme_lr_pct"]) == 50.0
    assert float(summary["first_meme_continuation_pct"]) == 100.0
    assert summary["first10_sends"] == 12
    assert float(summary["first10_lr_pct"]) == pytest.approx(54.5)
    assert float(summary["first10_continuation_pct"]) == 75.0
    assert summary["reached5_users"] == 1
    assert summary["reached10_users"] == 1
    assert float(summary["second_session_pct"]) == 50.0


@pytest.mark.asyncio
async def test_per_position_uses_sent_at_order_and_skip_semantics(cold_start_readout_data):
    rows = await _fetch_section("per_position")
    by_position = {row["first10_position"]: row for row in rows}

    assert sorted(by_position) == list(range(1, 11))
    position_3 = by_position[3]
    assert position_3["users"] == 1
    assert position_3["unreacted"] == 1
    assert float(position_3["first10_quality_score"]) == pytest.approx(-0.3)
    assert float(position_3["continuation_pct"]) == 100.0

    position_5 = by_position[5]
    assert position_5["dislikes"] == 1
    assert float(position_5["first10_quality_score"]) == pytest.approx(-0.5)
    assert float(position_5["continuation_pct"]) == 0.0


@pytest.mark.asyncio
async def test_engine_segments_and_candidate_memes_are_exposed(cold_start_readout_data):
    engine_rows = await _fetch_section("per_engine")
    assert {row["engine"] for row in engine_rows} == {
        "cold_start_adapt",
        "cold_start_explore",
    }

    segment_rows = await _fetch_section("segments")
    segment_keys = {(row["segment_type"], row["segment_value"]) for row in segment_rows}
    assert ("meme_type", "image") in segment_keys
    assert ("meme_language", "ru") in segment_keys
    assert ("source", "https://t.me/source_ru") in segment_keys

    candidate_rows = await _fetch_section("candidate_memes", candidate_limit=2)
    assert {row["quality_bucket"] for row in candidate_rows} == {"top", "bottom"}
    assert all(row["meme_id"] >= 10001 for row in candidate_rows)
