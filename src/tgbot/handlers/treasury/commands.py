from html import escape

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src.tgbot.handlers.payments.purchase import PURCHASE_TOKEN_CALLBACK_DATA_PATTERN
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.service import (
    LEADERBOARD_WINDOW_DAYS,
    get_leaderboard,
    get_token_supply,
    get_user_balance,
    get_user_place_in_leaderboard,
)
from src.tgbot.senders.utils import get_random_emoji

# get_user_place_in_leaderboard,
from src.tgbot.service import get_user_languages, update_user
from src.tgbot.user_info import update_user_info_cache


def _format_burgers(amount: int | None) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


def _public_name(nickname: str | None, fallback: str) -> str:
    nickname = (nickname or "").strip()
    return escape(nickname) if nickname else fallback


async def _user_has_russian_enabled(user_id: int) -> bool:
    languages = await get_user_languages(user_id)
    return any(language and language.startswith("ru") for language in languages)


# command: /b / /balance
async def handle_show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    balance = await get_user_balance(update.effective_user.id)

    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "buy 100 🍔",
                    callback_data=PURCHASE_TOKEN_CALLBACK_DATA_PATTERN.format(tokens_to_buy=100),
                ),
            ],
            [
                InlineKeyboardButton(
                    "buy 1000 🍔",
                    callback_data=PURCHASE_TOKEN_CALLBACK_DATA_PATTERN.format(tokens_to_buy=1000),
                ),
            ],
            [
                InlineKeyboardButton(
                    "buy 10000 🍔",
                    callback_data=PURCHASE_TOKEN_CALLBACK_DATA_PATTERN.format(tokens_to_buy=10000),
                ),
            ],
        ]
    )

    return await update.message.reply_text(
        f"""
<b>Your balance</b>: {balance} 🍔

Your rank: /leaderboard
Get more 🍔: /kitchen
        """,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


# Video explainer attached to /kitchen. Obtained by forwarding
# https://t.me/c/1305866294/71096 from mod chat to the storage chat via the
# prod bot and reading msg.video.file_id. File_ids are bot-token-specific,
# so this only works with the prod bot.
KITCHEN_EXPLAINER_VIDEO_FILE_ID = (
    "BAACAgIAAx0CTdXwNgABARW4aeoMX17ZaFBOoDt9-IfuFv8nPTQAAgKcAALQHFBLjxk3pwABFxAXOwQ"
)


# command: /kitchen
# shows all possible ways to earn / to mine 🍔
async def handle_show_kitchen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current burger earning and spending rules."""
    is_ru = await _user_has_russian_enabled(update.effective_user.id)
    if is_ru:
        text = f"""
<b>🍔 Кухня</b>

Как получить бургеры:

▪ загрузить мем в бота и пройти модерацию: {PAYOUTS[TrxType.MEME_UPLOADER]} 🍔
▪ если принятый мем попадет в наш канал: {PAYOUTS[TrxType.MEME_PUBLISHED]} 🍔
▪ кто-то нажал ссылку под мемом, которым ты поделился: {PAYOUTS[TrxType.MEME_SHARED]} 🍔 раз в день
▪ новый пользователь пришел по твоей ссылке под мемом: {PAYOUTS[TrxType.USER_INVITER]} 🍔
▪ если у нового пользователя Telegram Premium: {PAYOUTS[TrxType.USER_INVITER_PREMIUM]} 🍔

▪ топ-5 загруженных мемов недели:
    🥇: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_1]} 🍔
    🥈: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_2]} 🍔
    🥉: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_3]} 🍔
    4: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_4]} 🍔
    5: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_5]} 🍔

▪ активность в чатах во время раздач: {PAYOUTS[TrxType.ACTIVE_IN_CHAT]} 🍔

Потратить:
▪ ответ бота в чате: {PAYOUTS[TrxType.BOT_REPLY_PAYMENT] * -1} 🍔
▪ перевести бургеры другому: ответь на его сообщение +число, например +10

/leaderboard /balance /lang /chat /nickname
        """
    else:
        text = f"""
<b>🍔 Kitchen</b>

How to get more burgers:

▪ upload a meme to the bot and pass moderation: {PAYOUTS[TrxType.MEME_UPLOADER]} 🍔
▪ if an approved meme reaches our channel: {PAYOUTS[TrxType.MEME_PUBLISHED]} 🍔
▪ someone clicks the link under a meme you shared: {PAYOUTS[TrxType.MEME_SHARED]} 🍔 once per day
▪ a new user joins through your meme link: {PAYOUTS[TrxType.USER_INVITER]} 🍔
▪ if that new user has Telegram Premium: {PAYOUTS[TrxType.USER_INVITER_PREMIUM]} 🍔

▪ top 5 uploaded memes of the week:
    🥇: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_1]} 🍔
    🥈: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_2]} 🍔
    🥉: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_3]} 🍔
    4: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_4]} 🍔
    5: {PAYOUTS[TrxType.UPLOADER_TOP_WEEKLY_5]} 🍔

▪ chat activity during reward drops: {PAYOUTS[TrxType.ACTIVE_IN_CHAT]} 🍔

Spend:
▪ bot reply in chat: {PAYOUTS[TrxType.BOT_REPLY_PAYMENT] * -1} 🍔
▪ send burgers to someone: reply to their message with +number, for example +10

/leaderboard /balance /lang /chat /nickname
        """  # noqa

    if KITCHEN_EXPLAINER_VIDEO_FILE_ID:
        await update.message.reply_video(
            video=KITCHEN_EXPLAINER_VIDEO_FILE_ID,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# command: /leaderboard /l
async def handle_show_leaderbaord(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    emoji = get_random_emoji()
    is_ru = await _user_has_russian_enabled(update.effective_user.id)
    leaderboard = await get_leaderboard()

    if is_ru:
        LEADERBOARD_TEXT = (
            f"{emoji} Лидерборд за последние {LEADERBOARD_WINDOW_DAYS} дней {emoji}\n\n"
        )
    else:
        LEADERBOARD_TEXT = f"{emoji} Leaderboard (last {LEADERBOARD_WINDOW_DAYS} days) {emoji}\n\n"

    for i, user in enumerate(leaderboard):
        icon = "🏆" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🏅"
        nick = _public_name(user["nickname"], get_random_emoji() * 3)
        weekly_earned = user.get("weekly_earned", 0)
        LEADERBOARD_TEXT += f"{icon} - {nick} - {_format_burgers(weekly_earned)} 🍔\n"

    tokens = await get_token_supply()
    if is_ru:
        LEADERBOARD_TEXT += f"\nВсего в обороте: {_format_burgers(tokens)} 🍔"
    else:
        LEADERBOARD_TEXT += f"\nTotal supply: {_format_burgers(tokens)} 🍔"

    user_lb_data = await get_user_place_in_leaderboard(update.effective_user.id)
    if user_lb_data:
        place, nickname, weekly_earned = (
            user_lb_data["place"],
            user_lb_data["nickname"],
            user_lb_data.get("weekly_earned", 0),
        )
        if nickname:
            if is_ru:
                LEADERBOARD_TEXT += f"""

Ты:
#{place} - {_public_name(nickname, "")} - {_format_burgers(weekly_earned)} 🍔

/kitchen /uploads /chat
        """
            else:
                LEADERBOARD_TEXT += f"""

You:
#{place} - {_public_name(nickname, "")} - {_format_burgers(weekly_earned)} 🍔

/kitchen /uploads /chat
        """
        elif is_ru:
            LEADERBOARD_TEXT += "\nЧтобы увидеть свое место в лидерборде, задай /nickname ⬅️\n\n"
        else:
            LEADERBOARD_TEXT += "\nTo see your place in the leaderboard, set your /nickname ⬅️\n\n"  # noqa: E501

    return await update.message.reply_text(
        LEADERBOARD_TEXT,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def handle_change_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) == 0:
        return await update.message.reply_text(
            """
Set your nickname that we will show in /leaderboard and other public places.
IDEA: You can use your telegram channel username to get some views 😉😘😜

To update your public nickname, use the following command:

/nickname <new_nickname>
        """
        )

    nickname = context.args[0].strip()
    if len(nickname) > 32:
        return await update.message.reply_text("Nickname should be less than 32 characters 🤷‍♂️")  # noqa: E501

    stop_characters = ["<", ">"]
    for stop_c in stop_characters:
        if stop_c in nickname:
            return await update.message.reply_text(
                "Nickname should not contain: " + ", ".join(stop_characters) + " 🤷‍♂️"
            )

    await update_user(update.effective_user.id, nickname=nickname)
    await update.message.reply_text(
        f"""
Your public nickname is now: <b>{nickname}</b>.

/leaderboard /balance /lang /chat
        """,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    await update_user_info_cache(update.effective_user.id)
