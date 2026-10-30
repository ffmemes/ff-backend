import logging
from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from src import localizer
from src.flows.events import safe_emit
from src.tgbot.bot import bot
from src.tgbot.constants import POPUP_BUTTON_CALLBACK_DATA_PATTERN
from src.tgbot.schemas import Popup
from src.tgbot.senders.utils import get_random_emoji
from src.tgbot.service import (
    assign_experiment,
    create_user_popup_log,
    get_experiment_variant,
    user_popup_already_sent,
)
from src.tgbot.utils import get_related_channel_link

logger = logging.getLogger(__name__)

UPLOAD_PROMO_DAY1_EXPERIMENT_ID = "upload_promo_day1"
UPLOAD_PROMO_DAY1_POPUP_ID = "experiment.upload_promo_day1"

PopupFactory = Callable[[str, dict], Popup]
PopupPredicate = Callable[[int], bool]
StaticPopupRule = tuple[PopupPredicate, str, PopupFactory]


def _sent_count_is(expected: int) -> PopupPredicate:
    return lambda nmemes_sent: nmemes_sent == expected


def _sent_count_mod_1000_is(expected: int) -> PopupPredicate:
    return lambda nmemes_sent: nmemes_sent % 1000 == expected


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


STATIC_POPUP_RULES: tuple[StaticPopupRule, ...] = (
    (_sent_count_is(10), "achievement.nmemes_sent_10", _get_popup),
    (_sent_count_mod_1000_is(20), "popup.upload_meme", _get_popup),
    (_sent_count_mod_1000_is(33), "popup.inline_search", _get_popup),
    (_sent_count_mod_1000_is(5), "popup.telegram_channel", _get_channel_popup),
    (_sent_count_mod_1000_is(70), "popup.github_repo", _get_popup),
    (_sent_count_mod_1000_is(90), "popup.feedback", _get_popup),
    (_sent_count_is(100), "achievement.nmemes_sent_100", _get_popup),
    (_sent_count_is(1000), "achievement.nmemes_sent_1000", _get_popup),
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


async def _unsent_popup(
    user_id: int,
    popup_id: str,
    user_info: dict,
    popup_factory: PopupFactory | None = None,
) -> Popup | None:
    if await user_popup_already_sent(user_id, popup_id):
        return None
    popup_factory = popup_factory or _get_popup
    return popup_factory(popup_id, user_info)


async def _wrapped_auto_trigger_popup(user_id: int, user_info: dict) -> Popup | None:
    # Wrapped auto-trigger at 30th meme (April 1-7 for all, before that moderators only)
    if user_info["nmemes_sent"] != 30:
        return None

    popup_id = "wrapped.auto_trigger"
    if await user_popup_already_sent(user_id, popup_id):
        return None

    from src.tgbot.handlers.stats.wrapped import (
        is_wrapped_auto_trigger_active,
    )

    if not await is_wrapped_auto_trigger_active(user_id):
        return None

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


async def _upload_promo_day1_popup(user_id: int, user_info: dict) -> Popup | None:
    # Upload promotion Day 1 A/B experiment
    # Must come BEFORE the achievement.nmemes_sent_10 check — both trigger at
    # nmemes_sent == 10, and the achievement check's early return would swallow
    # this branch entirely for treatment users.
    if user_info["nmemes_sent"] != 10:
        return None

    variant = await get_experiment_variant(user_id, UPLOAD_PROMO_DAY1_EXPERIMENT_ID)
    if variant is None:
        # New user reaching trigger — assign to experiment
        variant = "treatment" if user_id % 2 == 0 else "control"
        await assign_experiment(user_id, UPLOAD_PROMO_DAY1_EXPERIMENT_ID, variant)

    if variant != "treatment":
        return None

    popup = await _unsent_popup(user_id, UPLOAD_PROMO_DAY1_POPUP_ID, user_info)
    if popup is None:
        return None

    safe_emit(
        "ff.experiment.upload_promo_day1.sent",
        f"user.{user_id}",
        {"user_id": user_id, "group": "treatment"},
    )
    return popup


async def _static_popup(user_id: int, user_info: dict) -> Popup | None:
    nmemes_sent = user_info["nmemes_sent"]
    for matches, popup_id, popup_factory in STATIC_POPUP_RULES:
        if matches(nmemes_sent):
            return await _unsent_popup(user_id, popup_id, user_info, popup_factory)
    return None


async def get_popup_to_send(user_id: int, user_info: dict) -> Popup | None:
    popup = await _wrapped_auto_trigger_popup(user_id, user_info)
    if popup is not None:
        return popup

    popup = await _upload_promo_day1_popup(user_id, user_info)
    if popup is not None:
        return popup

    popup = await _static_popup(user_id, user_info)
    if popup is not None:
        return popup

    # TODO:
    # 1. invite to update languages
    # 2. send a circle video with greeting from a team member
    return None
