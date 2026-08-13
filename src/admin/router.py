"""Admin HTTP routes for meme inspection (agent/operator tooling)."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from src.admin.auth import require_admin_token
from src.admin.service import (
    MAX_INLINE_MEDIA_BYTES,
    build_meme_inspect_payload,
    media_content_type,
    media_filename,
)
from src.storage.upload import download_meme_content_from_tg
from src.tgbot.service import get_meme_by_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/memes/{meme_id}")
async def inspect_meme(
    meme_id: int,
    include_media: bool = Query(
        default=False,
        description=(
            "If true, embed media as base64 when the file is <= 4MB. "
            "Prefer GET /admin/memes/{id}/media for larger files or binary save."
        ),
    ),
) -> dict:
    """Compact meme card: status, source, stats, OCR, media availability.

    Use this to understand what a meme is without SQL joins across meme /
    meme_source / meme_stats / ocr_result. Media itself requires a second hop
    (or include_media=1 for small images).
    """
    payload = await build_meme_inspect_payload(meme_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meme not found")

    if include_media and payload["media"]["available"]:
        meme_row = await get_meme_by_id(meme_id)
        file_id = meme_row and meme_row.get("telegram_file_id")
        if file_id:
            try:
                content = await download_meme_content_from_tg(file_id)
            except Exception as exc:
                logger.warning("admin inspect media download failed meme_id=%s: %s", meme_id, exc)
                payload["media"]["inline_error"] = f"download failed: {type(exc).__name__}"
            else:
                if len(content) > MAX_INLINE_MEDIA_BYTES:
                    payload["media"]["inline_error"] = (
                        f"media too large for inline base64 "
                        f"({len(content)} bytes > {MAX_INLINE_MEDIA_BYTES}); "
                        f"use GET {payload['media']['download_path']}"
                    )
                    payload["media"]["size_bytes"] = len(content)
                else:
                    payload["media"]["size_bytes"] = len(content)
                    payload["media"]["base64"] = base64.b64encode(content).decode("ascii")

    return payload


@router.get("/memes/{meme_id}/media")
async def download_meme_media(meme_id: int) -> Response:
    """Download meme image/video bytes via the production Telegram bot token.

    This is the piece agents cannot do with SQL alone: Telegram file_id only
    resolves with the bot that uploaded the file.
    """
    meme_row = await get_meme_by_id(meme_id)
    if meme_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meme not found")

    file_id = meme_row.get("telegram_file_id")
    if not file_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meme has no telegram_file_id (not uploaded to Telegram storage)",
        )

    try:
        content = await download_meme_content_from_tg(file_id)
    except Exception as exc:
        logger.exception("admin media download failed meme_id=%s", meme_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram download failed: {type(exc).__name__}: {exc}",
        ) from exc

    meme_type = meme_row.get("type")
    return Response(
        content=content,
        media_type=media_content_type(meme_type),
        headers={
            "Content-Disposition": f'inline; filename="{media_filename(meme_id, meme_type)}"',
            "X-Meme-Id": str(meme_id),
            "X-Meme-Type": str(meme_type or ""),
        },
    )
