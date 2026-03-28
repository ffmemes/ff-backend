#!/usr/bin/env python3
"""
One-time interactive script to generate a Telethon session string.

Usage:
    pip install telethon
    python scripts/generate_session_string.py

You'll be prompted for:
    1. API ID and API Hash (from https://my.telegram.org)
    2. Phone number
    3. Verification code (sent to your Telegram)

The output is a session string — store it as TELEGRAM_SESSION_STRING env var.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API ID: "))
api_hash = input("API Hash: ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()
    print("\nSession string (save as TELEGRAM_SESSION_STRING):\n")
    print(session_string)
