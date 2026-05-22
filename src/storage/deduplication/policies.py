from typing import Any

from src.storage.constants import MemeStatus
from src.storage.deduplication.finder import (
    find_duplicate_by_file_id,
    find_duplicate_by_ocr_text,
    ocr_text_from_meme,
)
from src.storage.deduplication.models import DeduplicationResult
from src.storage.deduplication.resolver import resolve_duplicate


async def deduplicate_pending_meme(meme_row: dict[str, Any]) -> DeduplicationResult:
    """Run cheap dedup checks before a created meme can be promoted to ok."""
    meme_id = meme_row["id"]
    telegram_file_id = meme_row.get("telegram_file_id")
    if telegram_file_id:
        duplicate_of = await find_duplicate_by_file_id(meme_id, telegram_file_id)
        if duplicate_of:
            resolution = await resolve_duplicate(
                meme_id,
                duplicate_of,
                reason="telegram_file_id",
            )
            return DeduplicationResult(meme_id, duplicate_of, "telegram_file_id", resolution)

    duplicate_of = await find_duplicate_by_ocr_text(meme_id, ocr_text_from_meme(meme_row))
    if duplicate_of:
        resolution = await resolve_duplicate(meme_id, duplicate_of, reason="ocr_text")
        return DeduplicationResult(meme_id, duplicate_of, "ocr_text", resolution)

    return DeduplicationResult(meme_id)


async def deduplicate_described_meme(
    meme_id: int,
    ocr_text: str,
    *,
    status: str | None,
) -> DeduplicationResult:
    """Run OCR dedup after Describe Memes enriches an already-ok image."""
    if status != MemeStatus.OK.value:
        return DeduplicationResult(meme_id)

    duplicate_of = await find_duplicate_by_ocr_text(meme_id, ocr_text)
    if not duplicate_of:
        return DeduplicationResult(meme_id)

    resolution = await resolve_duplicate(meme_id, duplicate_of, reason="ocr_text")
    return DeduplicationResult(meme_id, duplicate_of, "ocr_text", resolution)
