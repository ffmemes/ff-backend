"""Non-interactive CLI to advance a `meme_source` through moderation.

Use case: agent runtimes (CTO, QA) need to clear sources stuck in
`in_moderation` without driving the Telegram bot UI as a real user. The
bot moderator path requires a human Telegram identity; this CLI does not.

Run from inside the prod app container so it shares the same DB env vars
as the FastAPI service:

    docker compose exec app python -m scripts.admin.advance_source \\
        --id 21848 --language ru --status parsing_enabled \\
        --moderator-id agent:cto

Acceptance for FFM-1154: clears sources 21848 (nourlnews) and 21849
(kozakrichala) at language=ru, status=parsing_enabled, then post raw
post / total meme / ok meme counts back to FFM-1114.
"""

import argparse
import asyncio
import json
import sys
from typing import Any

from src.storage.constants import MemeSourceStatus
from src.storage.moderation import (
    MemeSourceNotFoundError,
    advance_meme_source,
    get_source,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.admin.advance_source",
        description=("Advance a meme_source through moderation states (language and/or status)."),
    )
    parser.add_argument(
        "--id",
        dest="meme_source_id",
        type=int,
        required=True,
        help="meme_source.id to advance.",
    )
    parser.add_argument(
        "--language",
        dest="language_code",
        type=str,
        default=None,
        help="ISO language code (e.g. ru, en). Skips if omitted.",
    )
    parser.add_argument(
        "--status",
        dest="status",
        type=str,
        default=None,
        choices=[s.value for s in MemeSourceStatus],
        help=("New status. Use parsing_enabled to clear in_moderation. Skips if omitted."),
    )
    parser.add_argument(
        "--moderator-id",
        dest="moderator_id",
        type=str,
        required=True,
        help=(
            "Stable identifier for who/what is moderating "
            "(e.g. 'agent:cto'). Persisted to the audit trail."
        ),
    )
    parser.add_argument(
        "--no-trigger-parse",
        dest="trigger_parse",
        action="store_false",
        default=True,
        help=("Skip kicking off the platform parser after flipping status to parsing_enabled."),
    )
    parser.add_argument(
        "--show",
        dest="show_only",
        action="store_true",
        help="Just print the current source row and exit (no writes).",
    )
    return parser


def _serialize(value: Any) -> Any:
    """Coerce DB rows / datetime to JSON-friendly primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return str(value)


async def _run(args: argparse.Namespace) -> int:
    if args.show_only:
        src = await get_source(args.meme_source_id)
        if src is None:
            print(json.dumps({"ok": False, "error": "not_found", "id": args.meme_source_id}))
            return 1
        print(json.dumps({"ok": True, "source": _serialize(dict(src))}, indent=2))
        return 0

    if args.language_code is None and args.status is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "no_change_requested",
                    "hint": "pass --language and/or --status",
                }
            )
        )
        return 2

    try:
        result = await advance_meme_source(
            args.meme_source_id,
            moderator_id=args.moderator_id,
            language_code=args.language_code,
            status=args.status,
            trigger_parse=args.trigger_parse,
        )
    except MemeSourceNotFoundError as e:
        print(json.dumps({"ok": False, "error": "not_found", "message": str(e)}))
        return 1
    except ValueError as e:
        print(json.dumps({"ok": False, "error": "bad_request", "message": str(e)}))
        return 2

    payload = {
        "ok": True,
        "id": args.meme_source_id,
        "before_status": result["before_status"],
        "before_language_code": result["before_language_code"],
        "after_status": result["source"]["status"],
        "after_language_code": result["source"]["language_code"],
        "snoozed_count": result["snoozed_count"],
        "unsnoozed_count": result["unsnoozed_count"],
        "parsed": result["parsed"],
        "moderator_id": args.moderator_id,
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
