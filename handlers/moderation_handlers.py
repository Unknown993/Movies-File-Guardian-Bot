"""
Group Moderation and Utilities module:
- /ban, /unban, /tban (timed ban)
- /mute, /unmute, /tmute (timed mute)
- /pin, /unpin, /purge (bulk message cleanup)
- /id, /info (IDs and user inspection)
"""

from __future__ import annotations

import re
import time
import html
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone, timedelta
from telegram import Update, Message, ChatPermissions
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest

from config import is_admin

logger = logging.getLogger(__name__)


def parse_duration_seconds(time_str: str) -> Optional[int]:
    """Parse time strings like '10m', '2h', '1d' into seconds."""
    match = re.match(r"^(\d+)([mhd])$", time_str.strip().lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return None


async def is_caller_admin(update: Update) -> bool:
    """Verify if the caller is a group administrator or developer."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if is_admin(user.id):
        return True
    try:
        member = await chat.get_member(user.id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        return False


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban a user from the group: /ban [reply or user_id]."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text(
            "ℹ️ <code>/ban</code> is for group chats. To ban a user from using the bot in PM, use <code>/ban_user &lt;user_id&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.MARKDOWN)
        return

    target_id: Optional[int] = None
    target_name: str = "User"

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    elif context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])
        target_name = str(target_id)

    if not target_id:
        await message.reply_text("📌 **Usage:** Reply to a user with `/ban` or type `/ban <user_id>`.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        await chat.ban_member(user_id=target_id)
        await message.reply_text(
            f"🔨 Banned <a href='tg://user?id={target_id}'>{html.escape(target_name)}</a> from the group.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ Could not ban user: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a user: /unban [reply or user_id]."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text(
            "ℹ️ <code>/unban</code> is for group chats. To unban a user from the bot, use <code>/unban_user &lt;user_id&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.MARKDOWN)
        return

    target_id: Optional[int] = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])

    if not target_id:
        await message.reply_text("📌 **Usage:** Reply to a user with `/unban` or type `/unban <user_id>`.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        await chat.unban_member(user_id=target_id)
        await message.reply_text(f"✅ Unbanned user `{target_id}`.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.reply_text(f"❌ Could not unban user: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def tban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Temporarily ban a user: /tban <time> [reply]. E.g. /tban 2h."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/tban</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if not args or not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply_text("📌 **Usage:** Reply to a user with `/tban <time>` (e.g. `/tban 2h` or `/tban 30m`).", parse_mode=ParseMode.MARKDOWN)
        return

    duration = parse_duration_seconds(args[0])
    if not duration:
        await message.reply_text("❌ Invalid duration format! Use m, h, or d (e.g. `30m`, `2h`, `1d`).", parse_mode=ParseMode.MARKDOWN)
        return

    target = message.reply_to_message.from_user
    until_date = datetime.now(timezone.utc) + timedelta(seconds=duration)

    try:
        await chat.ban_member(user_id=target.id, until_date=until_date)
        await message.reply_text(
            f"⏳ Temporarily banned <a href='tg://user?id={target.id}'>{html.escape(target.first_name)}</a> for <code>{html.escape(args[0])}</code>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ Could not temp-ban user: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute a user: /mute [reply]."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/mute</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.MARKDOWN)
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply_text("📌 **Usage:** Reply to a user with `/mute` to restrict sending messages.", parse_mode=ParseMode.MARKDOWN)
        return

    target = message.reply_to_message.from_user
    try:
        await chat.restrict_member(user_id=target.id, permissions=ChatPermissions(can_send_messages=False))
        await message.reply_text(
            f"🔇 Muted <a href='tg://user?id={target.id}'>{html.escape(target.first_name)}</a>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ Could not mute user: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute a user: /unmute [reply]."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/unmute</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.MARKDOWN)
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply_text("📌 **Usage:** Reply to a user with `/unmute`.", parse_mode=ParseMode.MARKDOWN)
        return

    target = message.reply_to_message.from_user
    try:
        await chat.restrict_member(
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await message.reply_text(
            f"🔊 Unmuted <a href='tg://user?id={target.id}'>{html.escape(target.first_name)}</a>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ Could not unmute user: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def tmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Temporarily mute a user: /tmute <time> [reply]. E.g. /tmute 30m."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/tmute</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if not args or not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply_text("📌 **Usage:** Reply to a user with `/tmute <time>` (e.g. `/tmute 30m` or `/tmute 2h`).", parse_mode=ParseMode.MARKDOWN)
        return

    duration = parse_duration_seconds(args[0])
    if not duration:
        await message.reply_text("❌ Invalid duration format! Use m, h, or d (e.g. `30m`, `2h`, `1d`).", parse_mode=ParseMode.MARKDOWN)
        return

    target = message.reply_to_message.from_user
    until_date = datetime.now(timezone.utc) + timedelta(seconds=duration)

    try:
        await chat.restrict_member(
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date,
        )
        await message.reply_text(
            f"⏳ Temporarily muted <a href='tg://user?id={target.id}'>{html.escape(target.first_name)}</a> for <code>{html.escape(args[0])}</code>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ Could not temp-mute user: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pin a replied message: /pin."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type == ChatType.PRIVATE:
        await message.reply_text("ℹ️ <code>/pin</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return
    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use <code>/pin</code>.", parse_mode=ParseMode.HTML)
        return

    if not message.reply_to_message:
        await message.reply_text("📌 Reply to any message with `/pin`.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        await message.reply_to_message.pin()
        await message.reply_text("📌 Message pinned successfully.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.reply_text(f"❌ Failed to pin: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def unpin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unpin the current or replied message: /unpin."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type == ChatType.PRIVATE:
        await message.reply_text("ℹ️ <code>/unpin</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return
    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use <code>/unpin</code>.", parse_mode=ParseMode.HTML)
        return

    try:
        if message.reply_to_message:
            await message.reply_to_message.unpin()
        else:
            await chat.unpin_message()
        await message.reply_text("📌 Message unpinned.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.reply_text(f"❌ Failed to unpin: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def purge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete all messages between replied message and this command: /purge."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/purge</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use `/purge`.", parse_mode=ParseMode.MARKDOWN)
        return

    if not message.reply_to_message:
        await message.reply_text("📌 **Usage:** Reply to the starting message with `/purge` to delete everything up to now.", parse_mode=ParseMode.MARKDOWN)
        return

    start_id = message.reply_to_message.message_id
    end_id = message.message_id

    if end_id - start_id > 100:
        await message.reply_text("⚠️ Purge is limited to 100 messages at a time.", parse_mode=ParseMode.MARKDOWN)
        return

    deleted = 0
    for mid in range(start_id, end_id + 1):
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=mid)
            deleted += 1
        except Exception:
            pass

    notify = await message.reply_text(f"🗑️ Purged `{deleted}` messages.")
    await asyncio.sleep(3)
    try:
        await notify.delete()
    except Exception:
        pass


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user ID, chat ID, and replied message details: /id."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    lines = [
        f"👤 <b>User ID:</b> <code>{user.id}</code>",
        f"💬 <b>Chat ID:</b> <code>{chat.id}</code>",
        f"🏷️ <b>Chat Type:</b> <code>{html.escape(str(chat.type))}</code>",
    ]

    if message.reply_to_message:
        replied = message.reply_to_message
        r_user = replied.from_user
        lines.append(f"📩 <b>Replied Message ID:</b> <code>{replied.message_id}</code>")
        if r_user:
            lines.append(f"👥 <b>Replied User ID:</b> <code>{r_user.id}</code>")

    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get full profile details about a user: /info [reply]."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    target = message.reply_to_message.from_user if message.reply_to_message and message.reply_to_message.from_user else user
    full_name = f"{html.escape(target.first_name or '')} {html.escape(target.last_name or '')}".strip() or "User"
    username_display = f"@{html.escape(target.username)}" if target.username else "None"

    text = (
        f"ℹ️ <b>User Profile Information</b>\n\n"
        f"• <b>Name:</b> {full_name}\n"
        f"• <b>User ID:</b> <code>{target.id}</code>\n"
        f"• <b>Username:</b> {username_display}\n"
        f"• <b>Is Bot:</b> <code>{'Yes' if target.is_bot else 'No'}</code>\n"
        f"• <b>Permanent Link:</b> <a href='tg://user?id={target.id}'>Profile</a>"
    )

    await message.reply_text(text, parse_mode=ParseMode.HTML)
