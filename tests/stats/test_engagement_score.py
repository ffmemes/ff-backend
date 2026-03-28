"""Tests for calculate_meme_reactions_and_engagement().

Engagement score assigns timing-weighted values to reactions and skips,
then applies user-bias smoothing (same running-average approach as lr_smoothed).

Reaction values:
    Like                          → +1.0
    Dislike, slow (>3s)           → -1.0
    Dislike, fast (≤3s)           → -0.5
    Dislike, timing unknown       → -1.0
    Skip (no reaction, user cont) → -0.3
    Last meme (unknowable)        → excluded
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (
    engine,
    fetch_all,
    meme,
    meme_source,
    meme_stats,
    user,
    user_meme_reaction,
)
from src.stats.meme import calculate_meme_reactions_and_engagement

EPS = 1e-3

T0 = datetime(2024, 6, 1, 12, 0, 0)


def _t(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest_asyncio.fixture()
async def conn():
    """Set up base entities: 15 users, 1 source, 20 memes."""
    async with engine.connect() as conn:
        await conn.execute(
            insert(user),
            [{"id": i, "type": "user"} for i in range(1, 16)],
        )
        await conn.execute(
            insert(meme_source),
            {
                "id": 1,
                "type": "telegram",
                "url": "https://t.me/test_es",
                "status": "parsing_enabled",
                "created_at": T0,
            },
        )
        meme_common = {
            "type": "image",
            "meme_source_id": 1,
            "status": "ok",
            "language_code": "ru",
            "published_at": T0,
        }
        await conn.execute(
            insert(meme),
            [{"id": i, "raw_meme_id": i, **meme_common} for i in range(1, 21)],
        )
        await conn.commit()
        yield conn

        await conn.execute(delete(meme_stats))
        await conn.execute(delete(user_meme_reaction))
        await conn.execute(delete(meme))
        await conn.execute(delete(meme_source))
        await conn.execute(delete(user))
        await conn.commit()


async def _get_engagement_score(meme_id: int) -> float | None:
    rows = await fetch_all(
        select(meme_stats.c.engagement_score).where(meme_stats.c.meme_id == meme_id)
    )
    if not rows:
        return None
    return rows[0]["engagement_score"]


async def _insert_reactions(conn, reactions: list[dict]):
    for r in reactions:
        r.setdefault("recommended_by", "test")
    await conn.execute(insert(user_meme_reaction), reactions)
    await conn.commit()


# ---- Basic value tests (threshold=0, same as lr_smoothed tests) ----


@pytest.mark.asyncio
async def test_like_value(conn):
    """All likes → engagement_score should be 0 (smoothing removes uniform bias)."""
    reactions = []
    for uid in range(1, 12):
        for mid in range(1, 12):
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": 1,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    score = await _get_engagement_score(1)
    assert score is not None
    # All likes, uniform → smoothed to ~0
    assert abs(score) < EPS


@pytest.mark.asyncio
async def test_slow_dislike_value(conn):
    """Slow dislikes (>3s) should produce lower scores than likes."""
    reactions = []
    for uid in range(1, 12):
        for mid in range(1, 12):
            rid = 2 if mid == 1 else 1
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": rid,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),  # all >3s (slow)
                }
            )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    score_disliked = await _get_engagement_score(1)
    score_liked = await _get_engagement_score(2)
    assert score_disliked is not None
    assert score_liked is not None
    assert score_disliked < score_liked


@pytest.mark.asyncio
async def test_fast_dislike_value(conn):
    """Fast dislikes (≤3s) should have a milder negative effect than slow dislikes."""
    reactions = []
    for uid in range(1, 12):
        for mid in range(1, 12):
            if mid == 1:
                # fast dislike (2 seconds)
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 2,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 2),
                    }
                )
            elif mid == 2:
                # slow dislike (5 seconds)
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 2,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 5),
                    }
                )
            else:
                # likes
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 1,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 5),
                    }
                )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    fast_dislike_score = await _get_engagement_score(1)
    slow_dislike_score = await _get_engagement_score(2)
    assert fast_dislike_score is not None
    assert slow_dislike_score is not None
    assert fast_dislike_score > slow_dislike_score


@pytest.mark.asyncio
async def test_dislike_timing_edge_cases(conn):
    """Dislikes outside 0.5-60s range default to slow dislike weight (-1.0)."""
    reactions = []
    for uid in range(1, 12):
        for mid in range(1, 12):
            if mid == 1:
                # Very fast (0.1s, outside range) → default -1.0
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 2,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 0.1),
                    }
                )
            elif mid == 2:
                # Very slow (120s, outside range) → default -1.0
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 2,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 120),
                    }
                )
            elif mid == 3:
                # Normal slow dislike (5s, within range) → -1.0
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 2,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 5),
                    }
                )
            else:
                reactions.append(
                    {
                        "user_id": uid,
                        "meme_id": mid,
                        "reaction_id": 1,
                        "sent_at": _t(uid * 100 + mid),
                        "reacted_at": _t(uid * 100 + mid + 5),
                    }
                )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    score_too_fast = await _get_engagement_score(1)
    score_too_slow = await _get_engagement_score(2)
    score_normal_slow = await _get_engagement_score(3)
    assert score_too_fast is not None
    assert score_too_slow is not None
    assert score_normal_slow is not None
    # All three should have similar scores (all are -1.0 weight)
    assert abs(score_too_fast - score_normal_slow) < EPS
    assert abs(score_too_slow - score_normal_slow) < EPS


@pytest.mark.asyncio
async def test_skip_detection(conn):
    """Memes sent but not reacted to (while user continues) count as skips."""
    reactions = []
    for uid in range(1, 12):
        # meme 1: sent first, no reaction (skip — user continues to other memes)
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 1,
                "reaction_id": None,
                "sent_at": _t(uid * 100),
                "reacted_at": None,
            }
        )
        # meme 2: liked (comparison)
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 2,
                "reaction_id": 1,
                "sent_at": _t(uid * 100 + 2),
                "reacted_at": _t(uid * 100 + 2 + 5),
            }
        )
        # memes 3-11: likes (background to establish user bias)
        for mid in range(3, 12):
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": 1,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    score_skipped = await _get_engagement_score(1)
    score_liked = await _get_engagement_score(2)
    assert score_skipped is not None
    assert score_liked is not None
    assert score_skipped < score_liked


@pytest.mark.asyncio
async def test_last_meme_excluded(conn):
    """Last meme in session (no reaction, no later activity) → excluded."""
    reactions = []
    for uid in range(1, 12):
        # memes 2-11: normal likes
        for mid in range(2, 12):
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": 1,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )
        # meme 1: sent AFTER all others, no reaction → last meme → excluded
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 1,
                "reaction_id": None,
                "sent_at": _t(uid * 100 + 99),
                "reacted_at": None,
            }
        )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    # meme 1: all rows are NULL (last meme per user) → excluded → no score
    score = await _get_engagement_score(1)
    assert score is None


@pytest.mark.asyncio
async def test_user_bias_smoothing(conn):
    """Smoothing removes per-user bias so universally-liked memes score higher."""
    reactions = []

    # User 1: likes ALL memes (high bias)
    for mid in range(1, 12):
        reactions.append(
            {
                "user_id": 1,
                "meme_id": mid,
                "reaction_id": 1,
                "sent_at": _t(mid),
                "reacted_at": _t(mid + 5),
            }
        )

    # User 2: dislikes ALL memes (low bias, slow dislikes)
    for mid in range(1, 12):
        reactions.append(
            {
                "user_id": 2,
                "meme_id": mid,
                "reaction_id": 2,
                "sent_at": _t(100 + mid),
                "reacted_at": _t(100 + mid + 5),
            }
        )

    # Users 3-11: like meme 1, dislike meme 2 (slow), mixed on others
    for uid in range(3, 12):
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 1,
                "reaction_id": 1,
                "sent_at": _t(uid * 100 + 1),
                "reacted_at": _t(uid * 100 + 1 + 5),
            }
        )
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 2,
                "reaction_id": 2,
                "sent_at": _t(uid * 100 + 2),
                "reacted_at": _t(uid * 100 + 2 + 5),
            }
        )
        for mid in range(3, 12):
            rid = 1 if mid % 2 == 0 else 2
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": rid,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )

    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    score_1 = await _get_engagement_score(1)
    score_2 = await _get_engagement_score(2)
    assert score_1 is not None
    assert score_2 is not None
    # Meme 1 (universally liked) should score higher than meme 2 (universally disliked)
    assert score_1 > score_2


# ---- Threshold tests ----


@pytest.mark.asyncio
async def test_min_user_threshold(conn):
    """Users with fewer reactions than min_user_reactions → excluded."""
    reactions = []
    # Users 1-3: only 2 reactions each (below threshold of 5)
    for uid in range(1, 4):
        for mid in [1, 2]:
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": 1,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=5, min_meme_reactions=0, lookback_hours=999_999)

    # No memes should get scores (all users below threshold)
    score = await _get_engagement_score(1)
    assert score is None


@pytest.mark.asyncio
async def test_min_meme_threshold(conn):
    """Memes with fewer qualifying reactions than min_meme_reactions → no score."""
    reactions = []
    # 11 users each react to memes 1-11
    for uid in range(1, 12):
        for mid in range(1, 12):
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": 1,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )
    # Only user 1 reacts to meme 20
    reactions.append(
        {
            "user_id": 1,
            "meme_id": 20,
            "reaction_id": 1,
            "sent_at": _t(200),
            "reacted_at": _t(205),
        }
    )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=3, lookback_hours=999_999)

    assert await _get_engagement_score(1) is not None
    # meme 20 has only 1 reaction < threshold 3
    assert await _get_engagement_score(20) is None


@pytest.mark.asyncio
async def test_all_skips_meme(conn):
    """A meme only ever skipped should get a negative score."""
    reactions = []
    for uid in range(1, 12):
        # memes 2-11: normal likes FIRST (establish positive user avg)
        for mid in range(2, 12):
            reactions.append(
                {
                    "user_id": uid,
                    "meme_id": mid,
                    "reaction_id": 1,
                    "sent_at": _t(uid * 100 + mid),
                    "reacted_at": _t(uid * 100 + mid + 5),
                }
            )
        # meme 1: sent AFTER likes, no reaction (skip)
        # Placed after other memes so running avg is established
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 1,
                "reaction_id": None,
                "sent_at": _t(uid * 100 + 50),
                "reacted_at": None,
            }
        )
        # one more like AFTER the skip to confirm user continued
        reactions.append(
            {
                "user_id": uid,
                "meme_id": 12,
                "reaction_id": 1,
                "sent_at": _t(uid * 100 + 60),
                "reacted_at": _t(uid * 100 + 65),
            }
        )
    await _insert_reactions(conn, reactions)
    await calculate_meme_reactions_and_engagement(min_user_reactions=0, min_meme_reactions=0, lookback_hours=999_999)

    score_all_skips = await _get_engagement_score(1)
    score_all_likes = await _get_engagement_score(2)
    assert score_all_skips is not None
    assert score_all_likes is not None
    assert score_all_skips < score_all_likes
    # Skip = -0.3, user avg is positive → smoothed skip is negative
    assert score_all_skips < 0
