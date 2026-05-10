"""Shared moderation transitions for `meme_source`.

Both the Telegram moderator UI (`src/tgbot/handlers/moderator/meme_source.py`)
and the admin CLI (`scripts/admin/advance_source.py`) call into
`advance_meme_source` so the snooze/unsnooze rules and audit trail can never
drift between the two paths.

Side-effects deliberately excluded from this module:
- TG admin-channel notifications (`src.tgbot.logs.log`) — caller-specific.
- UI rendering (keyboards, send_message) — caller-specific.

Side-effects this module owns:
- Snooze/unsnooze cascades on `meme.status` for the affected source.
- Audit log appended to `meme_source.data['moderation_log']`, plus a
  `last_moderated_by` field. `data` is JSONB so this is a structured trail
  rather than a free-form log line, which lets future tooling (analyst
  queries, re-deciding stuck sources) read who moved which source when.
- Triggering the platform parser when a source flips to `parsing_enabled`.
"""

from datetime import datetime
from typing import Any

from src.database import execute, fetch_one, meme, meme_source
from src.storage.constants import MemeSourceStatus, MemeSourceType, MemeStatus


class MemeSourceNotFoundError(LookupError):
    pass


async def get_source(meme_source_id: int) -> dict[str, Any] | None:
    return await fetch_one(meme_source.select().where(meme_source.c.id == meme_source_id))


async def _snooze_memes(meme_source_id: int) -> int:
    result = await execute(
        meme.update()
        .where(meme.c.meme_source_id == meme_source_id)
        .where(meme.c.status == MemeStatus.OK)
        .values(status=MemeStatus.SNOOZED)
    )
    return result.rowcount


async def _unsnooze_memes(meme_source_id: int) -> int:
    result = await execute(
        meme.update()
        .where(meme.c.meme_source_id == meme_source_id)
        .where(meme.c.status == MemeStatus.SNOOZED)
        .values(status=MemeStatus.OK)
    )
    return result.rowcount


def _audit_entry(moderator_id: str, changed: dict[str, Any]) -> dict[str, Any]:
    return {
        "moderator": moderator_id,
        "ts": datetime.utcnow().isoformat(),
        "changed": changed,
    }


async def advance_meme_source(
    meme_source_id: int,
    moderator_id: str,
    *,
    language_code: str | None = None,
    status: str | None = None,
    trigger_parse: bool = True,
) -> dict[str, Any]:
    """Apply one moderation step to `meme_source(id=meme_source_id)`.

    Args:
      meme_source_id: target meme_source row id.
      moderator_id: stable identifier of the moderator (Telegram user_id as
        string, or agent id like `agent:cto`). Persisted to the audit trail
        so we can tell apart human and agent moderation events.
      language_code: optional new `language_code`; pass None to leave it.
      status: optional new `meme_source.status`; pass None to leave it.
        Must be a `MemeSourceStatus` value if provided.
      trigger_parse: whether to kick off the platform parser when status
        flips to `parsing_enabled`. CLI/bot both default this to True.

    Returns dict with:
      - `source`: updated row (post-transition).
      - `before_status`, `before_language_code`: values prior to update.
      - `snoozed_count`, `unsnoozed_count`: rows touched on `meme`.
      - `parsed`: whether parsing was triggered for the source.

    Raises:
      MemeSourceNotFoundError: source id does not exist.
      ValueError: invalid status, or no fields supplied.
    """
    if status is None and language_code is None:
        raise ValueError("at least one of status or language_code must be provided")

    if status is not None:
        try:
            status_enum: MemeSourceStatus | None = MemeSourceStatus(status)
        except ValueError as e:
            valid = [s.value for s in MemeSourceStatus]
            raise ValueError(f"invalid status {status!r}; valid: {valid}") from e
    else:
        status_enum = None

    src = await get_source(meme_source_id)
    if src is None:
        raise MemeSourceNotFoundError(f"meme_source(id={meme_source_id}) not found")

    before_status = src["status"]
    before_language_code = src["language_code"]

    snoozed_count = 0
    unsnoozed_count = 0

    # Match the bot moderator path (`handle_meme_source_change_status`):
    # unsnooze the source's memes when leaving SNOOZED for PARSING_ENABLED;
    # snooze the source's OK memes whenever entering SNOOZED. Updating meme
    # rows before the source row keeps state consistent if either fails.
    if (
        status_enum is MemeSourceStatus.PARSING_ENABLED
        and before_status == MemeSourceStatus.SNOOZED.value
    ):
        unsnoozed_count = await _unsnooze_memes(meme_source_id)
    elif status_enum is MemeSourceStatus.SNOOZED:
        snoozed_count = await _snooze_memes(meme_source_id)

    changed: dict[str, Any] = {}
    values: dict[str, Any] = {"updated_at": datetime.utcnow()}
    if language_code is not None and language_code != before_language_code:
        values["language_code"] = language_code
        changed["language_code"] = {"from": before_language_code, "to": language_code}
    if status_enum is not None and status_enum.value != before_status:
        values["status"] = status_enum.value
        changed["status"] = {"from": before_status, "to": status_enum.value}

    if changed:
        existing_data = dict(src.get("data") or {})
        log_entries = list(existing_data.get("moderation_log") or [])
        log_entries.append(_audit_entry(moderator_id, changed))
        existing_data["moderation_log"] = log_entries
        existing_data["last_moderated_by"] = moderator_id
        values["data"] = existing_data

    updated = await fetch_one(
        meme_source.update()
        .where(meme_source.c.id == meme_source_id)
        .values(**values)
        .returning(meme_source)
    )

    parsed_triggered = False
    if (
        trigger_parse
        and status_enum is MemeSourceStatus.PARSING_ENABLED
        and updated["status"] == MemeSourceStatus.PARSING_ENABLED.value
    ):
        # Imported lazily so test code that exercises advance_meme_source
        # without prefect/parser deps does not pay the import cost.
        if updated["type"] == MemeSourceType.TELEGRAM.value:
            from src.flows.parsers.tg import parse_telegram_source

            await parse_telegram_source(meme_source_id, updated["url"])
            parsed_triggered = True
        elif updated["type"] == MemeSourceType.VK.value:
            from src.flows.parsers.vk import parse_vk_source

            await parse_vk_source(meme_source_id, updated["url"])
            parsed_triggered = True

    return {
        "source": updated,
        "before_status": before_status,
        "before_language_code": before_language_code,
        "snoozed_count": snoozed_count,
        "unsnoozed_count": unsnoozed_count,
        "parsed": parsed_triggered,
    }
