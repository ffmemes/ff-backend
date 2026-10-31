import io
import logging
from typing import Any

from PIL import Image
from sqlalchemy import text

from src.database import fetch_one
from src.observability.sentry import sentry_log_extra

logger = logging.getLogger(__name__)


def dhash(content: bytes) -> int:
    """64-bit difference hash as a signed int64 (fits Postgres BIGINT)."""
    with Image.open(io.BytesIO(content)) as img:
        pixels = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    value = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            value = (value << 1) | (left > pixels[row * 9 + col + 1])
    return value - (1 << 64) if value >= 1 << 63 else value


async def log_phash_shadow_match(meme_row: dict[str, Any]) -> dict[str, Any] | None:
    """Shadow mode: log a live meme with the same image_hash; never merges."""
    # Solid/blank frames (e.g. black first video frame) all hash to 0 or -1.
    if meme_row.get("image_hash") in (None, 0, -1):
        return None
    # ponytail: exact hash only; Hamming distance <= N (bit_count(a # b)) is the upgrade path.
    candidate = await fetch_one(
        text(
            """
            SELECT id, type, status, duplicate_of FROM meme
            WHERE image_hash = :image_hash
              AND id != :meme_id
              AND status IN ('ok', 'published')
              AND telegram_file_id IS DISTINCT FROM :file_id
            ORDER BY CASE WHEN status = 'published' THEN 0 ELSE 1 END, id
            LIMIT 1
            """
        ),
        {
            "image_hash": meme_row["image_hash"],
            "meme_id": meme_row["id"],
            "file_id": meme_row.get("telegram_file_id"),
        },
    )
    if candidate is None:
        return None
    logger.info(
        "phash shadow match",
        extra=sentry_log_extra(
            meme_id=meme_row["id"],
            candidate_id=candidate["id"],
            meme_type=meme_row.get("type"),
            candidate_type=candidate["type"],
            meme_status=meme_row.get("status"),
            candidate_status=candidate["status"],
            ocr_linked=meme_row.get("duplicate_of") == candidate["id"]
            or candidate["duplicate_of"] == meme_row["id"],
        ),
    )
    return candidate
