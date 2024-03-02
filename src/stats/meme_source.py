from sqlalchemy import text

from src.database import execute


async def calculate_meme_source_stats() -> None:
    insert_query = """
        INSERT INTO meme_source_stats (
            meme_source_id,
            nlikes,
            ndislikes,
            nmemes_sent_events,
            nmemes_parsed,
            nmemes_sent,
            latest_meme_age,
            updated_at
        )
        SELECT
            M.meme_source_id
            , COUNT(E.meme_id) FILTER (WHERE reaction_id = 1) nlikes
            , COUNT(E.meme_id) FILTER (WHERE reaction_id = 2) ndislikes
            , COUNT(E.meme_id) nmemes_sent_events
            , COUNT(DISTINCT M.id) nmemes_parsed
            , COUNT(DISTINCT E.meme_id) nmemes_sent
            , MIN(EXTRACT('DAYS' FROM NOW() - M.published_at)) latest_meme_age
            , NOW() AS updated_at
        FROM meme M
        LEFT JOIN user_meme_reaction E
            ON M.id = E.meme_id
        GROUP BY 1

        ON CONFLICT (meme_id) DO
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            nmemes_sent_events = EXCLUDED.nmemes_sent_events,
            nmemes_parsed = EXCLUDED.nmemes_parsed,
            nmemes_sent = EXCLUDED.nmemes_sent,
            latest_meme_age = EXCLUDED.latest_meme_age,
            updated_at = EXCLUDED.updated_at
    """
    await execute(text(insert_query))
