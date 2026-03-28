#!/usr/bin/env python3
"""
Post-deploy E2E smoke tests for @ffmemesbot.
Runs as standalone script (no pytest, no DB).
Exit 0 = all checks pass, Exit 1 = critical failure.

Required env vars:
    TELEGRAM_API_ID
    TELEGRAM_API_HASH
    TELEGRAM_SESSION_STRING

Optional:
    TELEGRAM_TEST_BOT_USERNAME (default: ffmemesbot)

Usage:
    pip install -r requirements-e2e.txt
    python scripts/e2e_smoke.py
"""
import asyncio
import os
import sys
import time

from telethon import TelegramClient
from telethon.sessions import StringSession


# --- Config ---
API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
BOT_USERNAME = os.environ.get("TELEGRAM_TEST_BOT_USERNAME", "ffmemesbot")
RESPONSE_TIMEOUT = 10  # seconds


# --- Helpers ---
async def get_latest_msg_id(client, entity):
    messages = await client.get_messages(entity, limit=1)
    return messages[0].id if messages else 0


async def wait_for_response(client, entity, since_id, timeout=RESPONSE_TIMEOUT):
    """Poll for new message from bot (not our own). Returns message or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await client.get_messages(entity, limit=5)
        for msg in messages:
            if msg.id > since_id and not msg.out:
                return msg
        await asyncio.sleep(0.3)
    return None


def has_reaction_buttons(msg):
    """Check if message has inline keyboard with r: callback buttons."""
    if not msg.reply_markup:
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            data = btn.data.decode() if btn.data else ""
            if data.startswith("r:"):
                return True
    return False


def find_like_button(msg):
    """Find the like button (r:{meme_id}:1) in inline keyboard."""
    if not msg.reply_markup:
        return None
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            data = btn.data.decode() if btn.data else ""
            if data.startswith("r:") and data.endswith(":1"):
                return btn
    return None


# --- Tests ---
async def test_start(client, bot):
    """Send /start, verify bot responds with a meme.
    Returns (status, detail, meme_msg) — meme_msg is passed to next test.
    """
    before_id = await get_latest_msg_id(client, bot)
    await client.send_message(bot, "/start")
    msg = await wait_for_response(client, bot, before_id)

    if msg is None:
        return "FAIL", "Bot did not respond to /start within timeout", None

    has_media = msg.media is not None
    has_buttons = has_reaction_buttons(msg)

    if has_media and has_buttons:
        return "PASS", "Meme received with reaction buttons", msg
    elif has_media:
        return "WARN", "Meme received but no reaction buttons", msg
    elif msg.text:
        return "WARN", f"Bot responded with text (popup?): {msg.text[:100]}", msg
    else:
        return "WARN", "Bot responded but with unexpected content", msg


async def test_like(client, bot, meme_msg):
    """Click like on the current meme, verify bot sends next meme.
    This is the core interaction: user sees meme → presses button → gets next meme.
    """
    if meme_msg is None:
        return "FAIL", "No meme to react to (start test failed)"

    like_btn = find_like_button(meme_msg)
    if like_btn is None:
        return "WARN", "No like button found on current meme, cannot test reaction flow"

    after_id = meme_msg.id
    await meme_msg.click(data=like_btn.data)
    next_msg = await wait_for_response(client, bot, after_id)

    if next_msg is None:
        return "FAIL", "Bot did not respond after like button press"

    has_media = next_msg.media is not None
    has_buttons = has_reaction_buttons(next_msg)

    if has_media and has_buttons:
        return "PASS", "Next meme received with buttons after like"
    elif has_media:
        return "WARN", "Next meme received but no buttons"
    elif next_msg.text:
        return "WARN", f"Bot responded with text after like: {next_msg.text[:100]}"
    else:
        return "WARN", "Bot responded after like but with unexpected content"


# --- Runner ---
async def main():
    if not all([API_ID, API_HASH, SESSION_STRING]):
        print("SKIP: Telegram E2E credentials not configured")
        print("  Set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING")
        sys.exit(0)  # skip is not a failure

    client = TelegramClient(
        StringSession(SESSION_STRING),
        int(API_ID),
        API_HASH,
    )

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("FAIL: Telegram session expired. Regenerate with:")
            print("  python scripts/generate_session_string.py")
            sys.exit(1)

        bot = await client.get_entity(BOT_USERNAME)
        results = []

        # Test 1: /start → get a meme
        status, detail, meme_msg = await test_start(client, bot)
        results.append(("start", status, detail))
        print(f"  [{status}] start: {detail}")

        # Test 2: click like on that meme → get next meme (no extra /start)
        status, detail = await test_like(client, bot, meme_msg)
        results.append(("like", status, detail))
        print(f"  [{status}] like: {detail}")

        # Exit code: FAIL on any FAIL, 0 otherwise (WARN is not a failure)
        has_fail = any(s == "FAIL" for _, s, _ in results)
        has_warn = any(s == "WARN" for _, s, _ in results)

        if has_fail:
            print("\nRESULT: FAIL — critical bot functionality broken")
            sys.exit(1)
        elif has_warn:
            print("\nRESULT: WARN — bot responds but with unexpected content")
            sys.exit(0)
        else:
            print("\nRESULT: PASS — bot fully functional")
            sys.exit(0)

    except Exception as e:
        print(f"ERROR: E2E smoke test crashed: {e}")
        sys.exit(1)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
