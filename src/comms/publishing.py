"""
Single entry point for publishing editorial posts to @ffmemes channels.

The Comms Agent calls `publish_editorial_post(...)` — that function validates
the draft, posts it as ONE Telegram message via `post_editorial_to_channel`,
and persists metadata to `editorial_posts` so the stats collector can track
it. Raw `curl`/Bot API calls are banned; this module is the only sanctioned
path.

Invariants enforced here (not in prompt):
- One-message publishing (sendPhoto with caption, single call).
- Caption length ≤ 1024 chars when media is attached (Telegram hard limit).
- HTML tag whitelist (b, strong, i, em, code, a, blockquote).
- `<blockquote>` is always rewritten to `<blockquote expandable>`.
- Substring/pattern ban (describe_memes, circuit breakers, A/B iteration updates).
- Category+entity rotation check against the last 14 editorial posts.
- Idempotency via SHA256 `draft_hash`. The hash row is INSERTED before the
  Telegram send (telegram_message_id NULL), then UPDATED with the real id
  after send returns. A retry that races with a previous in-flight call
  loses the ON CONFLICT and refuses to double-post; a retry after the
  previous call succeeded short-circuits via the existing-row fast path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.database import editorial_posts, execute, fetch_all, fetch_one

VALIDATION_VERSION = 1

# Telegram Bot API caption limit for sendPhoto (chars, not bytes).
TELEGRAM_CAPTION_MAX = 1024
# Telegram Bot API text limit for sendMessage.
TELEGRAM_MESSAGE_MAX = 4096

# HTML tag whitelist. Agent-facing tone: casual, concise — these 5 cover it.
ALLOWED_HTML_TAGS = {"b", "strong", "i", "em", "code", "a", "blockquote"}

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9\-]*)([^>]*)>")
_BLOCKQUOTE_OPEN_RE = re.compile(r"<blockquote(\s[^>]*)?>", re.IGNORECASE)
# Match a real `href=` attribute, not a substring of e.g. `xhref=`. Requires a
# non-letter (or start-of-attrs) before `href` so `xhref=` is rejected.
_HREF_ATTR_RE = re.compile(r"(?:^|[^a-z])href\s*=", re.IGNORECASE)
_HREF_VALUE_RE = re.compile(r"href\s*=\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)

BANNED_SUBSTRINGS: tuple[str, ...] = (
    "describe_memes",
    "describe memes",
    "circuit breaker",
    "openrouter",
    "free tier",
    "rate limit",
    "402 error",
    "deploy rollback",
    "rollback",
    "crashed",
    "fixed bug",
    "ab test",
    "a/b test",
    # Russian forms — agent writes in Russian for @ffmemes.
    "а/б тест",
    "аб-тест",
    "сплит-тест",
)

# Regex patterns for banned content structures.
BANNED_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "день 11/14", "day 12/14" — in-progress experiment iteration updates.
    re.compile(r"день\s+\d+\s*/\s*\d+", re.IGNORECASE),
    re.compile(r"\bday\s+\d+\s*/\s*\d+", re.IGNORECASE),
    # "итерация эксперимента" — experiments-in-progress framing.
    re.compile(r"итерация\s+эксперимента", re.IGNORECASE),
    # "A/B тест", "А/B test", "а/b тест" — every mixed-script combination of
    # Cyrillic/Latin a-b around a slash followed by test/тест. This is the
    # bypass that the prompt-level HARD BAN couldn't catch.
    re.compile(r"[аa]\s*/\s*[бbв]\s*[-–\s]?\s*(?:test|тест)", re.IGNORECASE),
)

# Cyrillic → Latin lookalike map. Used by _normalize_lookalikes() before the
# substring/pattern ban check so that mixed-script evasion (e.g. Cyrillic А
# in "А/B тест") cannot route around the ban list.
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "А": "a",
        "е": "e",
        "Е": "e",
        "о": "o",
        "О": "o",
        "р": "p",
        "Р": "p",
        "с": "c",
        "С": "c",
        "у": "y",
        "У": "y",
        "х": "x",
        "Х": "x",
        "к": "k",
        "К": "k",
        "в": "b",
        "В": "b",
        "м": "m",
        "М": "m",
        "т": "t",
        "Т": "t",
        "н": "h",
        "Н": "h",
    }
)


def _normalize_lookalikes(text: str) -> str:
    """Fold Cyrillic homoglyphs to Latin for ban-list matching only.

    Applied before substring/pattern checks; never to the posted text.
    """
    return text.translate(_CYRILLIC_TO_LATIN)


ALLOWED_CHANNELS = frozenset({"ru", "en", "ffmemes"})


class EditorialValidationError(Exception):
    """Raised when a draft fails validation. The agent must fix and retry."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Draft rejected: " + "; ".join(errors))


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class EditorialPostResult:
    message_id: int
    editorial_post_id: int
    already_posted: bool
    normalized_text: str


def normalize_blockquote(text: str) -> str:
    """Rewrite every <blockquote> to <blockquote expandable>.

    User preference: expandable by default. If the agent already wrote
    `<blockquote expandable>`, leave it alone.
    """

    def repl(match: re.Match[str]) -> str:
        attrs = (match.group(1) or "").strip()
        if "expandable" in attrs.lower():
            return match.group(0)
        return "<blockquote expandable>"

    return _BLOCKQUOTE_OPEN_RE.sub(repl, text)


def _validate_html(text: str) -> list[str]:
    errors: list[str] = []
    stack: list[str] = []
    for match in _TAG_RE.finditer(text):
        closing = match.group(1) == "/"
        tag = match.group(2).lower()
        attrs = match.group(3) or ""
        if tag not in ALLOWED_HTML_TAGS:
            errors.append(
                f"Disallowed HTML tag <{tag}>. Allowed: " + ", ".join(sorted(ALLOWED_HTML_TAGS))
            )
            continue
        if closing:
            if not stack or stack[-1] != tag:
                errors.append(f"Mismatched closing tag </{tag}>")
            else:
                stack.pop()
            continue
        if tag == "a":
            if not _HREF_ATTR_RE.search(attrs):
                errors.append("<a> tag missing href attribute")
            else:
                href_match = _HREF_VALUE_RE.search(attrs)
                if href_match:
                    scheme = href_match.group(1).strip().lower()
                    if scheme.startswith(("javascript:", "data:", "vbscript:", "file:")):
                        errors.append(f"<a> href uses unsafe scheme: {scheme.split(':', 1)[0]}:")
        if tag == "blockquote" and stack and "blockquote" in stack:
            errors.append("Nested <blockquote> is not supported by Telegram")
        stack.append(tag)
    if stack:
        errors.append(f"Unclosed HTML tags: {', '.join(stack)}")
    return errors


def _check_banned(text: str) -> list[str]:
    errors: list[str] = []
    # Fold Cyrillic homoglyphs to Latin so mixed-script bypass (e.g. Cyrillic А
    # in "А/B тест") still trips the ban list. Patterns are checked against
    # both forms because the Cyrillic-only patterns (день, итерация) need the
    # original characters.
    lower = text.lower()
    folded = _normalize_lookalikes(lower)
    for needle in BANNED_SUBSTRINGS:
        if needle in lower or needle in folded:
            errors.append(f"Banned substring: '{needle}' — topic violates HARD BAN")
    for pattern in BANNED_PATTERNS:
        m = pattern.search(text) or pattern.search(folded)
        if m:
            errors.append(
                f"Banned pattern: '{m.group(0)}' — A/B iteration updates are banned, "
                "post the conclusive learning instead"
            )
    return errors


def _check_length(text: str, has_media: bool) -> list[str]:
    limit = TELEGRAM_CAPTION_MAX if has_media else TELEGRAM_MESSAGE_MAX
    # Length check is on the final text Telegram will see. HTML tags DO count
    # toward the caption limit in the Bot API. We keep the agent safely under.
    if len(text) > limit:
        kind = "caption" if has_media else "text"
        return [
            f"Too long: {len(text)} chars > {limit} {kind} limit. "
            "Splitting into two messages is banned — shorten or move details "
            "into <blockquote expandable>."
        ]
    return []


def _check_rotation(
    category: str,
    entity_id: str,
    recent: Iterable[tuple[str | None, str | None]],
) -> list[str]:
    for rc, re_ in recent:
        if rc == category and re_ == entity_id:
            return [
                f"Rotation violation: category={category!r} entity={entity_id!r} "
                "was published in the last 14 editorial posts. Pick a different anomaly."
            ]
    return []


def validate_post_draft(
    text: str,
    has_media: bool,
    category: str,
    entity_id: str,
    recent: Iterable[tuple[str | None, str | None]] = (),
) -> ValidationResult:
    """Validate a post draft. Returns ValidationResult — does not raise."""
    errors: list[str] = []
    if not text.strip():
        errors.append("Empty post text")
    if not category:
        errors.append("Missing category (A-F)")
    if not entity_id:
        errors.append("Missing entity_id (specific source/metric/feature)")
    errors.extend(_validate_html(text))
    errors.extend(_check_banned(text))
    errors.extend(_check_length(text, has_media))
    errors.extend(_check_rotation(category, entity_id, recent))
    return ValidationResult(ok=not errors, errors=errors)


def compute_draft_hash(
    channel: str,
    text: str,
    photo_key: str | None,
    category: str,
    entity_id: str,
    button_text: str | None = None,
    button_url: str | None = None,
) -> str:
    blob = "|".join(
        [
            channel,
            category,
            entity_id,
            photo_key or "",
            button_text or "",
            button_url or "",
            text,
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


async def _recent_rotation_keys(
    channel: str, limit: int = 14
) -> list[tuple[str | None, str | None]]:
    rows = await fetch_all(
        select(editorial_posts.c.category, editorial_posts.c.entity_id)
        .where(editorial_posts.c.channel == channel)
        .order_by(editorial_posts.c.created_at.desc())
        .limit(limit)
    )
    return [(r["category"], r["entity_id"]) for r in (rows or [])]


async def publish_editorial_post(
    text: str,
    channel: str,
    category: str,
    entity_id: str,
    photo_file_id: str | None = None,
    photo_url: str | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
    topic_slug: str | None = None,
) -> EditorialPostResult:
    """Publish an editorial post. Single sanctioned posting path for the agent.

    Raises EditorialValidationError on validation failure — the agent must
    read the error list, fix the draft, and call again.
    """
    if channel not in ALLOWED_CHANNELS:
        raise EditorialValidationError(
            [f"Invalid channel {channel!r}; use 'ru', 'en', or 'ffmemes'"]
        )

    normalized_text = normalize_blockquote(text)
    photo_key = photo_file_id or photo_url
    has_media = bool(photo_key)

    draft_hash = compute_draft_hash(
        channel=channel,
        text=normalized_text,
        photo_key=photo_key,
        category=category,
        entity_id=entity_id,
        button_text=button_text,
        button_url=button_url,
    )

    # Fast-path: identical draft already posted (telegram_message_id set).
    existing = await fetch_one(
        select(
            editorial_posts.c.id,
            editorial_posts.c.telegram_message_id,
        ).where(editorial_posts.c.draft_hash == draft_hash)
    )
    if existing and existing["telegram_message_id"] is not None:
        return EditorialPostResult(
            message_id=existing["telegram_message_id"],
            editorial_post_id=existing["id"],
            already_posted=True,
            normalized_text=normalized_text,
        )

    recent = await _recent_rotation_keys(channel)
    result = validate_post_draft(
        text=normalized_text,
        has_media=has_media,
        category=category,
        entity_id=entity_id,
        recent=recent,
    )
    if not result.ok:
        raise EditorialValidationError(result.errors)

    # Claim the draft_hash slot BEFORE posting so a crash between TG send and
    # DB write cannot result in a re-post on retry. INSERT ON CONFLICT DO
    # NOTHING; if a row already exists with telegram_message_id IS NULL,
    # another worker is mid-send — refuse to double-post.
    claim_stmt = (
        insert(editorial_posts)
        .values(
            channel=channel,
            telegram_message_id=None,
            draft_hash=draft_hash,
            category=category,
            entity_id=entity_id,
            topic_slug=topic_slug,
            text=normalized_text,
            has_media=has_media,
            validation_version=VALIDATION_VERSION,
        )
        .on_conflict_do_nothing(index_elements=["draft_hash"])
        .returning(editorial_posts.c.id)
    )
    claim_row = await fetch_one(claim_stmt)
    if claim_row is None:
        # Lost the race — another caller already claimed this draft_hash.
        raise EditorialValidationError(
            [
                "Draft is already being published by another worker "
                "(draft_hash claim row exists with no telegram_message_id). "
                "Retry after the other call completes or fails."
            ]
        )
    editorial_post_id = claim_row["id"]

    # Import lazily — avoids pulling python-telegram-bot into the Comms agent
    # runtime for dry-run / validation-only calls in tests.
    from src.flows.crossposting.editorial import post_editorial_to_channel

    message_id = await post_editorial_to_channel(
        text=normalized_text,
        channel=channel,
        photo_file_id=photo_file_id,
        photo_url=photo_url,
        button_text=button_text,
        button_url=button_url,
    )

    await execute(
        update(editorial_posts)
        .where(editorial_posts.c.id == editorial_post_id)
        .values(telegram_message_id=message_id)
    )

    return EditorialPostResult(
        message_id=message_id,
        editorial_post_id=editorial_post_id,
        already_posted=False,
        normalized_text=normalized_text,
    )


async def mark_tracked_message_ids(channel: str) -> dict[int, int]:
    """Return {telegram_message_id: editorial_posts.id} for stats collector.

    Skips claim rows with telegram_message_id IS NULL (drafts mid-publish or
    orphaned by a crash between claim and Telegram send).
    """
    rows = await fetch_all(
        select(
            editorial_posts.c.id,
            editorial_posts.c.telegram_message_id,
        ).where(
            editorial_posts.c.channel == channel,
            editorial_posts.c.telegram_message_id.isnot(None),
        )
    )
    return {r["telegram_message_id"]: r["id"] for r in (rows or [])}


# `execute` is re-exported so tests can patch a single location if needed.
__all__ = [
    "ALLOWED_HTML_TAGS",
    "BANNED_PATTERNS",
    "BANNED_SUBSTRINGS",
    "EditorialPostResult",
    "EditorialValidationError",
    "TELEGRAM_CAPTION_MAX",
    "TELEGRAM_MESSAGE_MAX",
    "ValidationResult",
    "compute_draft_hash",
    "execute",
    "mark_tracked_message_ids",
    "normalize_blockquote",
    "publish_editorial_post",
    "validate_post_draft",
]
