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
    # ON CONFLICT DO NOTHING: rewrite-on-repost would corrupt source-quality
    # measurements (drop the original mature sample out of the [30d, 48h]
    # window and overwrite its views/forwards with the reward post's stats).
    # Reward reposts of already-crossposted memes therefore don't refresh
    # the diversity cap — acceptable since rewards run weekly.
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
    query = """
        WITH src_quality AS (
            SELECT
                m.meme_source_id,
                AVG(cp.forwards * SQRT(GREATEST(cp.views, 1) / 100.0)) AS signal,
                COUNT(*) AS n_posts
            FROM crossposting cp
            JOIN meme m ON m.id = cp.meme_id
            WHERE cp.channel = 'tgchannelru'
              AND cp.created_at > NOW() - INTERVAL '30 days'
              AND cp.created_at < NOW() - INTERVAL '48 hours'
              AND cp.views IS NOT NULL
              AND cp.views > 0
              AND m.type = 'image'
            GROUP BY m.meme_source_id
            HAVING COUNT(*) >= 5
        ),
        src_median AS (
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY signal) AS m_signal
            FROM src_quality
        ),
        recent_src AS (
            SELECT DISTINCT m2.meme_source_id
            FROM crossposting cp2
            JOIN meme m2 ON m2.id = cp2.meme_id
            WHERE cp2.channel = 'tgchannelru'
              AND cp2.created_at > NOW() - INTERVAL '24 hours'
              AND cp2.telegram_message_id IS NOT NULL
        )
        SELECT M.id, M.type, M.telegram_file_id, M.caption
        FROM meme M
        INNER JOIN meme_stats MS ON MS.meme_id = M.id
        LEFT JOIN crossposting CP ON CP.meme_id = M.id AND CP.channel = 'tgchannelru'
        LEFT JOIN src_quality SQ ON SQ.meme_source_id = M.meme_source_id
        WHERE 1=1
          AND CP.meme_id IS NULL
          AND M.status = 'ok'
          AND M.language_code = 'ru'
          AND M.type = 'image'
          AND MS.nlikes >= 5
          AND M.meme_source_id NOT IN (SELECT meme_source_id FROM recent_src)
        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
            * CASE WHEN MS.age_days < 7 THEN 1 ELSE 0.8 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
              END
            * COALESCE(
                LEAST(2.0, GREATEST(0.5,
                    SQ.signal / NULLIF((SELECT m_signal FROM src_median), 0)
                )),
                1.0
              )
            * (1.0 + LEAST(MS.invited_count, 10) * 0.1)
        LIMIT 1
    """
    return await fetch_one(text(query))


async def get_next_meme_for_tgchannelen() -> dict[str, Any]:
    query = """
        WITH src_quality AS (
            SELECT
                m.meme_source_id,
                AVG(cp.forwards * SQRT(GREATEST(cp.views, 1) / 100.0)) AS signal,
                COUNT(*) AS n_posts
            FROM crossposting cp
            JOIN meme m ON m.id = cp.meme_id
            WHERE cp.channel = 'tgchannelen'
              AND cp.created_at > NOW() - INTERVAL '30 days'
              AND cp.created_at < NOW() - INTERVAL '48 hours'
              AND cp.views IS NOT NULL
              AND cp.views > 0
              AND m.type = 'image'
            GROUP BY m.meme_source_id
            HAVING COUNT(*) >= 5
        ),
        src_median AS (
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY signal) AS m_signal
            FROM src_quality
        ),
        recent_src AS (
            SELECT DISTINCT m2.meme_source_id
            FROM crossposting cp2
            JOIN meme m2 ON m2.id = cp2.meme_id
            WHERE cp2.channel = 'tgchannelen'
              AND cp2.created_at > NOW() - INTERVAL '24 hours'
              AND cp2.telegram_message_id IS NOT NULL
        )
        SELECT M.id, M.type, M.telegram_file_id, M.caption
        FROM meme M
        INNER JOIN meme_stats MS ON MS.meme_id = M.id
        LEFT JOIN crossposting CP ON CP.meme_id = M.id AND CP.channel = 'tgchannelen'
        LEFT JOIN src_quality SQ ON SQ.meme_source_id = M.meme_source_id
        WHERE 1=1
          AND CP.meme_id IS NULL
          AND M.status = 'ok'
          AND M.language_code = 'en'
          AND M.type = 'image'
          AND MS.nlikes >= 5
          AND M.meme_source_id NOT IN (SELECT meme_source_id FROM recent_src)
        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 90 THEN 1 ELSE 0.8 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
              END
            * COALESCE(
                LEAST(2.0, GREATEST(0.5,
                    SQ.signal / NULLIF((SELECT m_signal FROM src_median), 0)
                )),
                1.0
              )
            * (1.0 + LEAST(MS.invited_count, 10) * 0.1)
        LIMIT 1
    """
    return await fetch_one(text(query))


async def get_next_meme_for_vkgroupru():
    pass
