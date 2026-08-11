"""Compatibility re-exports for Telegram-related repository helpers.

Implementation lives in `src.tgbot.repo.*`. New code should import from the
focused modules; existing `from src.tgbot.service import ...` call sites and
test patches stay valid through this barrel.
"""

from src.tgbot.repo.deep_links import log_user_deep_link
from src.tgbot.repo.experiments import (
    assign_experiment,
    get_experiment_assignment,
    get_experiment_variant,
)
from src.tgbot.repo.inline_search import (
    create_inline_chosen_result_log,
    create_inline_search_log,
    search_memes_for_inline_query,
)
from src.tgbot.repo.languages import (
    add_user_language,
    add_user_languages,
    clear_user_languages,
    del_user_language,
    get_user_languages,
    set_user_languages_exclusive,
)
from src.tgbot.repo.meme_sources import (
    dismiss_source_candidate,
    get_meme_source_by_id,
    get_meme_source_stats_by_id,
    get_or_create_meme_source,
    get_source_candidate_by_id,
    list_pending_source_candidates,
    promote_source_candidate,
    update_meme_source,
)
from src.tgbot.repo.memes import (
    get_last_reacted_meme_for_user,
    get_last_sent_meme_for_user,
    get_meme_by_id,
    get_meme_stats,
    get_meme_stats_for_meme_ids,
    get_shareable_meme_by_id,
)
from src.tgbot.repo.popups import (
    create_user_popup_log,
    delete_user_popup_log,
    update_user_popup_log,
    user_popup_already_sent,
)
from src.tgbot.repo.users import (
    _blocked_bot_at_timestamp,
    add_user_tg_chat_membership,
    create_or_update_user,
    get_tg_user_by_id,
    get_user_by_id,
    get_user_info,
    mark_user_blocked,
    mark_user_unblocked,
    save_tg_user,
    update_user,
)

__all__ = [
    "_blocked_bot_at_timestamp",
    "add_user_language",
    "add_user_languages",
    "add_user_tg_chat_membership",
    "assign_experiment",
    "clear_user_languages",
    "create_inline_chosen_result_log",
    "create_inline_search_log",
    "create_or_update_user",
    "create_user_popup_log",
    "del_user_language",
    "delete_user_popup_log",
    "dismiss_source_candidate",
    "get_experiment_assignment",
    "get_experiment_variant",
    "get_last_reacted_meme_for_user",
    "get_last_sent_meme_for_user",
    "get_meme_by_id",
    "get_meme_source_by_id",
    "get_meme_source_stats_by_id",
    "get_meme_stats",
    "get_meme_stats_for_meme_ids",
    "get_or_create_meme_source",
    "get_shareable_meme_by_id",
    "get_source_candidate_by_id",
    "get_tg_user_by_id",
    "get_user_by_id",
    "get_user_info",
    "get_user_languages",
    "list_pending_source_candidates",
    "log_user_deep_link",
    "mark_user_blocked",
    "mark_user_unblocked",
    "promote_source_candidate",
    "save_tg_user",
    "search_memes_for_inline_query",
    "set_user_languages_exclusive",
    "update_meme_source",
    "update_user",
    "update_user_popup_log",
    "user_popup_already_sent",
]
