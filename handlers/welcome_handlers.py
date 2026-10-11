"""
Group Welcome Greetings & Member Management module.
Greets incoming chat members and auto-deletes prior welcome messages to avoid spam.
"""

from __future__ import annotations

import html
import logging
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TelegramError

from config import WELCOME_TEXT, WELCOME_PIC, is_admin, send_work_log
from database import Database

logger = logging.getLogger(__name__)


async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle new members joining a group chat."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        return

    db: Database = context.bot_data["db"]
    # Update chat registry
    is_new_chat = await db.add_or_update_chat(chat.id, chat.title, chat.type)
    if is_new_chat:
        await send_work_log(
            context.bot,
            db,
            f"👥 <b>#NewGroup</b>\n\n"
            f"🏷 <b>Tɪᴛʟᴇ:</b> {html.escape(chat.title or 'Group')}\n"
            f"🆔 <b>Cʜᴀᴛ ID:</b> <code>{chat.id}</code>",
        )

    # Check if welcome greetings are enabled for this chat
    welcome_enabled = await db.get_chat_welcome(chat.id)
    if not welcome_enabled:
        return

    new_members = message.new_chat_members or []
    bot_info = await context.bot.get_me()

    for member in new_members:
        # Register user in DB
        await db.add_or_update_user(member.id, member.first_name, member.username)

        # If the bot itself was added
        if member.id == bot_info.id:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Support & Updates", url=f"https://t.me/{bot_info.username}?start=help")]
            ])
            await message.reply_text(
                f"🎉 **Thanks for adding me to {chat.title}!**\n\n"
                "• Make sure I have **Admin permissions** to delete messages and manage filters.\n"
                "• Send `/help` in private DM to see all my features.",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
            continue

        # Clean up prior welcome message to prevent chat clutter
        last_welcome_id = context.chat_data.get("last_welcome_msg_id")
        if last_welcome_id:
            try:
                await context.bot.delete_message(chat_id=chat.id, message_id=last_welcome_id)
            except Exception:
                pass

        user_mention = f"<a href='tg://user?id={member.id}'>{html.escape(member.first_name)}</a>"
        chat_title = html.escape(chat.title or "this group")
        caption = WELCOME_TEXT.format(user=user_mention, chat=chat_title)

        welcome_msg: Message
        if WELCOME_PIC:
            try:
                welcome_msg = await message.reply_photo(
                    photo=WELCOME_PIC,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning("Could not send welcome photo: %s. Falling back to text.", e)
                welcome_msg = await message.reply_text(
                    text=caption,
                    parse_mode=ParseMode.HTML,
                )
        else:
            welcome_msg = await message.reply_text(
                text=caption,
                parse_mode=ParseMode.HTML,
            )

        context.chat_data["last_welcome_msg_id"] = welcome_msg.message_id


async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Group admin command to toggle welcome greetings: /welcome on|off."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ This command can only be used inside groups.", parse_mode=ParseMode.MARKDOWN)
        return

    # Check if user is group admin or bot developer
    db: Database = context.bot_data["db"]
    is_user_admin = False
    try:
        member = await chat.get_member(user.id)
        is_user_admin = member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        pass

    if not is_user_admin and not is_admin(user.id):
        await message.reply_text("⛔ Only group administrators can configure welcome messages.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if not args:
        enabled = await db.get_chat_welcome(chat.id)
        status_str = "✅ **ENABLED**" if enabled else "❌ **DISABLED**"
        await message.reply_text(
            f"👋 **Welcome Message Status:** {status_str}\n\n"
            "Use `/welcome on` to enable or `/welcome off` to disable.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    arg = args[0].strip().lower()
    if arg in ["on", "enable", "true", "yes", "1"]:
        await db.set_chat_welcome(chat.id, True)
        await message.reply_text("✅ Welcome greetings **ENABLED** for this group.", parse_mode=ParseMode.MARKDOWN)
    elif arg in ["off", "disable", "false", "no", "0"]:
        await db.set_chat_welcome(chat.id, False)
        await message.reply_text("❌ Welcome greetings **DISABLED** for this group.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply_text("Usage: `/welcome on` or `/welcome off`", parse_mode=ParseMode.MARKDOWN)
