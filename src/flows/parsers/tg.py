import asyncio
import time
from datetime import datetime

from prefect import flow, get_run_logger

from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.storage.etl import insert_parsed_posts_from_telegram
from src.storage.parsers.tg import TelegramChannelScraper
from src.storage.service import (
    get_telegram_sources_to_parse,
    maybe_auto_snooze_source,
    update_meme_source,
)
from src.tgbot.logs import log


@flow(name="Parse Telegram Source", timeout_seconds=300)
async def parse_telegram_source(
    meme_source_id: int,
    meme_source_url: str,
    nposts: int = 10,
) -> None:
    logger = get_run_logger()

    tg_username = meme_source_url.split("/")[-1]  # is it ok?
    tg = TelegramChannelScraper(tg_username)

    posts = await tg.get_items(nposts)
    logger.info(f"Received {len(posts)} posts from @{tg_username}")
    if len(posts) > 0:
        await insert_parsed_posts_from_telegram(meme_source_id, posts)

    await update_meme_source(meme_source_id=meme_source_id, parsed_at=datetime.utcnow())

    snooze_reason = await maybe_auto_snooze_source(meme_source_id, len(posts))
    if snooze_reason:
        logger.warning(
            f"Auto-snoozed source {meme_source_id} ({meme_source_url}): {snooze_reason}"
        )
        await log(
            f"🔕 Auto-snoozed TG source <b>@{tg_username}</b> (id={meme_source_id})\n"
            f"Reason: <code>{snooze_reason}</code>"
        )

    await asyncio.sleep(5)


@flow(
    name="Parse Telegram Channels",
    description="Flow for parsing telegram channels to get posts",
    retries=2,
    retry_delay_seconds=60,
    timeout_seconds=1800,
    on_failure=[notify_telegram_on_failure],
)
async def parse_telegram_sources(
    sources_batch_size=25,
    nposts=10,
) -> None:
    logger = get_run_logger()
    t0 = time.monotonic()
    tg_sources = await get_telegram_sources_to_parse(limit=sources_batch_size)
    logger.info(f"Received {len(tg_sources)} tg sources to scrape.")

    ok_count = 0
    fail_count = 0
    for tg_source in tg_sources:
        try:
            await parse_telegram_source(tg_source["id"], tg_source["url"], nposts=nposts)
            ok_count += 1
        except Exception as e:
            fail_count += 1
            logger.error(
                f"Source {tg_source['id']} ({tg_source['url']}) failed: {e}"
            )

    elapsed = time.monotonic() - t0
    logger.info(
        f"Parsing done: {ok_count} ok, {fail_count} failed "
        f"out of {len(tg_sources)} sources in {elapsed:.0f}s"
    )

    safe_emit(
        "ff.parser.telegram.completed",
        "ff.parser.telegram",
        {"sources_ok": ok_count, "sources_failed": fail_count},
    )
