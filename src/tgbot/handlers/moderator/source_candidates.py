from telegram import Update
from telegram.ext import ContextTypes

from src.tgbot.constants import UserType
from src.tgbot.handlers.moderator.meme_source import meme_source_admin_pipeline
from src.tgbot.logs import log
from src.tgbot.senders.keyboards import source_candidate_actions_keyboard
from src.tgbot.service import (
    dismiss_source_candidate,
    get_source_candidate_by_id,
    list_pending_source_candidates,
    promote_source_candidate,
)
from src.tgbot.user_info import get_user_info

_LIST_LIMIT = 20


def _format_candidate_line(candidate: dict) -> str:
    return f"#{candidate['id']} • {candidate['url']} • forwarded ×{candidate['times_forwarded']}"


async def handle_discovered_sources_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_info = await get_user_info(update.effective_user.id)
    if not UserType(user_info["type"]).is_moderator:
        return

    candidates = await list_pending_source_candidates(limit=_LIST_LIMIT)
    if not candidates:
        await update.message.reply_text("No discovered TG source candidates pending.")
        return

    await update.message.reply_text(
        f"Top {len(candidates)} discovered TG source candidates "
        "(promote to enter moderation pipeline)."
    )
    for candidate in candidates:
        await update.message.reply_text(
            _format_candidate_line(candidate),
            reply_markup=source_candidate_actions_keyboard(candidate["id"]),
            disable_web_page_preview=True,
        )


async def handle_source_candidate_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user_id = update.effective_user.id
    user_info = await get_user_info(user_id)
    if not UserType(user_info["type"]).is_moderator:
        await update.callback_query.answer("🤷‍♀️ Only moderators can act on source candidates 🤷‍♂️")
        return

    args = update.callback_query.data.split(":")
    candidate_id, action = int(args[1]), args[2]

    candidate = await get_source_candidate_by_id(candidate_id)
    if candidate is None:
        await update.callback_query.answer("Candidate not found")
        return
    if candidate["status"] != "discovered":
        await update.callback_query.answer(f"Already {candidate['status']}; nothing to do.")
        return

    if action == "dismiss":
        await dismiss_source_candidate(candidate_id, reason=f"by:{user_id}")
        await log(
            f"🗑 SourceCandidate #{candidate_id} {candidate['url']}: dismissed (by {user_id})",
            context.bot,
        )
        await update.callback_query.answer("Dismissed.")
        await update.callback_query.edit_message_text(
            f"~~{_format_candidate_line(candidate)}~~ — dismissed",
            parse_mode=None,
        )
        return

    if action == "promote":
        promoted_meme_source = await promote_source_candidate(
            candidate_id=candidate_id,
            added_by_user_id=user_id,
        )
        if promoted_meme_source is None:
            await update.callback_query.answer("Promotion failed.")
            return
        await log(
            f"✅ SourceCandidate #{candidate_id} {candidate['url']}: "
            f"promoted to MemeSource {promoted_meme_source['id']} (by {user_id})",
            context.bot,
        )
        await update.callback_query.answer("Promoted to in_moderation.")
        await update.callback_query.edit_message_text(
            f"✅ {candidate['url']} → MemeSource #{promoted_meme_source['id']}"
        )
        # Funnel into the existing admin pipeline so the moderator can pick a
        # language and flip status — same UX as adding a source by URL.
        await meme_source_admin_pipeline(promoted_meme_source, update)
