from src import localizer
from src.tgbot.bot import bot
from src.tgbot.user_info import get_user_info


async def send_successfull_invitation_alert(
    invitor_user_id: int, invited_user_name: str
) -> None:
    user_info = await get_user_info(invitor_user_id)

    await bot.send_message(
        chat_id=invitor_user_id,
        text=localizer.t(
            "onboarding.invitation_successfull_alert",
            user_info["interface_lang"],
        ).format(invited_user_name=invited_user_name),
    )
