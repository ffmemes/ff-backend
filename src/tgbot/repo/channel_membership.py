"""Persistence for known bot users; no Telegram calls or user registration."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from src.database import fetch_all, run_in_transaction, user_channel_membership


def utc_naive(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


async def _locked_record(conn, user_id: int, chat_id: int) -> dict | None:
    # INSERT SELECT never creates a bot user from an unrelated channel event.
    # Lock the owning user so deletion cannot race the membership FK insert.
    known = await conn.execute(
        text('SELECT id FROM "user" WHERE id=:user_id FOR KEY SHARE'), {"user_id": user_id}
    )
    if known.first() is None:
        return None
    await conn.execute(
        text("""
            INSERT INTO user_channel_membership (user_id, chat_id, ever_member, last_member_at)
            SELECT :user_id, :chat_id, EXISTS(
                SELECT 1 FROM user_tg_chat_membership
                WHERE user_tg_id=:user_id AND chat_id=:chat_id
            ), (SELECT last_seen_at FROM user_tg_chat_membership
                WHERE user_tg_id=:user_id AND chat_id=:chat_id)
            ON CONFLICT (user_id, chat_id) DO NOTHING
        """),
        {"user_id": user_id, "chat_id": chat_id},
    )
    row = await conn.execute(
        select(user_channel_membership)
        .where(
            user_channel_membership.c.user_id == user_id,
            user_channel_membership.c.chat_id == chat_id,
        )
        .with_for_update()
    )
    return dict(row.mappings().one())


async def _save(conn, user_id: int, chat_id: int, values: dict) -> None:
    await conn.execute(
        user_channel_membership.update()
        .where(
            user_channel_membership.c.user_id == user_id,
            user_channel_membership.c.chat_id == chat_id,
        )
        .values(**values)
    )
    if values.get("last_member_at") is not None:
        # Preserve positive-only legacy readers. A missing Telegram profile is
        # not registered merely because we observed a channel member.
        await conn.execute(
            text("""
            INSERT INTO user_tg_chat_membership (user_tg_id, chat_id, last_seen_at)
            SELECT id, :chat_id, :seen_at FROM user_tg WHERE id=:user_id
            ON CONFLICT (user_tg_id, chat_id) DO UPDATE SET
              last_seen_at=greatest(user_tg_chat_membership.last_seen_at, EXCLUDED.last_seen_at)
        """),
            {"user_id": user_id, "chat_id": chat_id, "seen_at": values["last_member_at"]},
        )


async def enqueue_user_membership(user_id: int, chat_ids: tuple[int, ...], conn=None) -> None:
    async def enqueue(connection):
        for chat_id in chat_ids:
            await _locked_record(connection, user_id, chat_id)

    if conn is not None:
        await enqueue(conn)
    else:
        await run_in_transaction(enqueue)


async def persist_event(
    user_id: int,
    chat_id: int,
    status: str,
    was_member: bool,
    event_at: datetime,
    update_id: int,
    *,
    received_at: datetime | None = None,
    refresh_hours: float = 24,
) -> bool:
    event_at, received_at = utc_naive(event_at), utc_naive(received_at)

    async def persist(conn):
        row = await _locked_record(conn, user_id, chat_id)
        if row is None:
            return False
        positive = status == "member" or was_member
        values = {"ever_member": row["ever_member"] or positive}
        if positive:
            values["last_member_at"] = max(row["last_member_at"] or event_at, event_at)
        newer = row["observed_at"] is None or event_at > row["observed_at"]
        if event_at == row["observed_at"]:
            newer = row["source"] != "event" or update_id > (
                row["last_event_update_id"] if row["last_event_update_id"] is not None else -1
            )
        if newer:
            values.update(
                status=status,
                observed_at=event_at,
                source="event",
                last_event_update_id=update_id,
                last_event_received_at=received_at,
                last_error=None,
                next_check_at=received_at + timedelta(hours=refresh_hours),
            )
        await _save(conn, user_id, chat_id, values)
        return newer

    return await run_in_transaction(persist)


async def persist_snapshot(
    user_id: int,
    chat_id: int,
    status: str,
    requested_at: datetime,
    *,
    finished_at: datetime | None = None,
    error: str | None = None,
    refresh_hours: float = 24,
    retry_seconds: float = 900,
) -> bool:
    requested_at, finished_at = utc_naive(requested_at), utc_naive(finished_at)
    # Telegram event dates have one-second precision. An event wins a tie with
    # an HTTP request from that same second, even if it arrives afterwards.
    observation = requested_at.replace(microsecond=0)

    async def persist(conn):
        row = await _locked_record(conn, user_id, chat_id)
        if row is None:
            return False
        values = {"ever_member": row["ever_member"] or status == "member"}
        if status == "member":
            values["last_member_at"] = max(row["last_member_at"] or observation, observation)
        event_raced = (
            row["last_event_received_at"] is not None
            and row["last_event_received_at"] >= requested_at
        )
        newer = row["observed_at"] is None or observation > row["observed_at"]
        if observation == row["observed_at"] and row["source"] != "event":
            newer = row["checked_at"] is None or requested_at >= row["checked_at"]
        if newer and not event_raced:
            values.update(
                status=status,
                observed_at=observation,
                source="snapshot",
                checked_at=requested_at,
                last_error=error,
                next_check_at=finished_at
                + (
                    timedelta(seconds=retry_seconds)
                    if status == "unknown"
                    else timedelta(hours=refresh_hours)
                ),
            )
        await _save(conn, user_id, chat_id, values)
        return newer and not event_raced

    return await run_in_transaction(persist)


async def due_memberships(
    chat_ids: tuple[int, ...],
    *,
    limit: int,
    active_days: int | None = 30,
) -> list[dict]:
    # Missing records form the durable bootstrap queue, including new users.
    # A bounded repair also revisits old observations after missed webhooks.
    return await fetch_all(
        text("""
        SELECT u.id AS user_id, channels.chat_id
        FROM "user" u CROSS JOIN unnest(CAST(:chat_ids AS bigint[])) channels(chat_id)
        LEFT JOIN user_channel_membership m
          ON m.user_id=u.id AND m.chat_id=channels.chat_id
        WHERE u.blocked_bot_at IS NULL
          AND (CAST(:active_days AS integer) IS NULL OR
               greatest(u.last_active_at,u.created_at)>=
                   timezone('UTC',now())-make_interval(days=>:active_days))
          AND (m.user_id IS NULL OR m.next_check_at<=timezone('UTC',now()))
        ORDER BY m.user_id IS NULL DESC,
                 greatest(u.last_active_at,u.created_at) DESC, u.id, channels.chat_id
        LIMIT :limit
    """),
        {"chat_ids": list(chat_ids), "active_days": active_days, "limit": limit},
    )


async def invalidate_channel(chat_id: int, *, when: datetime | None = None) -> None:
    when = utc_naive(when)

    async def invalidate(conn):
        await conn.execute(
            user_channel_membership.update()
            .where(
                user_channel_membership.c.chat_id == chat_id,
            )
            .values(
                status="unknown",
                source="access_lost",
                observed_at=when,
                last_error="not_administrator",
                next_check_at=when + timedelta(minutes=15),
            )
        )

    await run_in_transaction(invalidate)
