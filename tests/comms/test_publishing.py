"""Unit tests for validation and normalization helpers in src.comms.publishing.

These tests do NOT touch the DB or Telegram — they verify the pure pieces
that would block a bad draft before any async work runs.
"""

import pytest

from src.comms.publishing import (
    ALLOWED_CHANNELS,
    ALLOWED_HTML_TAGS,
    TELEGRAM_CAPTION_MAX,
    compute_draft_hash,
    normalize_blockquote,
    validate_post_draft,
)

# ── normalize_blockquote ──────────────────────────────────────────────────


def test_normalize_blockquote_rewrites_plain_to_expandable():
    out = normalize_blockquote("before <blockquote>hi</blockquote> after")
    assert out == "before <blockquote expandable>hi</blockquote> after"


def test_normalize_blockquote_leaves_expandable_alone():
    src = "x <blockquote expandable>y</blockquote>"
    assert normalize_blockquote(src) == src


def test_normalize_blockquote_is_case_insensitive():
    out = normalize_blockquote("<BLOCKQUOTE>x</BLOCKQUOTE>")
    assert "<blockquote expandable>" in out


def test_normalize_blockquote_handles_multiple():
    out = normalize_blockquote("<blockquote>a</blockquote> <blockquote>b</blockquote>")
    assert out.count("<blockquote expandable>") == 2


# ── validate_post_draft: happy path ───────────────────────────────────────


def test_validate_happy_path_caption():
    result = validate_post_draft(
        text="<b>Интересное:</b> сессия выросла на 18%.",
        has_media=True,
        category="C",
        entity_id="session_length_2026_04_24",
        recent=[("C", "dau_delta_2026_04_23"), ("A", "popup_at_meme_5")],
    )
    assert result.ok, result.errors
    assert result.errors == []


# ── HTML whitelist ────────────────────────────────────────────────────────


def test_validate_rejects_disallowed_tag():
    result = validate_post_draft(
        text="<div>broken</div>",
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    assert any("div" in e for e in result.errors)


def test_validate_rejects_anchor_without_href():
    result = validate_post_draft(
        text="<a>click</a>",
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    assert any("href" in e.lower() for e in result.errors)


def test_validate_rejects_xhref_bypass():
    # 'href=' as a substring inside another attribute name (xhref) must NOT
    # satisfy the href-required check. Substring match was a real bug.
    result = validate_post_draft(
        text='<a xhref="https://evil">click</a>',
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    assert any("href" in e.lower() for e in result.errors)


@pytest.mark.parametrize(
    "bad_href",
    [
        '<a href="javascript:alert(1)">x</a>',
        '<a href="data:text/plain,hi">x</a>',
        '<a href="vbscript:msgbox(1)">x</a>',
        '<a href="file:///etc/passwd">x</a>',
    ],
)
def test_validate_rejects_unsafe_href_schemes(bad_href):
    result = validate_post_draft(text=bad_href, has_media=True, category="C", entity_id="e")
    assert not result.ok
    assert any("unsafe scheme" in e.lower() for e in result.errors)


def test_validate_rejects_unclosed_tag():
    result = validate_post_draft(
        text="<b>unclosed",
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    assert any("Unclosed" in e for e in result.errors)


def test_validate_rejects_nested_blockquote():
    result = validate_post_draft(
        text="<blockquote>outer <blockquote>inner</blockquote></blockquote>",
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    assert any("Nested" in e for e in result.errors)


def test_validate_accepts_all_whitelisted_tags():
    body = (
        "<b>b</b> <strong>s</strong> <i>i</i> <em>e</em> <code>c</code> "
        '<a href="https://t.me/ffmemesbot">l</a> '
        "<blockquote>q</blockquote>"
    )
    result = validate_post_draft(text=body, has_media=True, category="A", entity_id="feat_x")
    assert result.ok, result.errors


def test_whitelist_contains_expected_set():
    # Guard against accidental addition of risky tags.
    assert ALLOWED_HTML_TAGS == {"b", "strong", "i", "em", "code", "a", "blockquote"}


# ── Banned substrings / patterns ──────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_text",
    [
        "мы пофиксили describe_memes",
        "Circuit breaker сработал на параметрах",
        "OpenRouter упал, всё пропало",
        "А/B тест показал что",
        "день 11/14 GOAT-фильтра идёт",
        "Day 5/7 of the feature rollout",
        "итерация эксперимента номер три",
    ],
)
def test_validate_rejects_banned(bad_text):
    result = validate_post_draft(text=bad_text, has_media=True, category="C", entity_id="e")
    assert not result.ok, f"expected ban on: {bad_text!r}"


def test_validate_banned_patterns_message_useful():
    result = validate_post_draft(
        text="день 12/14 эксперимента",
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    joined = " ".join(result.errors)
    # Error should mention iteration updates are banned.
    assert "iteration" in joined.lower() or "N/M" in joined or "12/14" in joined


# ── Length cap ────────────────────────────────────────────────────────────


def test_validate_rejects_caption_over_1024():
    result = validate_post_draft(
        text="A" * (TELEGRAM_CAPTION_MAX + 1),
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert not result.ok
    assert any("Too long" in e for e in result.errors)


def test_validate_accepts_caption_at_limit():
    result = validate_post_draft(
        text="A" * TELEGRAM_CAPTION_MAX,
        has_media=True,
        category="C",
        entity_id="e",
    )
    assert result.ok


def test_validate_allows_longer_text_when_no_media():
    result = validate_post_draft(
        text="A" * (TELEGRAM_CAPTION_MAX + 100),
        has_media=False,
        category="C",
        entity_id="e",
    )
    assert result.ok


# ── Rotation ──────────────────────────────────────────────────────────────


def test_validate_rejects_rotation_clash():
    result = validate_post_draft(
        text="<b>hi</b>",
        has_media=True,
        category="C",
        entity_id="dau_delta_2026_04_24",
        recent=[("C", "dau_delta_2026_04_24")],
    )
    assert not result.ok
    assert any("Rotation" in e for e in result.errors)


def test_validate_passes_rotation_with_distinct_entity():
    result = validate_post_draft(
        text="<b>hi</b>",
        has_media=True,
        category="C",
        entity_id="source_climber_2026_04_24",
        recent=[("C", "dau_delta_2026_04_24")],
    )
    assert result.ok


# ── Metadata ──────────────────────────────────────────────────────────────


def test_validate_requires_category_and_entity():
    result = validate_post_draft(text="<b>hi</b>", has_media=True, category="", entity_id="")
    assert not result.ok
    joined = " ".join(result.errors)
    assert "category" in joined.lower()
    assert "entity_id" in joined.lower()


def test_validate_requires_nonempty_text():
    result = validate_post_draft(text="   ", has_media=True, category="C", entity_id="e")
    assert not result.ok
    assert any("Empty" in e for e in result.errors)


# ── Draft hash ────────────────────────────────────────────────────────────


def test_compute_draft_hash_is_stable():
    a = compute_draft_hash("ru", "hello", "file_id_1", "C", "e1")
    b = compute_draft_hash("ru", "hello", "file_id_1", "C", "e1")
    assert a == b
    assert len(a) == 32


def test_compute_draft_hash_differs_on_any_field():
    base = compute_draft_hash("ru", "hello", "f1", "C", "e1")
    assert base != compute_draft_hash("en", "hello", "f1", "C", "e1")
    assert base != compute_draft_hash("ru", "hi", "f1", "C", "e1")
    assert base != compute_draft_hash("ru", "hello", "f2", "C", "e1")
    assert base != compute_draft_hash("ru", "hello", "f1", "A", "e1")
    assert base != compute_draft_hash("ru", "hello", "f1", "C", "e2")


def test_compute_draft_hash_includes_button():
    base = compute_draft_hash("ru", "hello", "f1", "C", "e1")
    with_button = compute_draft_hash(
        "ru", "hello", "f1", "C", "e1", button_text="Открыть", button_url="https://t.me/x"
    )
    assert base != with_button
    # Different URL → different hash even if text identical.
    assert with_button != compute_draft_hash(
        "ru", "hello", "f1", "C", "e1", button_text="Открыть", button_url="https://t.me/y"
    )
    # Different text → different hash even if URL identical.
    assert with_button != compute_draft_hash(
        "ru", "hello", "f1", "C", "e1", button_text="Поехали", button_url="https://t.me/x"
    )


# ── Channel routing ───────────────────────────────────────────────────────


def test_allowed_channels_includes_ffmemes():
    # @ffmemes (build-in-public/product/process) is a sanctioned target.
    assert ALLOWED_CHANNELS == {"ru", "en", "ffmemes"}


def test_post_editorial_to_channel_routes_ffmemes_to_correct_chat_id():
    from src.flows.crossposting.editorial import CHANNEL_CHAT_IDS
    from src.tgbot.constants import (
        TELEGRAM_CHANNEL_EN_CHAT_ID,
        TELEGRAM_CHANNEL_FFMEMES_CHAT_ID,
        TELEGRAM_CHANNEL_RU_CHAT_ID,
    )

    assert CHANNEL_CHAT_IDS == {
        "ru": TELEGRAM_CHANNEL_RU_CHAT_ID,
        "en": TELEGRAM_CHANNEL_EN_CHAT_ID,
        "ffmemes": TELEGRAM_CHANNEL_FFMEMES_CHAT_ID,
    }
    # Hard-coded per the issue spec — keep these wired to the right chat ids.
    assert TELEGRAM_CHANNEL_FFMEMES_CHAT_ID == -1001472939243
    assert TELEGRAM_CHANNEL_RU_CHAT_ID == -1001152876229
    assert TELEGRAM_CHANNEL_EN_CHAT_ID == -1002120551028
