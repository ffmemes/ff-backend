import logging
from collections.abc import Mapping

from src.tgbot.constants import UserType
from src.tgbot.exceptions import UserNotFound
from src.tgbot.user_info import get_user_info, update_user_info_cache


def _is_moderator_type(raw_type: object) -> bool:
    try:
        return UserType(str(raw_type)).is_moderator
    except ValueError:
        logging.warning("Unknown user type '%s' encountered during moderator check", raw_type)
        return False


async def get_moderator_user_info(user_id: int) -> Mapping[str, object] | None:
    """Return user info only when the user currently has moderator privileges.

    Moderator gates are sensitive to role changes. `get_user_info` is cached for
    an hour, so if the cache says "not a moderator" we refresh once from DB
    before denying access.
    """
    try:
        user_info = await get_user_info(user_id)
    except UserNotFound:
        return None

    if _is_moderator_type(user_info["type"]):
        return user_info

    try:
        fresh_user_info = await update_user_info_cache(user_id)
    except UserNotFound:
        return None

    if _is_moderator_type(fresh_user_info["type"]):
        return fresh_user_info

    return None
