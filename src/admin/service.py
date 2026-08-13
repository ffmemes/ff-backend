"""Compact meme inspect payloads for agents and operators."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.storage.constants import MemeType
from src.tgbot.service import get_meme_by_id, get_meme_source_by_id, get_meme_stats

# Cap for optional base64 embedding so agents don't pull multi‑MB videos into JSON.
MAX_INLINE_MEDIA_BYTES = 4 * 1024 * 1024


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _compact_ocr(ocr_result: dict[str, Any] | None) -> dict[str, Any]:
    if not ocr_result:
        return {
            "has_ocr": False,
            "calculated_at": None,
            "description": None,
            "text": None,
            "language": None,
            "model": None,
            "describe_failures": 0,
            "last_failure_reason": None,
        }

    raw = ocr_result.get("raw_result") if isinstance(ocr_result.get("raw_result"), dict) else {}
    text = ocr_result.get("text") or raw.get("ocr_text")
    description = ocr_result.get("description") or raw.get("description")
    language = ocr_result.get("language") or raw.get("language")
    has_ocr = bool(description or text or ocr_result.get("calculated_at"))

    return {
        "has_ocr": has_ocr,
        "calculated_at": ocr_result.get("calculated_at"),
        "description": description,
        "text": text,
        "language": language,
        "model": ocr_result.get("model") or ocr_result.get("described_by"),
        "describe_failures": int(ocr_result.get("describe_failures") or 0),
        "last_failure_reason": ocr_result.get("last_failure_reason"),
    }


def _compact_stats(stats: dict[str, Any] | None) -> dict[str, Any] | None:
    if not stats:
        return None
    return {
        "nlikes": stats.get("nlikes"),
        "ndislikes": stats.get("ndislikes"),
        "nmemes_sent": stats.get("nmemes_sent"),
        "lr_smoothed": stats.get("lr_smoothed"),
        "engagement_score": stats.get("engagement_score"),
        "age_days": stats.get("age_days"),
        "raw_impr_rank": stats.get("raw_impr_rank"),
        "sec_to_react": stats.get("sec_to_react"),
        "invited_count": stats.get("invited_count"),
        "updated_at": _iso(stats.get("updated_at")),
    }


def _compact_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None
    return {
        "id": source.get("id"),
        "type": source.get("type"),
        "url": source.get("url"),
        "status": source.get("status"),
        "language_code": source.get("language_code"),
        "parsed_at": _iso(source.get("parsed_at")),
    }


def media_content_type(meme_type: str | None) -> str:
    if meme_type == MemeType.VIDEO.value:
        return "video/mp4"
    if meme_type == MemeType.ANIMATION.value:
        return "image/gif"
    return "image/jpeg"


def media_filename(meme_id: int, meme_type: str | None) -> str:
    if meme_type == MemeType.VIDEO.value:
        ext = "mp4"
    elif meme_type == MemeType.ANIMATION.value:
        ext = "gif"
    else:
        ext = "jpg"
    return f"meme_{meme_id}.{ext}"


async def build_meme_inspect_payload(meme_id: int) -> dict[str, Any] | None:
    meme_row = await get_meme_by_id(meme_id)
    if meme_row is None:
        return None

    source = await get_meme_source_by_id(meme_row["meme_source_id"])
    stats = await get_meme_stats(meme_id)
    file_id = meme_row.get("telegram_file_id")

    return {
        "meme": {
            "id": meme_row["id"],
            "status": meme_row.get("status"),
            "type": meme_row.get("type"),
            "language_code": meme_row.get("language_code"),
            "caption": meme_row.get("caption"),
            "published_at": _iso(meme_row.get("published_at")),
            "created_at": _iso(meme_row.get("created_at")),
            "updated_at": _iso(meme_row.get("updated_at")),
            "duplicate_of": meme_row.get("duplicate_of"),
            "meme_source_id": meme_row.get("meme_source_id"),
            "raw_meme_id": meme_row.get("raw_meme_id"),
            "has_telegram_file_id": bool(file_id),
        },
        "source": _compact_source(source),
        "stats": _compact_stats(stats),
        "ocr": _compact_ocr(meme_row.get("ocr_result")),
        "media": {
            "available": bool(file_id),
            "download_path": f"/admin/memes/{meme_id}/media" if file_id else None,
            "content_type": media_content_type(meme_row.get("type")) if file_id else None,
            "filename": media_filename(meme_id, meme_row.get("type")) if file_id else None,
        },
    }
