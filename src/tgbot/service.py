import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import bindparam, exists, select, text
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    experiment_assignment,
    fetch_all,
    fetch_one,
    inline_search_chosen_result_logs,
    inline_search_logs,
    meme,
    meme_source,
    meme_source_candidate,
    meme_source_stats,
    meme_stats,
    user,
    user_deep_link_log,
    user_language,
    user_popup_logs,
    user_tg,
    user_tg_chat_membership,
)
from src.storage.constants import MemeSourceStatus, MemeStatus, MemeType
from src.tgbot.constants import UserType


async def save_tg_user(
    id: int,
    **kwargs,
) -> None:
    filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}

    insert_statement = (
        insert(user_tg)
        .values({"id": id, **filtered_kwargs})
        .on_conflict_do_update(
            index_elements=(user_tg.c.id,),
            set_={"updated_at": datetime.utcnow(), **filtered_kwargs},
        )
    )

    await execute(insert_statement)


async def create_or_update_user(
    id: int,
) -> tuple[dict, bool]:
    """
    Creates or updates a row in user table.
    Returns tuple of (user dict, bool) where bool
    indicates if user was created (True) or updated (False).
    """
    sql = f"""
        WITH upsert AS (
            INSERT
            INTO "user"
            (id, type, last_active_at)
            VALUES ({id}, '{UserType.USER.value}', NOW())
            ON CONFLICT(id)
            DO UPDATE SET
                blocked_bot_at = NULL,
                last_active_at = NOW(),
                type = CASE
                    WHEN "user".type = '{UserType.BLOCKED_BOT.value}'
                        THEN '{UserType.USER.value}'
                    ELSE "user".type
                END
            RETURNING "user".*, (xmax = 0) as created
        )
        SELECT *, created FROM upsert
    """

    result = await fetch_one(text(sql))
    created = result.pop("created")
    return result, created


async def get_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user).where(user.c.id == id)
    return await fetch_one(select_statement)


async def get_tg_user_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(user_tg).where(user_tg.c.id == id)
    return await fetch_one(select_statement)


async def get_meme_source_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme_source).where(meme_source.c.id == id)
    return await fetch_one(select_statement)


async def get_meme_source_stats_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme_source_stats).where(meme_source_stats.c.meme_source_id == id)
    return await fetch_one(select_statement)


async def get_meme_by_id(
    id: int,
) -> dict[str, Any] | None:
    select_statement = select(meme).where(meme.c.id == id)
    return await fetch_one(select_statement)


async def get_or_create_meme_source(
    url: str,
    **kwargs,
) -> dict[str, Any] | None:
    insert_statement = (
        insert(meme_source)
        .values({"url": url, **kwargs})
        .on_conflict_do_update(
            index_elements=(meme_source.c.url,),
            set_={"updated_at": datetime.utcnow()},
        )
        .returning(meme_source)
    )

    return await fetch_one(insert_statement)


async def update_meme_source(
    id: int,
    **kwargs,
) -> dict[str, Any] | None:
    update_statement = (
        meme_source.update()
        .where(meme_source.c.id == id)
        .values({"updated_at": datetime.utcnow(), **kwargs})
        .returning(meme_source)
    )

    return await fetch_one(update_statement)


async def list_pending_source_candidates(limit: int = 20) -> list[dict[str, Any]]:
    # Exclude candidates whose URL was added to meme_source via the manual URL
    # flow — discovery's own dedup only fires at insert time, so without this
    # filter such rows re-surface in /discoveredsources forever.
    select_statement = (
        select(meme_source_candidate)
        .where(meme_source_candidate.c.status == "discovered")
        .where(~select(1).where(meme_source.c.url == meme_source_candidate.c.url).exists())
        .order_by(meme_source_candidate.c.times_forwarded.desc())
        .limit(limit)
    )
    return await fetch_all(select_statement)


async def get_source_candidate_by_id(id: int) -> dict[str, Any] | None:
    select_statement = select(meme_source_candidate).where(meme_source_candidate.c.id == id)
    return await fetch_one(select_statement)


async def dismiss_source_candidate(
    id: int,
    reason: str = "moderator",
) -> dict[str, Any] | None:
    update_statement = (
        meme_source_candidate.update()
        .where(meme_source_candidate.c.id == id)
        .where(meme_source_candidate.c.status == "discovered")
        .values(
            status="dismissed",
            dismissed_reason=reason,
            updated_at=datetime.utcnow(),
        )
        .returning(meme_source_candidate)
    )
    return await fetch_one(update_statement)


async def promote_source_candidate(
    candidate_id: int,
    added_by_user_id: int,
) -> dict[str, Any] | None:
    """Promote a candidate into `meme_source` with `status=in_moderation`.

    Idempotent: if the URL already exists in `meme_source`, returns that row
    and marks the candidate as promoted. Never auto-enables parsing — the
    moderator still has to flip status via the existing admin pipeline.
    """
    candidate = await get_source_candidate_by_id(candidate_id)
    if candidate is None or candidate["status"] != "discovered":
        return None

    insert_statement = (
        insert(meme_source)
        .values(
            {
                "url": candidate["url"],
                "type": candidate["type"],
                "status": MemeSourceStatus.IN_MODERATION.value,
                "added_by": added_by_user_id,
            }
        )
        .on_conflict_do_update(
            index_elements=(meme_source.c.url,),
            set_={"updated_at": datetime.utcnow()},
        )
        .returning(meme_source)
    )
    promoted = await fetch_one(insert_statement)
    if promoted is None:
        return None

    # Status guard prevents TOCTOU between concurrent moderator clicks: two
    # callers can both pass the existence check, both insert into meme_source
    # (one no-ops via on_conflict_do_nothing), but without this WHERE the
    # second UPDATE would silently overwrite a `rejected` / `dismissed` status
    # set by another moderator in the gap. With the guard, the trailing UPDATE
    # is a no-op once the candidate has been resolved.
    await execute(
        meme_source_candidate.update()
        .where(meme_source_candidate.c.id == candidate_id)
        .where(meme_source_candidate.c.status == "discovered")
        .values(
            status="promoted",
            promoted_meme_source_id=promoted["id"],
            updated_at=datetime.utcnow(),
        )
    )
    return promoted


async def search_memes_for_inline_query(search_query: str, limit: int) -> list[dict[str, Any]]:
    select_query = f"""
        SELECT
            M.*
        FROM meme M
        WHERE M.status = '{MemeStatus.OK}'
        AND M.type = '{MemeType.IMAGE}'
        AND M.ocr_result IS NOT NULL
        ORDER BY word_similarity(:search_query, M.ocr_result ->> 'text') DESC
        LIMIT {limit};
    """
    select_statement = text(select_query).bindparams(bindparam("search_query", value=search_query))

    return await fetch_all(select_statement)


async def get_user_languages(
    user_id: int,
) -> set[str]:
    select_statement = select(user_language).where(user_language.c.user_id == user_id)
    rows = await fetch_all(select_statement)
    return set(row["language_code"] for row in rows)


async def add_user_language(
    user_id: int,
    language_code: str,
) -> None:
    insert_language_query = (
        insert(user_language)
        .values({"user_id": user_id, "language_code": language_code})
        .on_conflict_do_nothing(
            index_elements=(user_language.c.user_id, user_language.c.language_code)
        )
    )

    await execute(insert_language_query)


async def add_user_languages(
    user_id: int,
    language_codes: Sequence[str],
) -> None:
    # Prepare a list of dictionaries where each dictionary represents
    # the values to be inserted for one row.
    values_to_insert = [
        {"user_id": user_id, "language_code": language_code} for language_code in language_codes
    ]

    insert_language_query = (
        insert(user_language)
        .values(values_to_insert)
        .on_conflict_do_nothing(
            index_elements=(user_language.c.user_id, user_language.c.language_code)
        )
    )

    await execute(insert_language_query)


async def del_user_language(
    user_id: int,
    language_code: str,
) -> None:
    delete_language_query = (
        user_language.delete()
        .where(user_language.c.user_id == user_id)
        .where(user_language.c.language_code == language_code)
    )

    await execute(delete_language_query)


async def add_user_tg_chat_membership(
    user_tg_id: int,
    chat_id: int,
) -> None:
    insert_query = (
        insert(user_tg_chat_membership)
        .values({"user_tg_id": user_tg_id, "chat_id": chat_id})
        .on_conflict_do_update(
            index_elements=(
                user_tg_chat_membership.c.user_tg_id,
                user_tg_chat_membership.c.chat_id,
            ),
            set_={"last_seen_at": datetime.utcnow()},
        )
    )

    await execute(insert_query)


async def get_user_info(
    user_id: int,
) -> dict[str, Any] | None:
    # TODO: calculate memes_watched_today inside user_stats
    # TODO: not sure about logic behind interface_lang
    query = f"""
        WITH MEMES_WATCHED_TODAY AS (
            SELECT user_id, COUNT(*) memes_watched_today
            FROM user_meme_reaction
            WHERE 1=1
                AND reacted_at >= DATE(NOW())
                AND user_id = {user_id}
            GROUP BY 1
        ),
        USER_INTERFACE_LANG AS (
            SELECT DISTINCT ON (user_id)
                user_id,
                language_code AS interface_lang,
                CASE
                    WHEN language_code = 'en' THEN 0
                    WHEN language_code = 'ru' THEN 1
                    ELSE 2
                END score
            FROM user_language UL
            WHERE user_id = {user_id}
            ORDER BY 1, 3 DESC
        )

        SELECT
            type,
            COALESCE(nmemes_sent, 0) nmemes_sent,
            COALESCE(memes_watched_today, 0) memes_watched_today,
            UIL.interface_lang
        FROM "user" AS U
        LEFT JOIN user_stats US
            ON US.user_id = U.id
        LEFT JOIN USER_INTERFACE_LANG UIL
            ON UIL.user_id = U.id
        LEFT JOIN MEMES_WATCHED_TODAY
            ON MEMES_WATCHED_TODAY.user_id = U.id
        WHERE U.id = {user_id}
    """

    return await fetch_one(text(query))


async def get_meme_stats(meme_id: int) -> dict[str, Any] | None:
    select_statement = select(meme_stats).where(meme_stats.c.meme_id == meme_id)
    return await fetch_one(select_statement)


async def get_meme_stats_for_meme_ids(meme_ids: list[int]) -> list[dict[str, Any]]:
    select_statement = select(meme_stats).where(meme_stats.c.meme_id.in_(meme_ids))
    return await fetch_all(select_statement)


async def update_user(user_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = user.update().where(user.c.id == user_id).values(**kwargs).returning(user)
    return await fetch_one(update_query)


async def mark_user_blocked(
    user_id: int,
    source: str,
    when: datetime | None = None,
) -> dict[str, Any] | None:
    """Mark a user as having blocked the bot.

    Idempotent. Preserves privileged roles (moderator/admin/super_user) —
    still records blocked_bot_at for retention analysis, but does not
    demote their type. Invalidates user_info cache on success.

    `source` is a free-form label for observability
    ("my_chat_member", "forbidden_send_meme", ...).
    `when` should be the Telegram event date when available
    (update.my_chat_member.date); otherwise defaults to utcnow().
    """
    from src.tgbot.user_info import update_user_info_cache  # avoid cycle

    current = await get_user_by_id(user_id)
    if current is None:
        return None

    # blocked_bot_at is TIMESTAMP WITHOUT TIME ZONE; asyncpg on Py 3.14 rejects
    # tz-aware values. Telegram's update.my_chat_member.date is tz-aware UTC,
    # so strip tzinfo (preserving the wall-clock UTC moment).
    if when is None:
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
    elif when.tzinfo is not None:
        ts = when.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        ts = when
    current_type = UserType(current["type"]) if current["type"] else None

    if current_type and current_type.is_moderator:
        logging.warning(
            "User #%s blocked via %s but is privileged (type=%s); "
            "recording blocked_bot_at, NOT demoting type",
            user_id,
            source,
            current_type.value,
        )
        updated = await update_user(user_id, blocked_bot_at=ts)
    else:
        updated = await update_user(
            user_id,
            type=UserType.BLOCKED_BOT,
            blocked_bot_at=ts,
        )

    if updated is not None:
        try:
            await update_user_info_cache(user_id)
        except Exception as exc:
            logging.warning(
                "Cache refresh failed for user #%s after block: %s",
                user_id,
                exc,
            )
        logging.info("User #%s blocked (source=%s)", user_id, source)

    return updated


async def mark_user_unblocked(
    user_id: int,
    source: str,
    when: datetime | None = None,
) -> dict[str, Any] | None:
    """Mark a user as having unblocked the bot.

    Always clears blocked_bot_at. Restores type to 'user' only if the
    user was currently 'blocked_bot' — privileged roles left alone.
    Invalidates user_info cache on success.
    """
    from src.tgbot.user_info import update_user_info_cache  # avoid cycle

    current = await get_user_by_id(user_id)
    if current is None:
        return None

    update_kwargs: dict[str, Any] = {"blocked_bot_at": None}
    if current["type"] == UserType.BLOCKED_BOT.value:
        update_kwargs["type"] = UserType.USER.value

    updated = await update_user(user_id, **update_kwargs)

    if updated is not None:
        try:
            await update_user_info_cache(user_id)
        except Exception as exc:
            logging.warning(
                "Cache refresh failed for user #%s after unblock: %s",
                user_id,
                exc,
            )
        logging.info("User #%s unblocked (source=%s)", user_id, source)

    return updated


async def user_popup_already_sent(
    user_id: int,
    popup_id: str,
) -> bool:
    exists_statement = (
        exists(user_popup_logs)
        .where(user_popup_logs.c.user_id == user_id)
        .where(user_popup_logs.c.popup_id == popup_id)
        .select()
    )
    res = await execute(exists_statement)
    return res.scalar()


async def create_user_popup_log(
    user_id: int,
    popup_id: str,
) -> bool:
    # Returns True if a new row was inserted (caller "won the lease"), False if a
    # row already existed. Callers that need atomic single-fire semantics can use
    # the return value as a lease — see maybe_send_first_meme_nudge.
    insert_query = (
        insert(user_popup_logs)
        .values(
            user_id=user_id,
            popup_id=popup_id,
        )
        .on_conflict_do_nothing(
            index_elements=(user_popup_logs.c.user_id, user_popup_logs.c.popup_id)
        )
    )
    result = await execute(insert_query)
    return result.rowcount > 0


async def delete_user_popup_log(
    user_id: int,
    popup_id: str,
) -> None:
    await execute(
        user_popup_logs.delete()
        .where(user_popup_logs.c.user_id == user_id)
        .where(user_popup_logs.c.popup_id == popup_id)
    )


async def update_user_popup_log(
    user_id: int,
    popup_id: int,
) -> bool:
    update_query = (
        user_popup_logs.update()
        .where(user_popup_logs.c.user_id == user_id)
        .where(user_popup_logs.c.popup_id == popup_id)
        .where(user_popup_logs.c.reacted_at.is_(None))  # not sure abot that
        .values(reacted_at=datetime.utcnow())
    )
    res = await execute(update_query)
    reaction_is_new = res.rowcount > 0
    if not reaction_is_new:
        logging.warning(f"User {user_id} already reacted to popup {popup_id}!")
    return reaction_is_new  # so I can filter double clicks


async def create_inline_search_log(
    user_id: int,
    query: str,
    chat_type: str | None,
) -> None:
    insert_query = insert(inline_search_logs).values(
        user_id=user_id,
        query=query,
        chat_type=chat_type,
    )
    await execute(insert_query)


async def create_inline_chosen_result_log(
    user_id: int,
    result_id: str,
    query: str,
) -> None:
    insert_query = insert(inline_search_chosen_result_logs).values(
        user_id=user_id,
        result_id=result_id,
        query=query,
    )
    await execute(insert_query)


async def log_user_deep_link(user_id: int, deep_link: str | None) -> None:
    insert_query = insert(user_deep_link_log).values(
        user_id=user_id,
        deep_link=deep_link,
    )
    await execute(insert_query)


async def snooze_memes_of_meme_source(meme_source_id: int) -> int:
    update_statement = (
        meme.update()
        .where(meme.c.meme_source_id == meme_source_id)
        .where(meme.c.status == MemeStatus.OK)
        .values(status=MemeStatus.SNOOZED)
    )
    result = await execute(update_statement)
    return result.rowcount


async def unsnooze_memes_of_meme_source(meme_source_id: int) -> int:
    update_statement = (
        meme.update()
        .where(meme.c.meme_source_id == meme_source_id)
        .where(meme.c.status == MemeStatus.SNOOZED)
        .values(status=MemeStatus.OK)
    )
    result = await execute(update_statement)
    return result.rowcount


# === Experiment Assignment ===


async def get_experiment_variant(user_id: int, experiment_id: str) -> str | None:
    """Get a user's experiment variant. Returns None if not assigned."""
    query = select(experiment_assignment.c.variant).where(
        experiment_assignment.c.experiment_id == experiment_id,
        experiment_assignment.c.user_id == user_id,
    )
    row = await fetch_one(query)
    return row["variant"] if row else None


async def assign_experiment(user_id: int, experiment_id: str, variant: str) -> bool:
    """Assign a user to an experiment variant. Idempotent (ON CONFLICT DO NOTHING).

    Returns True when this call inserted a new assignment row, False when a
    row already existed. Callers can use the return value as a once-per-user
    gate (e.g. emitting `evaluated` exactly once when the cohort is decided).
    """
    insert_query = (
        insert(experiment_assignment)
        .values(
            experiment_id=experiment_id,
            user_id=user_id,
            variant=variant,
        )
        .on_conflict_do_nothing(
            index_elements=["experiment_id", "user_id"],
        )
    )
    result = await execute(insert_query)
    return result.rowcount > 0
