from typing import Any

from sqlalchemy import text

from src.database import fetch_one
from src.storage.deduplication.models import MIN_OCR_DUPLICATE_TEXT_LENGTH


def ocr_text_from_meme(meme_row: dict[str, Any]) -> str:
    ocr_result = meme_row.get("ocr_result") or {}
    text_value = ocr_result.get("text") or ocr_result.get("raw_result", {}).get("ocr_text")
    return text_value if isinstance(text_value, str) else ""


async def find_duplicate_by_file_id(meme_id: int, telegram_file_id: str) -> int | None:
    """Find an earlier meme that stores the same Telegram file_id."""
    query = text(
        """
        SELECT id FROM meme
        WHERE telegram_file_id = :file_id
          AND status IN ('ok', 'published', 'created')
          AND id < :meme_id
        ORDER BY
            CASE WHEN status = 'published' THEN 0 ELSE 1 END,
            id ASC
        LIMIT 1
    """
    )
    res = await fetch_one(query, {"file_id": telegram_file_id, "meme_id": meme_id})
    return res["id"] if res else None


async def find_duplicate_by_ocr_text(meme_id: int, image_text: Any) -> int | None:
    """Find an approved OCR match, regardless of which copy was described first."""
    if not isinstance(image_text, str):
        return None

    if len(image_text) < MIN_OCR_DUPLICATE_TEXT_LENGTH:
        return None

    select_query = text(
        """
        SELECT
            M.id
        FROM meme M
        WHERE M.id != :meme_id
            AND M.status IN ('ok', 'published')
            AND M.type = 'image'
            AND M.ocr_result IS NOT NULL
            AND (M.ocr_result ->> 'text') % :image_text
        ORDER BY
            CASE WHEN M.status = 'published' THEN 0 ELSE 1 END,
            M.id ASC
        LIMIT 1
    """
    )

    res = await fetch_one(select_query, {"meme_id": meme_id, "image_text": image_text})
    return res["id"] if res else None
