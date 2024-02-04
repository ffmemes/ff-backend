from src.tgbot.constants import UserType
from src.tgbot.senders.invite import send_successfull_invitation_alert
from src.tgbot.service import (
    update_user,
)


async def handle_deep_link_used(
    invited_user: dict, invited_user_name: str, deep_link: int
):
    """
    E.g. if user was invited, send a msg to invited about used invitation
    """

    if deep_link and deep_link.startswith("s_"):  # invited
        user_id, _ = deep_link[2:].split("_")
        invitor_user_id = int(user_id)

        if invited_user["type"] == UserType.WAITLIST:
            await update_user(invited_user["id"], type=UserType.USER)

            await send_successfull_invitation_alert(invitor_user_id, invited_user_name)
