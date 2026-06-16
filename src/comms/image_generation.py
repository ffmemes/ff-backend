"""OpenAI image generation helpers for Comms editorial visuals.

This module is intentionally small: Comms builds an explicit prompt, receives
image bytes, visually reviews them, and passes the bytes directly to
`publish_editorial_post(photo_bytes=...)`. No Telegram moderator-chat staging
is needed to obtain a file_id.

This helper is API-key backed and is not the approved path for Paperclip
`codex_local` agents. Those agents should use first-class Codex subscription
image-generation artifacts when the runtime exposes them, or create a visual
handoff task for an interactive Codex operator.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from src.config import settings

DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1536x1024"
DEFAULT_IMAGE_QUALITY = "medium"
DEFAULT_OUTPUT_FORMAT = "png"


@dataclass(frozen=True)
class GeneratedEditorialImage:
    image_bytes: bytes
    prompt: str
    revised_prompt: str | None
    model: str
    size: str
    quality: str
    output_format: str


def build_editorial_image_prompt(
    *,
    post_text: str,
    visual_brief: str,
    composition: str,
    mood: str = "curious, sharp, optimistic",
    include_text: bool = False,
) -> str:
    """Build a precise, repeatable prompt for Telegram post visuals.

    Use AI-generated imagery for illustrative/editorial visuals. For exact
    numbers, charts, UI labels, or text-heavy layouts, use `src.comms.visuals`
    instead; image models can still miss precise typography.
    """
    text_rule = (
        "Do not include readable text, numbers, UI labels, watermarks, or logos."
        if not include_text
        else "Readable text is allowed only where explicitly described in the brief."
    )
    return "\n".join(
        [
            "Create a polished editorial image for a Russian Telegram channel post.",
            f"Post context: {post_text.strip()}",
            f"Visual brief: {visual_brief.strip()}",
            f"Composition: {composition.strip()}",
            f"Mood: {mood.strip()}",
            "Style: premium product/editorial illustration, clean shapes, "
            "crisp lighting, high contrast, not stock-photo-like.",
            "Brand palette: warm orange #FF6B35 as a single accent, "
            "deep navy #1A1A2E, soft light neutral #F5F5F5, "
            "restrained green #4CAF50 only for positive signal.",
            "Format: landscape 3:2, Telegram-friendly crop, "
            "clear focal point in the center third, readable at phone size.",
            text_rule,
            "Content safety: apolitical, SFW, non-offensive, "
            "no real public figures, no brand logos unless explicitly requested.",
        ]
    )


async def generate_editorial_image(
    prompt: str,
    *,
    client: Any | None = None,
    model: str = DEFAULT_IMAGE_MODEL,
    size: str = DEFAULT_IMAGE_SIZE,
    quality: str = DEFAULT_IMAGE_QUALITY,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> GeneratedEditorialImage:
    """Generate a Comms visual with the OpenAI Images API.

    Returns raw bytes so callers can publish with
    `publish_editorial_post(photo_bytes=image.image_bytes)`.
    """
    if client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required to generate editorial images.")
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality=quality,
        output_format=output_format,
        n=1,
    )
    data = getattr(response, "data", None) or []
    if not data:
        raise RuntimeError("OpenAI image generation returned no images.")

    first = data[0]
    image_b64 = getattr(first, "b64_json", None)
    if not image_b64:
        raise RuntimeError("OpenAI image generation returned no base64 image data.")

    return GeneratedEditorialImage(
        image_bytes=base64.b64decode(image_b64),
        prompt=prompt,
        revised_prompt=getattr(first, "revised_prompt", None),
        model=model,
        size=size,
        quality=quality,
        output_format=output_format,
    )


__all__ = [
    "DEFAULT_IMAGE_MODEL",
    "DEFAULT_IMAGE_QUALITY",
    "DEFAULT_IMAGE_SIZE",
    "DEFAULT_OUTPUT_FORMAT",
    "GeneratedEditorialImage",
    "build_editorial_image_prompt",
    "generate_editorial_image",
]
