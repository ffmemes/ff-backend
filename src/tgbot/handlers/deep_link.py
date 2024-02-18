import re

from src.tgbot.constants import UserType
from src.tgbot.logs import log
from src.tgbot.senders.invite import send_successfull_invitation_alert
from src.tgbot.service import get_user_by_id, update_user

LINK_UNDER_MEME_PATTERN = r"s_\d+_\d+"


async def handle_deep_link_used(
    invited_user: dict, invited_user_name: str, deep_link: str
):
    """
    E.g. if user was invited, send a msg to invited about used invitation
    """

    # TODO: log all deep link used
    if re.match(LINK_UNDER_MEME_PATTERN, deep_link):
        _, user_id, _ = deep_link.split("_")
        invitor_user_id = int(user_id)

        if invitor_user_id == invited_user["id"]:
            return

        invitor_user = await get_user_by_id(invitor_user_id)
        if not invitor_user:
            return  # user with this id doesn't exist

        if invitor_user["type"] != UserType.WAITLIST and invited_user["type"] in [
            UserType.WAITLIST,
            UserType.BLOCKED_BOT,
        ]:
            await update_user(invited_user["id"], type=UserType.USER)

            await send_successfull_invitation_alert(invitor_user_id, invited_user_name)
            await log(f"🤝 #{invitor_user_id} invited {invited_user_name}")
