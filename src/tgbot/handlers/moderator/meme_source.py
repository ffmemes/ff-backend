import re
from dataclasses import dataclass
from html import escape as html_escape
from typing import Any

from telegram import Message, Update
from telegram.ext import (
    ContextTypes,
)

from src import localizer
from src.flows.parsers.tg import parse_telegram_source
from src.flows.parsers.vk import parse_vk_source
from src.storage.constants import MemeSourceStatus, MemeSourceType
from src.storage.etl import normalize_telegram_channel_url
from src.storage.moderation import (
    MemeSourceNotFoundError,
    advance_meme_source,
)
from src.tgbot.handlers.moderator.permissions import get_moderator_user_info
from src.tgbot.logs import log
from src.tgbot.senders.keyboards import (
    meme_source_change_status_keyboard,
    meme_source_language_selection_keyboard,
)
from src.tgbot.senders.utils import send_or_edit
from src.tgbot.service import (
    get_meme_source_stats_by_id,
    get_or_create_meme_source,
)

MEME_SOURCE_LINK_REGEXP = (
    r"(?i)(?:https?://)?(?:t\.me|telegram\.me|vk\.com|(?:www\.)?instagram\.com)/[^\s<>()]+"
)

_MEME_SOURCE_LINK_RE = re.compile(MEME_SOURCE_LINK_REGEXP)


def _t(key: str, lang: str | None, **kwargs: object) -> str:
    text = localizer.t(key, lang)
    return text.format(**kwargs) if kwargs else text


@dataclass(frozen=True)
class MemeSourceLink:
    url: str
    type: MemeSourceType


def parse_meme_source_link(text: str | None) -> MemeSourceLink | None:
    if not text:
        return None

    match = _MEME_SOURCE_LINK_RE.search(text.strip())
    if match is None:
        return None

    url = match.group(0).rstrip(".,)")
    url_lower = url.lower()
    if url_lower.startswith(("t.me/", "telegram.me/", "vk.com/", "instagram.com/")):
        url = f"https://{url}"

    normalized_lower = url.lower()
    if "t.me/" in normalized_lower or "telegram.me/" in normalized_lower:
        canonical = normalize_telegram_channel_url(url)
        if canonical is None:
            return None
        return MemeSourceLink(url=canonical, type=MemeSourceType.TELEGRAM)

    if "vk.com/" in normalized_lower:
        return MemeSourceLink(url=url.split("?", 1)[0], type=MemeSourceType.VK)

    if "instagram.com/" in normalized_lower:
        return MemeSourceLink(url=url.split("?", 1)[0], type=MemeSourceType.INSTAGRAM)

    return None


def parse_meme_source_status_callback_data(data: str) -> tuple[int, str]:
    _, meme_source_id, _, raw_status = data.split(":", maxsplit=3)
    if raw_status.startswith("MemeSourceStatus."):
        status_name = raw_status.split(".", maxsplit=1)[1]
        return int(meme_source_id), MemeSourceStatus[status_name].value

    return int(meme_source_id), raw_status


async def handle_meme_source_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    moderator = await get_moderator_user_info(update.effective_user.id)
    lang = _get_moderator_lang(update, moderator)
    if moderator is None:
        await update.message.reply_text(_t("moderator.meme_source.only_moderators_manage", lang))
        return

    link = parse_meme_source_link(update.message.text)
    if link is None:
        await update.message.reply_text(_t("moderator.meme_source.unsupported_source", lang))
        return

    meme_source = await get_or_create_meme_source(
        url=link.url,
        type=link.type,
        status=MemeSourceStatus.IN_MODERATION,
        added_by=update.effective_user.id,
    )

    await meme_source_admin_pipeline(meme_source, update, lang)


async def handle_meme_source_language_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    moderator = await get_moderator_user_info(user_id)
    lang = _get_moderator_lang(update, moderator)
    if moderator is None:
        await update.callback_query.answer(
            _t("moderator.meme_source.only_moderators_language", lang)
        )
        return

    args = update.callback_query.data.split(":")
    meme_source_id, lang_code = int(args[1]), args[3]

    try:
        result = await advance_meme_source(
            meme_source_id,
            moderator_id=str(user_id),
            language_code=lang_code,
            trigger_parse=False,
        )
    except MemeSourceNotFoundError:
        await update.callback_query.answer(_t("moderator.meme_source.not_found", lang))
        return

    await log(
        f"ℹ️ MemeSource ${meme_source_id}: set_lang={lang_code} (by {user_id})",
        context.bot,
    )

    await update.callback_query.answer(
        _t("moderator.meme_source.language_updated", lang, language=lang_code)
    )
    await meme_source_admin_pipeline(result["source"], update, lang)


async def handle_meme_source_change_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    moderator = await get_moderator_user_info(user_id)
    lang = _get_moderator_lang(update, moderator)
    if moderator is None:
        await update.callback_query.answer(_t("moderator.meme_source.only_moderators_status", lang))
        return

    try:
        meme_source_id, status = parse_meme_source_status_callback_data(update.callback_query.data)
    except (IndexError, KeyError, ValueError):
        await update.callback_query.answer(_t("moderator.meme_source.invalid_status_action", lang))
        return

    try:
        # `trigger_parse=False` keeps parse-after-UI ordering: we want the
        # moderator to see the keyboard refresh before we await the parser.
        result = await advance_meme_source(
            meme_source_id,
            moderator_id=str(user_id),
            status=status,
            trigger_parse=False,
        )
    except MemeSourceNotFoundError:
        await update.callback_query.answer(
            _t("moderator.meme_source.not_found_by_id", lang, source_id=meme_source_id)
        )
        return
    except ValueError as e:
        await update.callback_query.answer(str(e)[:180])
        return

    if result["unsnoozed_count"]:
        await update.effective_chat.send_message(
            _t(
                "moderator.meme_source.unsnoozed_memes",
                lang,
                count=result["unsnoozed_count"],
                source_id=meme_source_id,
            )
        )

    await log(
        f"ℹ️ MemeSource ${meme_source_id}: set_status={status} (by {user_id})",
        context.bot,
    )

    await update.callback_query.answer(
        _t(
            "moderator.meme_source.status_updated",
            lang,
            status=_status_label(status, lang),
        )
    )
    await meme_source_admin_pipeline(result["source"], update, lang)

    meme_source = result["source"]
    if status == MemeSourceStatus.PARSING_ENABLED:  # trigger parsing
        # TODO: async
        if meme_source["type"] == MemeSourceType.VK:
            await parse_vk_source(meme_source_id, meme_source["url"])
        elif meme_source["type"] == MemeSourceType.TELEGRAM:
            await parse_telegram_source(meme_source_id, meme_source["url"])

    if result["snoozed_count"]:
        await update.effective_chat.send_message(
            _t(
                "moderator.meme_source.snoozed_memes",
                lang,
                count=result["snoozed_count"],
                source_id=meme_source_id,
            )
        )


def _get_moderator_lang(
    update: Update,
    moderator_info: dict[str, Any] | None = None,
) -> str | None:
    if moderator_info and moderator_info.get("interface_lang"):
        return str(moderator_info["interface_lang"])
    if update.effective_user and getattr(update.effective_user, "language_code", None):
        return update.effective_user.language_code
    return "ru"


def _html(value: object) -> str:
    if value is None:
        return "—"
    return html_escape(str(value), quote=False)


def _source_type_label(source_type: object) -> str:
    value = getattr(source_type, "value", source_type)
    if value == MemeSourceType.TELEGRAM.value:
        return "Telegram"
    if value == MemeSourceType.INSTAGRAM.value:
        return "Instagram"
    if value == MemeSourceType.VK.value:
        return "VK"
    return _html(value)


def _status_label(status: object, lang: str | None) -> str:
    value = getattr(status, "value", status)
    try:
        return localizer.t(f"moderator.meme_source.status.{value}", lang)
    except KeyError:
        return _html(value)


def _format_int(value: object) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _format_latest_age(value: object, lang: str | None) -> str:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return "—"

    if days <= 0:
        return localizer.t("moderator.meme_source.today", lang)

    return _t("moderator.meme_source.days_short", lang, days=days)


def _get_meme_source_info(meme_source: dict, lang: str | None) -> str:
    source_type = _source_type_label(meme_source["type"])
    language = _html(meme_source["language_code"])
    added_by = _html(meme_source["added_by"])
    status = _status_label(meme_source["status"], lang)

    return _t(
        "moderator.meme_source.card",
        lang,
        id=_html(meme_source["id"]),
        type=source_type,
        language=language,
        url=_html(meme_source["url"]),
        status=status,
        added_by=added_by,
    )


def _get_meme_source_stats_info(meme_source_stats: dict, lang: str | None) -> str:
    return _t(
        "moderator.meme_source.stats",
        lang,
        likes=_format_int(meme_source_stats["nlikes"]),
        dislikes=_format_int(meme_source_stats["ndislikes"]),
        sent_events=_format_int(meme_source_stats["nmemes_sent_events"]),
        parsed=_format_int(meme_source_stats["nmemes_parsed"]),
        sent=_format_int(meme_source_stats["nmemes_sent"]),
        latest_age=_format_latest_age(meme_source_stats["latest_meme_age"], lang),
    )


async def meme_source_admin_pipeline(
    meme_source: dict,
    update: Update,
    lang: str | None = None,
) -> Message:
    if lang is None:
        lang = _get_moderator_lang(update)

    ms_info = _get_meme_source_info(meme_source, lang)
    ms_stats = await get_meme_source_stats_by_id(meme_source["id"])
    if ms_stats:
        ms_info += "\n\n" + _get_meme_source_stats_info(ms_stats, lang)

    if meme_source["language_code"] is None:
        return await send_or_edit(
            update,
            text=f"{ms_info}\n\n{localizer.t('moderator.meme_source.select_language', lang)}",
            reply_markup=meme_source_language_selection_keyboard(meme_source_id=meme_source["id"]),
        )

    return await send_or_edit(
        update,
        text=ms_info,
        reply_markup=meme_source_change_status_keyboard(
            meme_source["id"],
            meme_source["status"],
            lang,
        ),
    )
