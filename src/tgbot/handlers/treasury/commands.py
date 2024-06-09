from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.service import (
    get_leaderboard,
    get_user_balance,
    get_user_place_in_leaderboard,
    get_token_supply,
)
from src.tgbot.senders.utils import get_random_emoji

# get_user_place_in_leaderboard,
from src.tgbot.service import update_user
from src.tgbot.user_info import update_user_info_cache


# command: /b / /balance
async def handle_show_balance(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    balance = await get_user_balance(update.effective_user.id)
    return await update.message.reply_text(
        f"""
<b>Your balance</b>: {balance} 🍔

Your rank: /leaderboard
Get more 🍔: /kitchen
        """,
        parse_mode=ParseMode.HTML,
    )


# command: /kitchen
# shows all possible ways to earn / to mine 🍔
async def handle_show_kitchen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Sends you the meme by it's id"""
    await update.message.reply_text(
        f"""
<b>🍔 Kitchen</b>

How to get more 🍔.

Menu:
▪ forward a funny meme to the bot & pass the modedation: {PAYOUTS[TrxType.MEME_UPLOADER]} 🍔
▪ you share a meme from bot and your friend clicks a link under meme: {PAYOUTS[TrxType.USER_INVITER]} 🍔
▪▪ an invited friend has Telegram premium: {PAYOUTS[TrxType.USER_INVITER_PREMIUM]} 🍔
▪▪ only new ffmemes users counts

Soon:
▪ top 3 memes in weekly leaderboard: 50 🍔, 30 🍔, 20 🍔
▪ follow our channels: ? 🍔

/leaderboard /balance /lang /chat /nickname
        """,  # noqa
        parse_mode=ParseMode.HTML,
    )


# command: /leaderboard /l
async def handle_show_leaderbaord(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    emoji = get_random_emoji()
    leaderboard = await get_leaderboard()

    LEADERBOARD_TEXT = f"{emoji} Leaderboard {emoji}\n\n"
    for i, user in enumerate(leaderboard):
        icon = "🏆" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🏅"
        nick = user["nickname"] or get_random_emoji() * 3
        LEADERBOARD_TEXT += f"{icon} - {nick} - {user['balance']} 🍔\n"

    user_lb_data = await get_user_place_in_leaderboard(update.effective_user.id)
    if user_lb_data:
        place, nickname, balance = (
            user_lb_data["place"],
            user_lb_data["nickname"],
            user_lb_data["balance"],
        )
        if nickname:
            LEADERBOARD_TEXT += f"""

You:
#{place} - {nickname} - {balance} 🍔

/kitchen /nickname /lang /chat
        """
        else:
            LEADERBOARD_TEXT += (
                "To see your place in the leaderboard, set your /nickname ⬅️\n\n"
            )

    tokens = await get_token_supply()
    LEADERBOARD_TEXT += f"\n Total supply: {tokens} 🍔"

    return await update.message.reply_text(LEADERBOARD_TEXT, parse_mode=ParseMode.HTML)


async def handle_change_nickname(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
        return await update.message.reply_text(
            "Nickname should be less than 32 characters 🤷‍♂️"
        )

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
    )

    await update_user_info_cache(update.effective_user.id)
