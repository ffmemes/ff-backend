"""
One-off script to deep-parse newly added sources.
Run inside Docker: docker compose exec app python scripts/deep_parse_new_sources.py
"""
import asyncio

from src.storage.etl import insert_parsed_posts_from_telegram
from src.storage.parsers.tg import TelegramChannelScraper
from src.storage.service import update_meme_source
from datetime import datetime


SOURCES_TO_DEEP_PARSE = [
    (21285, "https://t.me/koyechto_daily"),
    (21286, "https://t.me/MemDoze"),
    (21287, "https://t.me/kabinet_memologini"),
    (21288, "https://t.me/mamayavtelege"),
    (21289, "https://t.me/abstracthumor"),
    (106, "https://t.me/kabinet_memologa"),  # re-enabled
]

NPOSTS = 100


async def main():
    for source_id, url in SOURCES_TO_DEEP_PARSE:
        username = url.split("/")[-1]
        print(f"\n{'='*60}")
        print(f"Parsing @{username} (id={source_id}) with nposts={NPOSTS}...")

        try:
            tg = TelegramChannelScraper(username)
            posts = await tg.get_items(NPOSTS)
            print(f"  Got {len(posts)} posts")

            if posts:
                await insert_parsed_posts_from_telegram(source_id, posts)
                print(f"  Inserted into meme_raw_telegram")

            await update_meme_source(
                meme_source_id=source_id, parsed_at=datetime.utcnow()
            )
            print(f"  Done!")
        except Exception as e:
            print(f"  ERROR: {e}")

        # Small delay to avoid rate limiting
        await asyncio.sleep(3)

    print(f"\n{'='*60}")
    print("All sources parsed. Pipeline will pick them up automatically.")


if __name__ == "__main__":
    asyncio.run(main())
