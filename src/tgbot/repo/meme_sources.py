from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    execute,
    fetch_all,
    fetch_one,
    meme_source,
    meme_source_candidate,
    meme_source_stats,
)
from src.storage.constants import MemeSourceStatus


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
