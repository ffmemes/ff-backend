import re
from typing import Any

from sqlalchemy import text

from src.database import fetch_one
from src.storage.deduplication.models import (
    MIN_OCR_DUPLICATE_SIMILARITY,
    MIN_OCR_DUPLICATE_TEXT_LENGTH,
    OCR_WATERMARK_PATTERN,
)

_WATERMARK_RE = re.compile(OCR_WATERMARK_PATTERN, re.IGNORECASE)


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

    # Our watermark (and OCR misreads of it) is on most images; matching on it
    # merged unrelated short captions into a few "hub" memes.
    image_text = _WATERMARK_RE.sub("", image_text).strip()
    if len(image_text) < MIN_OCR_DUPLICATE_TEXT_LENGTH:
        return None

    # `%` (default 0.3 threshold) only prefilters via the trigram index;
    # the real match is similarity >= MIN_OCR_DUPLICATE_SIMILARITY on stripped text.
    select_query = text(
        """
        SELECT id FROM (
            SELECT
                M.id,
                M.status,
                similarity(
                    regexp_replace(M.ocr_result ->> 'text', :watermark, '', 'gi'),
                    :image_text
                ) AS sim
            FROM meme M
            WHERE M.id != :meme_id
                AND M.status IN ('ok', 'published')
                AND M.type = 'image'
                AND M.ocr_result IS NOT NULL
                AND (M.ocr_result ->> 'text') % :image_text
        ) C
        WHERE C.sim >= :min_similarity
        ORDER BY
            C.sim DESC,
            CASE WHEN C.status = 'published' THEN 0 ELSE 1 END,
            C.id ASC
        LIMIT 1
    """
    )

    res = await fetch_one(
        select_query,
        {
            "meme_id": meme_id,
            "image_text": image_text,
            "watermark": OCR_WATERMARK_PATTERN,
            "min_similarity": MIN_OCR_DUPLICATE_SIMILARITY,
        },
    )
    return res["id"] if res else None
