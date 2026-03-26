"""
Deep-parse a Telegram source to backfill historical memes.

Usage:
    docker compose exec app python scripts/deep_parse.py https://t.me/channel_name
    docker compose exec app python scripts/deep_parse.py https://t.me/channel_name --nposts 200
    docker compose exec app python scripts/deep_parse.py https://t.me/channel_name --add --lang ru

Options:
    --nposts N   Number of posts to parse (default: 100)
    --add        Add source to DB if it doesn't exist (requires --lang)
    --lang CODE  Language code for new source (e.g. ru, en, uk, es)
"""
import argparse
import asyncio
from datetime import datetime, timezone

from src.database import fetch_one
from src.storage.etl import insert_parsed_posts_from_telegram
from src.storage.parsers.tg import TelegramChannelScraper
from src.storage.service import update_meme_source
from src.tgbot.service import get_or_create_meme_source


async def main():
    parser = argparse.ArgumentParser(description="Deep-parse a Telegram meme source")
    parser.add_argument("url", help="Telegram channel URL (https://t.me/channel)")
    parser.add_argument("--nposts", type=int, default=100, help="Posts to parse")
    parser.add_argument("--add", action="store_true", help="Add source if missing")
    parser.add_argument("--lang", default=None, help="Language code (required with --add)")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    if not url.startswith("https://t.me/"):
        print(f"ERROR: URL must start with https://t.me/, got: {url}")
        return

    username = url.split("/")[-1]

    # Find source in DB
    from sqlalchemy import text
    from src.database import fetch_one

    source = await fetch_one(
        text("SELECT id, url, status FROM meme_source WHERE url = :url"),
        {"url": url},
    )

    if not source:
        if not args.add:
            print(f"Source {url} not found in DB. Use --add --lang ru to create it.")
            return
        if not args.lang:
            print("ERROR: --lang is required when using --add")
            return

        source = await get_or_create_meme_source(
            url=url,
            type="telegram",
            status="parsing_enabled",
            language_code=args.lang,
        )
        print(f"Created source id={source['id']} ({url}, lang={args.lang})")
    else:
        print(f"Found source id={source['id']} ({url}, status={source['status']})")

    # Parse
    print(f"Parsing @{username} with nposts={args.nposts}...")
    tg = TelegramChannelScraper(username)
    posts = await tg.get_items(args.nposts)
    print(f"Got {len(posts)} posts")

    if posts:
        await insert_parsed_posts_from_telegram(source["id"], posts)
        print(f"Inserted into meme_raw_telegram")

    await update_meme_source(
        meme_source_id=source["id"], parsed_at=datetime.now(timezone.utc)
    )
    print("Done! Pipeline will pick up new memes automatically.")


if __name__ == "__main__":
    asyncio.run(main())
