"""Friend challenge storage invariants against the disposable test database."""

import asyncio
import re
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from tests.factories import (
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_reaction,
    create_user,
    create_user_language,
)

from src.database import (
    engine,
    experiment_assignment,
    friend_challenge_item,
    friend_challenge_pack,
    meme,
    meme_source,
    user,
    user_meme_reaction,
)
from src.tgbot.repo import friend_challenge as repo

OWNER = 1_650_001
FRIEND = 1_650_002
OTHER = 1_650_003
SOURCE = 1_650_010
MEME = 1_650_100
MEMES = list(range(MEME, MEME + 10))


async def _cleanup(conn):
    await conn.execute(delete(user).where(user.c.id.in_([OWNER, FRIEND, OTHER])))
    await conn.execute(delete(meme).where(meme.c.id.between(MEME, MEME + 100)))
    await conn.execute(delete(meme_source).where(meme_source.c.id.in_([SOURCE, SOURCE + 1])))


@pytest_asyncio.fixture(autouse=True)
async def data(monkeypatch):
    # Daily eligibility gate lives in Redis; tests exercise the SQL path every time.
    monkeypatch.setattr(repo.redis, "redis_client", AsyncMock(set=AsyncMock(return_value=True)))
    async with engine.begin() as conn:
        await _cleanup(conn)
        for user_id in (OWNER, FRIEND, OTHER):
            await create_user(conn, user_id)
            await create_user_language(conn, user_id, "ru")
        await create_meme_source(conn, SOURCE)
        await create_meme_source(conn, SOURCE + 1)
        for meme_id in MEMES:
            await create_meme(conn, meme_id, SOURCE, telegram_file_id=f"fc-file-{meme_id}")
    yield
    async with engine.begin() as conn:
        await _cleanup(conn)


async def _confirmed_pack(owner_id: int = OWNER) -> dict:
    pack = await repo.get_or_create_owner_pack(owner_id, MEMES[:5])
    return await repo.confirm_owner_pack(owner_id, pack["id"])


async def _metadata(user_id: int = OWNER) -> dict:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                select(experiment_assignment.c.assignment_metadata).where(
                    experiment_assignment.c.user_id == user_id,
                    experiment_assignment.c.experiment_id == repo.EXPERIMENT_ID,
                )
            )
        ).scalar_one()


async def _activity(user_id: int, days: int, likes_per_day: int = 3, *, type_="user"):
    async with engine.begin() as conn:
        await conn.execute(update(user).where(user.c.id == user_id).values(type=type_))
        offset = 20
        for day in range(days):
            for _ in range(likes_per_day):
                await create_meme(conn, MEME + offset, SOURCE)
                await create_reaction(
                    conn,
                    user_id,
                    MEME + offset,
                    reaction_id=1,
                    recommended_by="lr_smoothed",
                    reacted_at=datetime.utcnow().replace(hour=0, minute=30)
                    - timedelta(days=day, seconds=offset),
                )
                offset += 1


# --- packs and answers ---


async def test_pack_needs_owner_confirmation_before_public_lookup():
    pack = await repo.get_or_create_owner_pack(OWNER, MEMES[:5])
    assert re.fullmatch(r"[A-Za-z0-9_-]{24}", pack["token"])
    assert [item["meme_id"] for item in pack["items"]] == MEMES[:5]
    assert await repo.get_public_pack(pack["token"]) is None
    assert await repo.confirm_owner_pack(FRIEND, pack["id"]) is None
    assert await repo.start_participation(pack["id"], FRIEND) is None

    confirmed = await repo.confirm_owner_pack(OWNER, pack["id"])
    assert confirmed["confirmed_at"] is not None
    assert (await repo.get_public_pack(pack["token"]))["id"] == pack["id"]
    assert (await repo.confirm_owner_pack(OWNER, pack["id"]))["confirmed_at"] == confirmed[
        "confirmed_at"
    ]
    assert await repo.get_or_create_owner_pack(OWNER, MEMES[5:]) == confirmed


async def test_concurrent_creation_has_one_pack_and_five_fixed_items():
    packs = await asyncio.gather(
        *(repo.get_or_create_owner_pack(OWNER, ids) for ids in [MEMES[:5], MEMES[5:]] * 4)
    )
    assert len({pack["id"] for pack in packs}) == 1
    assert len({tuple(i["meme_id"] for i in pack["items"]) for pack in packs}) == 1
    async with engine.connect() as conn:
        items = await conn.execute(
            select(friend_challenge_item).where(friend_challenge_item.c.pack_id == packs[0]["id"])
        )
        assert len(items.all()) == 5


@pytest.mark.parametrize("ids", [MEMES[:4], MEMES[:4] + MEMES[:1], MEMES[:4] + [-1]])
async def test_invalid_collection_never_leaves_a_partial_pack(ids):
    with pytest.raises(ValueError):
        await repo.get_or_create_owner_pack(OWNER, ids)
    assert await repo.get_owner_pack(OWNER) is None


async def test_removed_content_keeps_slot_but_cannot_start():
    pack = await _confirmed_pack()
    async with engine.begin() as conn:
        await conn.execute(delete(meme).where(meme.c.id == MEMES[0]))
    saved = await repo.get_pack(pack["id"])
    assert len(saved["items"]) == 5 and saved["items"][0]["meme_id"] is None
    assert await repo.start_participation(pack["id"], FRIEND) is None


async def test_answers_require_confirmed_non_owner_participation_and_current_position():
    pack = await _confirmed_pack()
    assert await repo.start_participation(pack["id"], OWNER) is None
    assert await repo.record_answer(pack["id"], FRIEND, 1, True) == {
        "changed": False,
        "progress": None,
    }
    first = await repo.start_participation(pack["id"], FRIEND)
    assert first["next_position"] == 1 and first["answered_count"] == 0
    assert await repo.start_participation(pack["id"], FRIEND) == first
    assert not (await repo.record_answer(pack["id"], FRIEND, 2, True))["changed"]
    assert not (await repo.record_answer(pack["id"], OTHER, 1, True))["changed"]
    answer = await repo.record_answer(pack["id"], FRIEND, 1, True)
    assert answer["changed"] and answer["progress"]["next_position"] == 2
    assert (await repo.start_participation(pack["id"], FRIEND))["started_at"] == first["started_at"]


async def test_concurrent_opposite_answers_advance_once():
    pack = await _confirmed_pack()
    await repo.start_participation(pack["id"], FRIEND)
    results = await asyncio.gather(
        *(repo.record_answer(pack["id"], FRIEND, 1, liked) for liked in [True, False] * 5),
        return_exceptions=True,
    )
    assert sum(r["changed"] for r in results if isinstance(r, dict)) == 1
    assert (await repo.get_progress(pack["id"], FRIEND))["answered_count"] == 1


async def test_completion_after_five_answers_and_replay_is_inert():
    pack = await _confirmed_pack()
    await repo.start_participation(pack["id"], FRIEND)
    for position in range(1, 6):
        result = await repo.record_answer(pack["id"], FRIEND, position, position % 2 == 1)
        assert result["changed"]
        assert (result["progress"]["completed_at"] is not None) == (position == 5)
    completed = result["progress"]
    assert completed["liked_count"] == 3 and completed["next_position"] is None
    assert not (await repo.record_answer(pack["id"], FRIEND, 5, False))["changed"]
    assert await repo.get_progress(pack["id"], FRIEND) == completed


async def test_seeding_answers_keeps_existing_history():
    pack = await _confirmed_pack()
    previous = datetime(2026, 1, 1)
    async with engine.begin() as conn:
        await create_reaction(
            conn, FRIEND, MEMES[0], reaction_id=2, recommended_by="lr_smoothed", reacted_at=previous
        )
    await repo.start_participation(pack["id"], FRIEND)
    for position, liked in enumerate([True, True, False], start=1):
        await repo.record_answer(pack["id"], FRIEND, position, liked)
    await repo.seed_answers_as_reactions(pack["id"], OWNER)  # not the owner's answers
    await repo.seed_answers_as_reactions(pack["id"], FRIEND)
    await repo.seed_answers_as_reactions(pack["id"], FRIEND)
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(user_meme_reaction).where(
                        user_meme_reaction.c.user_id.in_([OWNER, FRIEND])
                    )
                )
            )
            .mappings()
            .all()
        )
    by_meme = {row["meme_id"]: row for row in rows}
    assert {row["user_id"] for row in rows} == {FRIEND}
    assert set(by_meme) == set(MEMES[:3])
    assert by_meme[MEMES[0]]["recommended_by"] == "lr_smoothed"
    assert by_meme[MEMES[0]]["reacted_at"] == previous
    assert by_meme[MEMES[1]]["recommended_by"] == "friend_challenge"
    assert by_meme[MEMES[1]]["reaction_id"] == 1
    assert by_meme[MEMES[2]]["reaction_id"] == 2


async def test_owner_removal_cascades_game():
    pack = await _confirmed_pack()
    await repo.start_participation(pack["id"], FRIEND)
    await repo.record_answer(pack["id"], FRIEND, 1, True)
    async with engine.begin() as conn:
        await conn.execute(delete(user).where(user.c.id == OWNER))
        assert (
            await conn.execute(
                select(friend_challenge_pack).where(friend_challenge_pack.c.id == pack["id"])
            )
        ).first() is None


# --- candidates ---


async def test_candidates_keep_personal_likes_ahead_of_quality_and_vary_sources():
    async with engine.begin() as conn:
        await conn.execute(delete(meme).where(meme.c.id.in_(MEMES)))
        for offset in range(6):
            await create_meme(
                conn, MEME + offset, SOURCE + (offset == 5), telegram_file_id=f"fc-l-{offset}"
            )
            await create_meme_stats(conn, MEME + offset, nlikes=30, ndislikes=10)
            await create_reaction(
                conn,
                OWNER,
                MEME + offset,
                reaction_id=1,
                recommended_by="lr_smoothed",
                reacted_at=datetime.utcnow() - timedelta(seconds=offset),
            )
        await create_meme(conn, MEME + 6, SOURCE, telegram_file_id="fc-l-6")
        await create_meme_stats(conn, MEME + 6, nlikes=1000, ndislikes=1, lr_smoothed=0.9)

    assert await repo.candidate_meme_ids(OWNER) == [MEME, MEME + 5, MEME + 1, MEME + 2, MEME + 3]


async def test_fallback_excludes_disliked_invalid_or_other_language():
    async with engine.begin() as conn:
        await conn.execute(delete(meme).where(meme.c.id.in_(MEMES)))
        specs = [
            {},
            {},
            {},
            {"status": "rejected"},
            {"telegram_file_id": ""},
            {"language_code": "en"},
            {"type": "unsupported"},
            {},
        ]
        for offset, kwargs in enumerate(specs):
            kwargs.setdefault("telegram_file_id", f"fc-c-{offset}")
            await create_meme(conn, MEME + offset, SOURCE, **kwargs)
            await create_meme_stats(conn, MEME + offset, nlikes=30, ndislikes=10)
        await create_reaction(conn, OWNER, MEME + 7, reaction_id=2, recommended_by="lr_smoothed")
    assert set(await repo.candidate_meme_ids(OWNER)) == {MEME, MEME + 1, MEME + 2}


# --- assignment, offer, authorization ---


def test_variant_split_is_deterministic_and_about_ninety_ten():
    variants = [repo.variant_for_user(user_id) for user_id in range(10_000)]
    assert variants == [repo.variant_for_user(user_id) for user_id in range(10_000)]
    assert 800 < variants.count(repo.HOLDOUT) < 1200


async def test_inactive_user_is_not_assigned():
    await _activity(OWNER, days=7)
    assert await repo.get_or_assign_variant(OWNER) is None


@pytest.mark.parametrize("type_", ["user", "moderator"])
async def test_active_users_and_moderators_are_assigned_once(type_):
    await _activity(OWNER, days=8, type_=type_)
    first = await repo.get_or_assign_variant(OWNER)
    assert first["variant"] == repo.variant_for_user(OWNER)
    assert first["assignment_metadata"]["active_days_28d"] == 8
    assert first["assignment_metadata"]["likes_28d"] == 24
    assert await repo.get_or_assign_variant(OWNER) == first


@pytest.mark.parametrize("type_", ["admin", "blocked_bot"])
async def test_admins_and_blocked_users_are_not_assigned(type_):
    await _activity(OWNER, days=8, type_=type_)
    assert await repo.get_or_assign_variant(OWNER) is None


async def test_daily_gate_skips_the_eligibility_query(monkeypatch):
    monkeypatch.setattr(repo.redis.redis_client, "set", AsyncMock(return_value=None))
    monkeypatch.setattr(repo, "fetch_one", AsyncMock(side_effect=AssertionError("queried")))
    assert await repo.get_or_assign_variant(OWNER) is None


async def _assign(user_id=OWNER, variant=repo.TREATMENT):
    async with engine.begin() as conn:
        await conn.execute(
            insert(experiment_assignment).values(
                experiment_id=repo.EXPERIMENT_ID,
                user_id=user_id,
                variant=variant,
                assignment_metadata={"keep": "me"},
            )
        )


async def test_offer_claim_is_one_shot_and_treatment_only():
    await _assign()
    await _assign(FRIEND, repo.HOLDOUT)
    assert not await repo.claim_offer(FRIEND, MEMES[0])
    attempts = await asyncio.gather(*(repo.claim_offer(OWNER, MEMES[0]) for _ in range(4)))
    assert sum(attempts) == 1
    metadata = await _metadata()
    assert "offer_attempted_at" in metadata and "offered_at" not in metadata
    await repo.mark_offer_sent(OWNER)
    await repo.mark_offer_sent(OWNER)
    saved = await _metadata()
    assert saved["keep"] == "me" and "offered_at" in saved
    assert saved["offer_attempted_at"] == metadata["offer_attempted_at"]


async def test_creation_rights_assignment_precedes_completion():
    assert not await repo.authorized_to_create(OWNER)
    await _assign(OWNER, repo.TREATMENT)
    assert await repo.authorized_to_create(OWNER)

    pack = await _confirmed_pack(OWNER)
    await repo.start_participation(pack["id"], FRIEND)
    await repo.start_participation(pack["id"], OTHER)
    for position in range(1, 6):
        await repo.record_answer(pack["id"], FRIEND, position, True)
        await repo.record_answer(pack["id"], OTHER, position, True)
    assert await repo.authorized_to_create(FRIEND)  # unassigned and completed
    await _assign(OTHER, repo.HOLDOUT)
    assert not await repo.authorized_to_create(OTHER)  # holdout stays clean
