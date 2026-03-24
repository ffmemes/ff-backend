"""
Handle old callback queries from old bot version
"""

from telegram import Update
from telegram.ext import (
    ContextTypes,
)


async def handle_broken_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import sys
    cb = update.callback_query.data if update.callback_query else "none"
    sys.stderr.write(f"[broken] catch-all fired: cb={cb}\n")
    sys.stderr.flush()
    await update.effective_user.send_message("🔄 The bot was updated. Press /start to continue.")
