"""One-time script to describe memes liked by a specific user.

Usage:
    docker compose exec app python scripts/describe_user_memes.py --user-id 49820636 --limit 50

This prioritizes memes the user liked that don't have descriptions yet,
enabling them to test /wrapped with real personalized data.
"""

import argparse
import asyncio

from src.config import settings
from src.database import fetch_all
from src.flows.storage.describe_memes import describe_single_meme


async def get_user_liked_memes_without_description(user_id: int, limit: int = 50):
    from sqlalchemy import text

    query = text("""
        SELECT
            M.id,
            M.telegram_file_id,
            M.ocr_result,
            M.language_code
        FROM user_meme_reaction UMR
        JOIN meme M ON M.id = UMR.meme_id
        WHERE UMR.user_id = :user_id
            AND UMR.reaction_id = 1
            AND M.type = 'image'
            AND M.status = 'ok'
            AND M.telegram_file_id IS NOT NULL
            AND (M.ocr_result IS NULL OR M.ocr_result->>'description' IS NULL)
            AND COALESCE((M.ocr_result->>'describe_failures')::int, 0) < 3
        ORDER BY UMR.reacted_at DESC
        LIMIT :limit
    """)
    return await fetch_all(query, {"user_id": user_id, "limit": limit})


async def main(user_id: int, limit: int):
    if not settings.OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        return

    import logging
    log = logging.getLogger("describe_user_memes")
    logging.basicConfig(level=logging.INFO)

    memes = await get_user_liked_memes_without_description(user_id, limit)
    print(f"Found {len(memes)} liked memes without description for user {user_id}")

    ok = 0
    failed = 0
    for i, meme_row in enumerate(memes):
        status = await describe_single_meme(meme_row, log)
        if status == "ok":
            ok += 1
            print(f"  [{i+1}/{len(memes)}] Described meme {meme_row['id']}")
        elif status == "rate_limited":
            print(f"  [{i+1}/{len(memes)}] Rate limited — stopping (daily quota hit)")
            break
        else:
            failed += 1
            print(f"  [{i+1}/{len(memes)}] Failed meme {meme_row['id']}")

        if i < len(memes) - 1:
            await asyncio.sleep(2)

    print(f"\nDone: {ok} described, {failed} failed out of {len(memes)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Describe memes liked by a specific user")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    asyncio.run(main(args.user_id, args.limit))
