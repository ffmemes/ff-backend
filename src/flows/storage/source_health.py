import html
import logging

from prefect import flow

from src.flows.hooks import notify_telegram_on_failure
from src.storage.service import (
    STALE_SOURCE_SNOOZE_AFTER_DAYS,
    auto_snooze_stale_sources,
)
from src.tgbot.logs import log

logger = logging.getLogger(__name__)


def _format_snoozed_sources_alert(
    sources: list[dict],
    stale_after_days: int,
) -> str:
    sample_lines = []
    for source in sources[:10]:
        source_url = html.escape(str(source["url"]))
        parsed_at = source["parsed_at"] or "never"
        sample_lines.append(
            f"- #{source['id']} {html.escape(source['type'])} "
            f"<code>{source_url}</code> last_parse={html.escape(str(parsed_at))}"
        )

    sample = "\n".join(sample_lines)
    return (
        "🔕 Auto-snoozed stale meme sources\n"
        f"Reason: <code>stale_no_raw_posts_7d</code>\n"
        f"Rule: parsing_enabled, no successful parse/raw posts for {stale_after_days}+ days\n"
        f"Count: {len(sources)}\n"
        f"{sample}\n\n"
        "Recovery: open the source admin card and set status to "
        "<code>parsing_enabled</code>. TG/VK sources parse immediately after unsnooze; "
        "Instagram currently has no active parser deployment."
    )


@flow(
    name="Auto-snooze stale meme sources",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def auto_snooze_stale_sources_flow(
    stale_after_days: int = STALE_SOURCE_SNOOZE_AFTER_DAYS,
) -> dict:
    snoozed_sources = await auto_snooze_stale_sources(stale_after_days=stale_after_days)
    summary = {
        "snoozed_count": len(snoozed_sources),
        "source_ids": [source["id"] for source in snoozed_sources],
    }

    if snoozed_sources:
        logger.warning("Auto-snoozed %d stale sources", len(snoozed_sources))
        await log(_format_snoozed_sources_alert(snoozed_sources, stale_after_days))

    return summary
