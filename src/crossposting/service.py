from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.crossposting.constants import Channel
from src.database import crossposting, execute, fetch_one


async def log_meme_sent(meme_id: int, channel: Channel) -> None:
    insert_statement = insert(crossposting).values(
        meme_id=meme_id, channel=channel.value
    )

    await execute(insert_statement)


async def get_next_meme_for_tgchannelru():
    query = """
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption

        ----------- DEBUG
        --	, MS.nlikes
        --	, MS.ndislikes
        --	, MS.nmemes_sent
        --	, MS.raw_impr_rank
        --	, MS.age_days
        --	, M.meme_source_id
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
    query = """
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption

            -- DEBUG
        --    , MS.nlikes
        --    , MS.ndislikes
        --    , MS.nmemes_sent
        --    , MSS.nlikes AS source_likes
        --    , MSS.ndislikes AS source_dislikes
        --    , MS.raw_impr_rank
        --    , MS.age_days
        --    , M.meme_source_id

        FROM meme M
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        --LEFT JOIN meme_source_stats MSS
        --	ON MSS.meme_source_id = M.meme_source_id
        LEFT JOIN crossposting CP
            ON CP.meme_id = M.id
            AND CP.channel = 'tgchannelen'

        WHERE 1=1
            AND CP.meme_id IS NULL
            AND M.status = 'ok'
            AND M.language_code = 'en'
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
