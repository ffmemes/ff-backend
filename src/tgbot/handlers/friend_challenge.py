"""Friend challenge (H12): confirm five memes, invite a friend, then enter the feed."""

import logging
import re
from urllib.parse import urlencode

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from src.config import settings
from src.localizer import t
from src.recommendations.meme_queue import clear_meme_queue_for_user
from src.storage.schemas import MemeData
from src.tgbot.handlers.language import resolve_onboarding_auto_language
from src.tgbot.repo import friend_challenge as repo
from src.tgbot.senders.meme import send_new_message_with_meme
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import get_user_languages, set_user_languages_exclusive, update_user
from src.tgbot.user_info import get_user_info, update_user_info_cache

logger = logging.getLogger(__name__)
CHALLENGE_PREFIX = "fc_"
CALLBACK_PATTERN = r"^fc:"
TOKEN_PATTERN = re.compile(r"^fc_([A-Za-z0-9_-]{24})$")


def parse_challenge_token(deep_link: str | None) -> str | None:
    match = TOKEN_PATTERN.fullmatch(deep_link or "")
    return match.group(1) if match else None


def challenge_url(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={CHALLENGE_PREFIX}{token}"


def _private(update: Update) -> bool:
    return bool(
        update.effective_user
        and update.effective_chat
        and update.effective_chat.type == "private"
        and update.effective_chat.id == update.effective_user.id
    )


def _button(key: str, lang: str | None, action: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(t(key, lang), callback_data=f"fc:{action}")]


def _feed_keyboard(lang: str | None, pack_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_button("friend_feed", lang, f"feed:{pack_id}")])


async def _language(update: Update) -> str | None:
    info = await get_user_info(update.effective_user.id)
    return info.get("interface_lang") or update.effective_user.language_code


async def _ensure_languages(update: Update, pack: dict | None = None) -> None:
    user_id = update.effective_user.id
    if await get_user_languages(user_id):
        return
    languages = list(
        dict.fromkeys(
            item["language_code"]
            for item in (pack or {}).get("items", [])
            if item.get("language_code")
        )
    )
    await set_user_languages_exclusive(
        user_id, languages or [resolve_onboarding_auto_language(update.effective_user) or "en"]
    )
    await update_user_info_cache(user_id)


async def _open_feed(bot: Bot, update: Update, pack: dict | None = None) -> None:
    user_id = update.effective_user.id
    await _ensure_languages(update, pack)
    if pack is not None:
        await repo.seed_answers_as_reactions(pack["id"], user_id)
        await clear_meme_queue_for_user(user_id)
        await update_user_info_cache(user_id)
    await next_message(bot, user_id, update, skip_popups=True)


async def maybe_offer_challenge(bot: Bot, user_id: int, meme_id: int, user_info: dict) -> None:
    """After an ordinary like: assign eligible users (90/10), offer treatment once."""
    if not settings.FRIEND_CHALLENGE_ENABLED:
        return
    assignment = await repo.get_or_assign_variant(user_id)
    if (
        assignment is None
        or assignment["variant"] != repo.TREATMENT
        or "offer_attempted_at" in assignment["assignment_metadata"]
        or not await repo.claim_offer(user_id, meme_id)
    ):
        return
    lang = user_info.get("interface_lang")
    await bot.send_message(
        user_id,
        t("friend_offer", lang),
        reply_markup=InlineKeyboardMarkup(
            [_button("friend_create", lang, "create"), _button("friend_dismiss", lang, "dismiss")]
        ),
    )
    await repo.mark_offer_sent(user_id)


async def _send_link(bot: Bot, user_id: int, pack: dict, lang: str | None) -> None:
    share_url = "https://t.me/share/url?" + urlencode(
        {"url": challenge_url(pack["token"]), "text": t("friend_invitation", lang)}
    )
    await bot.send_message(
        user_id,
        f"{t('friend_link_ready', lang)}\n{challenge_url(pack['token'])}",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(t("friend_share", lang), url=share_url)],
                _button("friend_feed", lang, "feed:0"),
            ]
        ),
    )


async def _send_item(bot: Bot, user_id: int, item: dict, lang: str | None, keyboard=None):
    if not item.get("meme_id") or item.get("status") != "ok" or not item.get("telegram_file_id"):
        return None
    # No ordinary delivery/reaction bookkeeping, share rewards or popups.
    caption = "\n\n".join(
        filter(
            None,
            [
                (item.get("caption") or "")[:850],
                t("friend_position", lang).format(position=item["position"]),
            ],
        )
    )
    meme = MemeData(
        id=item["meme_id"],
        type=item["type"],
        telegram_file_id=item["telegram_file_id"],
        caption=caption,
    )
    return await send_new_message_with_meme(bot, user_id, meme, keyboard)


async def _create(bot: Bot, user_id: int, lang: str | None) -> None:
    pack = await repo.get_owner_pack(user_id)
    if pack and pack["confirmed_at"]:
        return await _send_link(bot, user_id, pack, lang)
    if not await repo.authorized_to_create(user_id):
        return await bot.send_message(
            user_id, t("friend_not_enrolled", lang), reply_markup=_feed_keyboard(lang)
        )
    if pack is None:
        meme_ids = await repo.candidate_meme_ids(user_id)
        if len(meme_ids) != repo.PACK_SIZE:
            return await bot.send_message(
                user_id, t("friend_not_enough", lang), reply_markup=_feed_keyboard(lang)
            )
        try:
            pack = await repo.get_or_create_owner_pack(user_id, meme_ids)
        except ValueError:
            return await bot.send_message(
                user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang)
            )
    await bot.send_message(user_id, t("friend_preview", lang))
    for item in pack["items"]:
        try:
            sent = await _send_item(bot, user_id, item, lang)
        except TelegramError:
            logger.warning("Friend challenge preview delivery failed", exc_info=True)
            sent = None
        if not sent:
            return await bot.send_message(
                user_id,
                t("friend_send_failed", lang),
                reply_markup=InlineKeyboardMarkup(
                    [
                        _button("friend_create", lang, "create"),
                        _button("friend_feed", lang, "feed:0"),
                    ]
                ),
            )
    await bot.send_message(
        user_id,
        t("friend_confirm_prompt", lang),
        reply_markup=InlineKeyboardMarkup(
            [
                _button("friend_confirm", lang, f"confirm:{pack['id']}"),
                _button("friend_feed", lang, "feed:0"),
            ]
        ),
    )


async def _show_progress(bot: Bot, user_id: int, pack: dict, lang: str | None) -> None:
    progress = await repo.get_progress(pack["id"], user_id)
    if progress is None:
        return
    if progress["completed_at"]:
        await repo.seed_answers_as_reactions(pack["id"], user_id)
        rows = [_button("friend_feed", lang, f"feed:{pack['id']}")]
        if await repo.authorized_to_create(user_id):
            rows.append(_button("friend_create", lang, "create"))
        return await bot.send_message(
            user_id,
            t("friend_result", lang).format(liked=progress["liked_count"]),
            reply_markup=InlineKeyboardMarkup(rows),
        )
    position = progress["next_position"]
    item = next((i for i in pack["items"] if i["position"] == position), None)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("friend_funny", lang), callback_data=f"fc:a:{pack['id']}:{position}:1"
                ),
                InlineKeyboardButton(
                    t("friend_pass", lang), callback_data=f"fc:a:{pack['id']}:{position}:0"
                ),
            ],
            _button("friend_feed", lang, f"feed:{pack['id']}"),
        ]
    )
    try:
        sent = item is not None and await _send_item(bot, user_id, item, lang, keyboard)
    except TelegramError:
        logger.warning("Friend challenge media delivery failed", exc_info=True)
        return await bot.send_message(
            user_id,
            t("friend_send_failed", lang),
            reply_markup=InlineKeyboardMarkup(
                [
                    _button("friend_resume", lang, f"resume:{pack['id']}"),
                    _button("friend_feed", lang, f"feed:{pack['id']}"),
                ]
            ),
        )
    if not sent:
        await bot.send_message(
            user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang, pack["id"])
        )


async def handle_challenge_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, deep_link: str, *, created: bool
) -> None:
    """/start fc_<token>. Callers route here only while the flag is on."""
    if not _private(update):
        return
    user_id = update.effective_user.id
    token = parse_challenge_token(deep_link)
    pack = await repo.get_public_pack(token) if token else None
    await _ensure_languages(update, pack if created else None)
    lang = await _language(update)
    if pack is None:
        await context.bot.send_message(user_id, t("friend_unavailable", lang))
        return await next_message(context.bot, user_id, update, skip_popups=True)
    if pack["owner_id"] == user_id:
        return await _send_link(context.bot, user_id, pack, lang)
    if created:
        # Same attribution column as meme-share invites; set once, at registration.
        await update_user(user_id, inviter_id=pack["owner_id"])
    if await repo.start_participation(pack["id"], user_id) is None:
        return await context.bot.send_message(
            user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang)
        )
    await _show_progress(context.bot, user_id, pack, lang)


async def handle_friend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    lang = await _language(update)
    if not settings.FRIEND_CHALLENGE_ENABLED:
        return await context.bot.send_message(
            update.effective_user.id,
            t("friend_unavailable", lang),
            reply_markup=_feed_keyboard(lang),
        )
    await _create(context.bot, update.effective_user.id, lang)


async def _remove_buttons(update: Update) -> None:
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass


async def handle_friend_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _private(update):
        return
    await update.callback_query.answer()
    bot, user_id = context.bot, update.effective_user.id
    lang = await _language(update)
    parts = update.callback_query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "dismiss":
        return await _remove_buttons(update)
    if action == "feed" and (not settings.FRIEND_CHALLENGE_ENABLED or parts[2:] == ["0"]):
        return await _open_feed(bot, update)
    if not settings.FRIEND_CHALLENGE_ENABLED:
        return await bot.send_message(
            user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang)
        )
    if action == "create":
        return await _create(bot, user_id, lang)
    try:
        pack_id = int(parts[2])
    except (IndexError, ValueError):
        return
    pack = await repo.get_pack(pack_id)
    if not pack:
        return await bot.send_message(
            user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang)
        )
    if action == "confirm":
        confirmed = await repo.authorized_to_create(user_id) and await repo.confirm_owner_pack(
            user_id, pack_id
        )
        if not confirmed:
            return await bot.send_message(
                user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang)
            )
        await _remove_buttons(update)
        return await _send_link(bot, user_id, confirmed, lang)
    if await repo.get_progress(pack_id, user_id) is None:
        return await bot.send_message(
            user_id, t("friend_unavailable", lang), reply_markup=_feed_keyboard(lang)
        )
    if action == "feed":
        return await _open_feed(bot, update, pack)
    if action == "a" and len(parts) == 5 and parts[4] in {"0", "1"} and parts[3].isdigit():
        answer = await repo.record_answer(pack_id, user_id, int(parts[3]), parts[4] == "1")
        if not answer["changed"]:
            return await bot.send_message(
                user_id,
                t("friend_saved", lang),
                reply_markup=InlineKeyboardMarkup(
                    [_button("friend_resume", lang, f"resume:{pack_id}")]
                ),
            )
        await _remove_buttons(update)
    elif action != "resume":
        return
    await _show_progress(bot, user_id, pack, lang)
