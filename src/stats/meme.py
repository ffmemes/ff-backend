from sqlalchemy import text

from src.database import execute


async def calculate_meme_stats() -> None:
    insert_query = f"""
        INSERT INTO user_stats (
            meme_id, 
            nlikes, 
            ndislikes, 
            nmemes_sent, 
            updated_at
        )
        SELECT 
            meme_id
            , COUNT(*) FILTER (WHERE reaction_id = 1) nlikes
            , COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes
            , COUNT(*) nmemes_sent
            , NOW() AS updated_at
        FROM user_meme_reaction E
        GROUP BY 1

        ON CONFLICT (meme_id) DO 
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            nmemes_sent = EXCLUDED.nmemes_sent,
            updated_at = EXCLUDED.updated_at
    """
    await execute(text(insert_query))
