import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from src import localizer
from src.flows.events import safe_emit
from src.tgbot.bot import bot
from src.tgbot.constants import POPUP_BUTTON_CALLBACK_DATA_PATTERN
from src.tgbot.schemas import Popup
from src.tgbot.senders.utils import get_random_emoji
from src.tgbot.service import (
    assign_experiment,
    create_user_popup_log,
    delete_user_popup_log,
    get_experiment_variant,
    user_popup_already_sent,
)
from src.tgbot.utils import get_related_channel_link

logger = logging.getLogger(__name__)

FIRST_MEME_NUDGE_EXPERIMENT_ID = "first_meme_nudge"
FIRST_MEME_NUDGE_POPUP_ID = "nudge.first_meme"


def _get_popup(popup_id: str, user_info: dict) -> Popup:
    # TODO: alertn when we don't have localization for the popup
    return Popup(
        id=popup_id,
        text=localizer.t(popup_id, user_info["interface_lang"]),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_random_emoji() * 3,
                        callback_data=POPUP_BUTTON_CALLBACK_DATA_PATTERN.format(popup_id=popup_id),
                    )
                ]
            ]
        ),
    )


def _get_channel_popup(popup_id: str, user_info: dict) -> Popup:
    channel_link = get_related_channel_link(user_info["interface_lang"])
    return Popup(
        id=popup_id,
        text=localizer.t(popup_id, user_info["interface_lang"]),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📢 Subscribe",
                        url=channel_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ I subscribed",
                        callback_data=POPUP_BUTTON_CALLBACK_DATA_PATTERN.format(popup_id=popup_id),
                    )
                ],
            ]
        ),
    )


async def send_popup(user_id: int, popup: Popup) -> None:
    await bot.send_message(
        chat_id=user_id,
        text=popup.text,
        parse_mode=ParseMode.HTML,
        reply_markup=popup.reply_markup,
    )
    await create_user_popup_log(user_id, popup.id)

    if popup.id == "popup.telegram_channel":
        safe_emit(
            "ff.popup.telegram_channel.shown",
            f"user.{user_id}",
            {"user_id": user_id},
        )


async def get_popup_to_send(user_id: int, user_info: dict) -> Popup | None:
    # Wrapped auto-trigger at 30th meme (April 1-7 for all, before that moderators only)
    if user_info["nmemes_sent"] == 30:
        popup_id = "wrapped.auto_trigger"
        if not await user_popup_already_sent(user_id, popup_id):
            from src.tgbot.handlers.stats.wrapped import (
                is_wrapped_auto_trigger_active,
            )

            if await is_wrapped_auto_trigger_active(user_id):
                return Popup(
                    id=popup_id,
                    text=(
                        "🎁 <b>Meme Wrapped 2026</b>\n\n"
                        "Ты посмотрел 30 мемов — этого достаточно, "  # noqa: E501
                        "чтобы я составил твой мем-профиль!\n\n"
                        "Жми кнопку ниже 👇"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🧬 Мой Wrapped",
                                    url="https://t.me/ffmemesbot?start=wrapped",  # noqa: E501
                                )
                            ]
                        ]
                    ),
                )

    # Upload promotion Day 1 A/B experiment
    # Must come BEFORE the achievement.nmemes_sent_10 check — both trigger at
    # nmemes_sent == 10, and the achievement check's early return would swallow
    # this branch entirely for treatment users.
    if user_info["nmemes_sent"] == 10:
        experiment_id = "upload_promo_day1"
        variant = await get_experiment_variant(user_id, experiment_id)
        if variant is None:
            # New user reaching trigger — assign to experiment
            variant = "treatment" if user_id % 2 == 0 else "control"
            await assign_experiment(user_id, experiment_id, variant)

        if variant == "treatment":
            popup_id = "experiment.upload_promo_day1"
            if not await user_popup_already_sent(user_id, popup_id):
                safe_emit(
                    "ff.experiment.upload_promo_day1.sent",
                    f"user.{user_id}",
                    {"user_id": user_id, "group": "treatment"},
                )
                return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] == 10:
        popup_id = "achievement.nmemes_sent_10"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] % 1000 == 20:
        popup_id = "popup.upload_meme"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] % 1000 == 33:
        popup_id = "popup.inline_search"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] % 1000 == 5:
        popup_id = "popup.telegram_channel"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_channel_popup(popup_id, user_info)

    if user_info["nmemes_sent"] % 1000 == 70:
        popup_id = "popup.github_repo"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] % 1000 == 90:
        popup_id = "popup.feedback"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    # TODO:
    # 1. invite to update languages
    # 2. send a circle video with greeting from a team member

    if user_info["nmemes_sent"] == 100:
        popup_id = "achievement.nmemes_sent_100"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] == 1000:
        popup_id = "achievement.nmemes_sent_1000"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    return None


async def maybe_send_first_meme_nudge(user_id: int, user_info: dict) -> None:
    # Cheap pre-check: avoids extra writes (assignment row + insert attempt) for
    # the common already-nudged path. The atomic lease below is what actually
    # guarantees single-fire under concurrent meme #1 deliveries.
    if await user_popup_already_sent(user_id, FIRST_MEME_NUDGE_POPUP_ID):
        return

    variant = await get_experiment_variant(user_id, FIRST_MEME_NUDGE_EXPERIMENT_ID)
    if variant is None:
        variant = "treatment" if user_id % 2 == 0 else "control"
        await assign_experiment(user_id, FIRST_MEME_NUDGE_EXPERIMENT_ID, variant)

    safe_emit(
        f"ff.experiment.{FIRST_MEME_NUDGE_EXPERIMENT_ID}.evaluated",
        f"user.{user_id}",
        {"user_id": user_id, "group": variant},
    )

    if variant != "treatment":
        return

    # Atomic lease: insert the popup-log row first. Only the caller whose insert
    # actually created the row (rowcount==1) is allowed to send. This collapses
    # the previous (check, send, log) sequence into a single race-safe op so two
    # concurrent first-meme flows can't both fire the nudge.
    if not await create_user_popup_log(user_id, FIRST_MEME_NUDGE_POPUP_ID):
        return

    text = localizer.t(FIRST_MEME_NUDGE_POPUP_ID, user_info["interface_lang"])
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Forbidden:
        # User blocked the bot between meme send and nudge. Keep the lease — the
        # user can't receive messages anyway, and nmemes_sent will advance past 0
        # so this code path won't re-enter for this user.
        return
    except TelegramError as exc:
        # Transient delivery failure (timeout, rate-limit, etc.). Release the
        # lease so a future meme #1 attempt can re-fire the nudge.
        logger.warning("Failed to send first-meme nudge to user %s: %s", user_id, exc)
        await delete_user_popup_log(user_id, FIRST_MEME_NUDGE_POPUP_ID)
        return

    safe_emit(
        f"ff.experiment.{FIRST_MEME_NUDGE_EXPERIMENT_ID}.sent",
        f"user.{user_id}",
        {"user_id": user_id, "group": variant},
    )
