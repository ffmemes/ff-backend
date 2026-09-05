"""Readout semantics; run only with the repository's disposable test database."""

from datetime import datetime, timedelta

import pytest
from scripts.channel_hit_experiment import READOUT_SQL
from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert
from tests.factories import create_meme, create_meme_source

from src.database import engine, experiment_assignment, user, user_deep_link_log, user_meme_reaction

START = datetime(2026, 1, 1)
TEST_EXPERIMENT = "test_channel_hits_readout"
HOST_T, HOST_C, HOST_ZERO = 990001, 990002, 990003


@pytest.fixture
async def conn():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            await connection.execute(
                insert(user),
                [
                    {"id": uid, "type": "user", "created_at": START - timedelta(days=1)}
                    for uid in range(990001, 990025)
                ],
            )
            await create_meme_source(connection, id=990001)
            for meme_id in range(990101, 990125):
                await create_meme(connection, meme_id, meme_source_id=990001)
            for uid, variant in (
                (HOST_T, "treatment"),
                (HOST_C, "control"),
                (HOST_ZERO, "treatment"),
            ):
                await connection.execute(
                    insert(experiment_assignment).values(
                        experiment_id=TEST_EXPERIMENT,
                        user_id=uid,
                        variant=variant,
                        assigned_at=START,
                        assignment_metadata={
                            "experiment_start_at": "2026-01-01T00:00:00Z",
                            "exposure_end_at": "2026-01-15T00:00:00Z",
                            "reactions_28d": 100,
                            "active_days_28d": 10,
                        },
                    )
                )
            yield connection
        finally:
            await transaction.rollback()


async def acquire(conn, guest, host, day=0):
    await conn.execute(
        update(user)
        .where(user.c.id == guest)
        .values(inviter_id=host, created_at=START + timedelta(days=day))
    )


async def react(conn, uid, meme_id, day, origin="goat", reaction_id=1):
    await conn.execute(
        insert(user_meme_reaction)
        .values(
            user_id=uid,
            meme_id=meme_id,
            sent_at=START + timedelta(days=day),
            reacted_at=START + timedelta(days=day),
            reaction_id=reaction_id,
            recommended_by=origin,
        )
        .on_conflict_do_nothing()
    )


async def outcome(conn, day=28):
    sql = READOUT_SQL.read_text().replace("$1::timestamp", "CAST(:as_of AS timestamp)")
    sql = sql.replace("$2", ":experiment_id")
    rows = (
        await conn.execute(
            text(sql), {"as_of": START + timedelta(days=day), "experiment_id": TEST_EXPERIMENT}
        )
    ).mappings()
    return {row["variant"]: dict(row) for row in rows}


async def test_zero_exposure_hosts_stay_in_denominator_and_link_recipients_deduplicate(conn):
    await acquire(conn, 990010, HOST_T)
    for mid in range(990101, 990104):
        await react(conn, 990010, mid, day=7)
    for host in (HOST_T, HOST_T, HOST_ZERO):
        await conn.execute(
            insert(user_deep_link_log).values(
                user_id=990010, deep_link=f"m_{host}_990101", created_at=START + timedelta(days=1)
            )
        )
    await conn.execute(
        insert(user_deep_link_log).values(
            user_id=HOST_T, deep_link=f"m_{HOST_T}_990101", created_at=START + timedelta(days=1)
        )
    )
    await react(conn, HOST_T, 990105, day=1, origin="channel_hit_v1")
    await react(conn, HOST_C, 990105, day=1)
    result = (await outcome(conn))["treatment"]
    assert result["assigned_users"] == 2
    assert result["exposed_users"] == 1
    assert result["hit_delivery_rows"] == 1
    assert result["new_invitees"] == 1
    assert result["retained_invitees"] == 1
    assert result["retained_invitees_per_100_assigned"] == 50
    assert result["nonself_start_events"] == 3
    assert result["unique_nonself_recipients"] == 1
    assert result["seeds_with_nonself_start"] == 2


async def test_guest_window_is_complete_before_retention_and_acquisition_end_exclusive(conn):
    await acquire(conn, 990010, HOST_T, day=13)
    await acquire(conn, 990011, HOST_T, day=14)
    for guest in (990010, 990011):
        for mid in range(990101, 990104):
            await react(conn, guest, mid, day=21)
    pending = (await outcome(conn, day=22))["treatment"]
    assert pending["new_invitees"] == 1
    assert pending["pending_invitee_followups"] == 1
    assert pending["retained_invitees"] == 0
    assert (await outcome(conn))["treatment"]["retained_invitees"] == 1


async def test_retention_excludes_push_game_and_synthetic_reactions(conn):
    await acquire(conn, 990010, HOST_T)
    await react(conn, 990010, 990101, day=7)
    await react(conn, 990010, 990102, day=8, reaction_id=2)
    for offset, origin in enumerate(
        ("broadcast_reengagement", "uploaded_meme", "low_sent_pool", "friend_challenge")
    ):
        await react(conn, 990010, 990103 + offset, day=9, origin=origin)
    await react(conn, HOST_T, 990120, day=8, origin="broadcast_reengagement")
    before = (await outcome(conn))["treatment"]
    assert before["retained_invitees"] == 0
    assert before["hosts_active_d7_13"] == 0
    await react(conn, 990010, 990107, day=13)
    await react(conn, HOST_T, 990121, day=13)
    after = (await outcome(conn))["treatment"]
    assert after["retained_invitees"] == 1
    assert after["hosts_active_d7_13"] == 1
