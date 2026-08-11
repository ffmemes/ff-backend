#!/usr/bin/env python3
"""Download @fastfoodmemes history via Telethon; parse bot deeplinks → meme_id.

Join key in caption / entities:
  https://t.me/ffmemesbot?start=sc_{meme_id}_tgchannelru
  (also bare start=sc_{meme_id}_...)

Posts without sc_ link cannot be joined to bot memes → kept with meme_id=null
for inventory only.

Env (same as stats_collector):
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING

Usage:
  set -a; source .env; set +a   # or export from zshrc
  python export_channel_telethon.py --limit 0          # all reachable
  python export_channel_telethon.py --limit 500
  python export_channel_telethon.py --min-id 1 --max-id 999999

Writes:
  data/raw/channel_telethon_posts.parquet
  data/raw/channel_telethon_meta.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import polars as pl
except ImportError:
    print("polars required", file=sys.stderr)
    sys.exit(1)

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.custom.message import Message
except ImportError:
    print("telethon required", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
CHANNEL = "fastfoodmemes"

# sc_<meme_id>_<channel>  or sc_<meme_id>
SC_RE = re.compile(
    r"(?:t\.me/ffmemesbot\?start=|start=)sc_(\d+)(?:_[a-zA-Z0-9]+)?",
    re.I,
)


def _parse_meme_id(text: str | None, message: Message | None = None) -> int | None:
    blobs: list[str] = []
    if text:
        blobs.append(text)
    # entities / raw message
    if message is not None:
        try:
            raw = message.message or ""
            if raw:
                blobs.append(raw)
        except Exception:
            pass
        # walk entities for MessageEntityTextUrl / url
        try:
            if message.entities:
                for ent in message.entities:
                    url = getattr(ent, "url", None)
                    if url:
                        blobs.append(url)
        except Exception:
            pass
    for b in blobs:
        m = SC_RE.search(b)
        if m:
            return int(m.group(1))
    return None


def _reaction_count(message: Message) -> int:
    try:
        reactions = message.reactions
        if not reactions or not getattr(reactions, "results", None):
            return 0
        return int(sum(getattr(r, "count", 0) or 0 for r in reactions.results))
    except Exception:
        return 0


async def crawl(*, limit: int, min_id: int | None, max_id: int | None) -> dict:
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    session = os.environ.get("TELEGRAM_SESSION_STRING")
    if not all([api_id, api_hash, session]):
        raise SystemExit(
            "Need TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING"
        )

    client = TelegramClient(StringSession(session), int(api_id), api_hash)
    rows: list[dict] = []
    meta: dict = {
        "channel": CHANNEL,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
    }

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SystemExit("Telethon session not authorized — regenerate session string")

        entity = await client.get_entity(CHANNEL)
        # limit=0 → Telethon treats as all; we use None for "no limit"
        kwargs: dict = {}
        if limit and limit > 0:
            kwargs["limit"] = limit
        if min_id is not None:
            kwargs["min_id"] = min_id
        if max_id is not None:
            kwargs["max_id"] = max_id

        n = 0
        async for message in client.iter_messages(entity, **kwargs):
            if message is None or not message.id:
                continue
            # skip service messages without content stats
            text = (message.text or message.message or "") or ""
            meme_id = _parse_meme_id(text, message)
            views = int(message.views or 0) if message.views is not None else None
            forwards = int(message.forwards or 0) if message.forwards is not None else None
            rows.append(
                {
                    "telegram_message_id": int(message.id),
                    "posted_at": message.date.replace(tzinfo=None) if message.date else None,
                    "views": views,
                    "forwards": forwards,
                    "reactions": _reaction_count(message),
                    "meme_id": meme_id,
                    "has_media": bool(message.media),
                    "is_reply": bool(message.reply_to),
                    "text_preview": (text[:300] if text else None),
                    "joined_via": "deeplink_sc" if meme_id else None,
                }
            )
            n += 1
            if n % 200 == 0:
                print(f"  … {n} messages", flush=True)

        meta["n_messages"] = len(rows)
        meta["n_with_meme_id"] = sum(1 for r in rows if r["meme_id"] is not None)
        meta["n_with_views"] = sum(1 for r in rows if r["views"])
        print(
            f"fetched {meta['n_messages']} msgs, "
            f"joinable sc_ meme_id={meta['n_with_meme_id']}"
        )
    finally:
        await client.disconnect()

    RAW.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(rows) if rows else pl.DataFrame()
    out = RAW / "channel_telethon_posts.parquet"
    df.write_parquet(out)
    (RAW / "channel_telethon_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"wrote {out}")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max messages (0 = no limit / full history Telethon allows)",
    )
    ap.add_argument("--min-id", type=int, default=None)
    ap.add_argument("--max-id", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(crawl(limit=args.limit, min_id=args.min_id, max_id=args.max_id))


if __name__ == "__main__":
    main()
