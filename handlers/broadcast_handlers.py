"""
Broadcast system module:
- /broadcast: Sends announcement/media to all registered bot users.
- /group_broadcast: Sends announcement/media to all registered groups.
"""

from __future__ import annotations

import asyncio
import logging
import time
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import TelegramError, Forbidden, BadRequest

from config import is_admin
from database import Database

logger = logging.getLogger(__name__)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcast a message or replied media to all users: /broadcast."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    text_to_send = " ".join(context.args or []).strip()
    replied = message.reply_to_message

    if not text_to_send and not replied:
        await message.reply_text(
            "📌 **Usage:** Reply to any message or media with `/broadcast`\n"
            "Or use `/broadcast <your text>`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    user_ids = await db.get_all_users()
    if not user_ids:
        await message.reply_text("📭 No registered users in database to broadcast to.", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await message.reply_text(
        f"📢 **Starting User Broadcast to {len(user_ids)} users...**",
        parse_mode=ParseMode.MARKDOWN,
    )

    success = 0
    blocked = 0
    failed = 0
    start_time = time.time()

    for i, target_id in enumerate(user_ids, 1):
        try:
            if replied:
                await replied.copy(chat_id=target_id)
            else:
                await context.bot.send_message(chat_id=target_id, text=text_to_send, parse_mode=ParseMode.MARKDOWN)
            success += 1
        except Forbidden:
            blocked += 1
        except BadRequest as e:
            if "Chat not found" in e.message or "user not found" in e.message.lower():
                blocked += 1
            else:
                failed += 1
        except Exception:
            failed += 1

        # Periodic status updates every 25 messages
        if i % 25 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 **Broadcast in progress:** `{i}/{len(user_ids)}`\n"
                    f"• ✅ Success: `{success}`\n"
                    f"• 🚫 Blocked: `{blocked}`\n"
                    f"• ❌ Failed: `{failed}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            await asyncio.sleep(0.5)

    elapsed = round(time.time() - start_time, 1)
    await status_msg.edit_text(
        f"✅ **User Broadcast Complete!**\n\n"
        f"👥 **Total Users:** `{len(user_ids)}`\n"
        f"✅ **Delivered:** `{success}`\n"
        f"🚫 **Blocked/Deleted:** `{blocked}`\n"
        f"❌ **Failed:** `{failed}`\n"
        f"⏱️ **Time Taken:** `{elapsed}s`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def group_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcast a message or replied media to all groups: /group_broadcast."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    text_to_send = " ".join(context.args or []).strip()
    replied = message.reply_to_message

    if not text_to_send and not replied:
        await message.reply_text(
            "📌 **Usage:** Reply to any message with `/group_broadcast` or type `/group_broadcast <text>`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    chats = await db.get_all_chats()
    if not chats:
        await message.reply_text("📭 No registered groups in database to broadcast to.", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await message.reply_text(
        f"📢 **Starting Group Broadcast to {len(chats)} groups...**",
        parse_mode=ParseMode.MARKDOWN,
    )

    success = 0
    failed = 0
    start_time = time.time()

    for i, chat_rec in enumerate(chats, 1):
        target_chat_id = chat_rec["chat_id"]
        try:
            if replied:
                await replied.copy(chat_id=target_chat_id)
            else:
                await context.bot.send_message(chat_id=target_chat_id, text=text_to_send, parse_mode=ParseMode.MARKDOWN)
            success += 1
        except Exception:
            failed += 1

        if i % 15 == 0:
            await asyncio.sleep(0.5)

    elapsed = round(time.time() - start_time, 1)
    await status_msg.edit_text(
        f"✅ **Group Broadcast Complete!**\n\n"
        f"👥 **Total Groups:** `{len(chats)}`\n"
        f"✅ **Delivered:** `{success}`\n"
        f"❌ **Failed:** `{failed}`\n"
        f"⏱️ **Time Taken:** `{elapsed}s`",
        parse_mode=ParseMode.MARKDOWN,
    )
