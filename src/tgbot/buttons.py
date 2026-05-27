import inspect
import random
from typing import Any

from telegram import InlineKeyboardButton

INLINE_KEYBOARD_BUTTON_STYLES = ("primary", "success", "danger")

_INLINE_BUTTON_SUPPORTS_STYLE = (
    "style" in inspect.signature(InlineKeyboardButton.__init__).parameters
)


def select_random_inline_keyboard_button_style() -> str:
    return random.choices(INLINE_KEYBOARD_BUTTON_STYLES, k=1)[0]


def styled_inline_keyboard_button(
    text: str,
    *,
    style: str | None = None,
    api_kwargs: dict[str, Any] | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    if style is None:
        return InlineKeyboardButton(text, api_kwargs=api_kwargs, **kwargs)

    if _INLINE_BUTTON_SUPPORTS_STYLE:
        return InlineKeyboardButton(text, style=style, api_kwargs=api_kwargs, **kwargs)

    merged_api_kwargs = dict(api_kwargs or {})
    merged_api_kwargs["style"] = style
    return InlineKeyboardButton(text, api_kwargs=merged_api_kwargs, **kwargs)
