from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.crossposting.constants import Channel
from src.database import crossposting, execute, fetch_one


async def log_meme_sent(
    meme_id: int,
    channel: Channel,
    telegram_message_id: int | None = None,
    caption_text: str | None = None,
    score_version: int = 1,
) -> None:
    insert_statement = (
        insert(crossposting)
        .values(
            meme_id=meme_id,
            channel=channel.value,
            telegram_message_id=telegram_message_id,
            caption_text=caption_text,
            score_version=score_version,
        )
        .on_conflict_do_nothing()
    )

    await execute(insert_statement)


async def get_next_meme_for_tgchannelru():
    # Videos excluded: 1.8x boost flipped RU channel to ~89% videos in last 14 days
    # (84 video / 10 image as of 2026-04-26). Users complained about video-only feed.
    # Same root cause as EN fix on 2026-04-22 — fwd/1k boost was an artifact of fewer
    # views, not better content. RU was left untouched then; reality showed the 50/50
    # mix collapsed within days. Hard-filter to images, mirroring EN.
    query = """
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id
        LEFT JOIN crossposting CP
            ON CP.meme_id = M.id
            AND CP.channel = 'tgchannelru'

        WHERE 1=1
            AND CP.meme_id IS NULL
            AND M.status = 'ok'
            AND M.language_code = 'ru'
            AND M.type = 'image'
            AND MS.nlikes >= 5

        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
            * CASE WHEN MS.age_days < 7 THEN 1 ELSE 0.8 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT 1
    """
    return await fetch_one(text(query))


async def get_next_meme_for_tgchannelen() -> dict[str, Any]:
    # Videos excluded: 1.8x boost (added 2026-04-13) flipped EN channel to 100% videos.
    # Outcome over 9 days: avg views collapsed 179 → 78, reactions 1.1 → 0.5 per post,
    # subscribers drifted 629 → 625. Higher fwd/1k for videos was an artifact of fewer
    # views (Russian internet loads videos poorly), not better content.
    query = """
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption

        FROM meme M
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        LEFT JOIN crossposting CP
            ON CP.meme_id = M.id
            AND CP.channel = 'tgchannelen'

        WHERE 1=1
            AND CP.meme_id IS NULL
            AND M.status = 'ok'
            AND M.language_code = 'en'
            AND M.type = 'image'
            AND MS.nlikes >= 5

        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 90 THEN 1 ELSE 0.7 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.9 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT 1
    """
    return await fetch_one(text(query))


async def get_next_meme_for_vkgroupru():
    pass
