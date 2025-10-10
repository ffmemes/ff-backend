from datetime import datetime, timedelta
from types import SimpleNamespace

from src.tgbot.handlers.upload.forwarded_meme import (
    extract_meme_id_from_message,
    format_age,
    was_forwarded_from_bot,
)


def _make_message(**kwargs):
    return SimpleNamespace(**kwargs)


def test_extract_meme_id_from_plain_url() -> None:
    message = _make_message(
        text="https://t.me/ffmemesbot?start=s_111_222",
        entities=None,
        caption=None,
        caption_entities=None,
    )

    assert extract_meme_id_from_message(message) == 222


def test_extract_meme_id_from_caption_entity() -> None:
    entity = SimpleNamespace(type="text_link", url="https://t.me/ffmemesbot?start=s_333_444")
    message = _make_message(
        text=None,
        entities=None,
        caption="Fast Food Memes",
        caption_entities=[entity],
    )

    assert extract_meme_id_from_message(message) == 444


def test_extract_meme_id_trims_trailing_characters() -> None:
    message = _make_message(
        text="Check this https://t.me/ffmemesbot?start=s_777_888).",
        entities=None,
        caption=None,
        caption_entities=None,
    )

    assert extract_meme_id_from_message(message) == 888


def test_format_age_uses_explicit_now() -> None:
    fixed_now = datetime(2023, 1, 1, 12, 0, 0)
    published_at = fixed_now - timedelta(days=1, hours=2, minutes=30)

    assert format_age(published_at, now=fixed_now) == "1d 2h"


def test_was_forwarded_from_bot_by_forward_from() -> None:
    message = _make_message(forward_from=_make_message(id=1), forward_origin=None)

    assert was_forwarded_from_bot(message, 1)


def test_was_forwarded_from_bot_by_forward_origin() -> None:
    message = _make_message(
        forward_from=None,
        forward_origin=_make_message(sender_user=_make_message(id=2)),
    )

    assert was_forwarded_from_bot(message, 2)
