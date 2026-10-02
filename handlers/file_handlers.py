"""
File handling and storage registration module.
Admins can upload, forward, or register files to generate secure deep-links.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple
import telegram.error
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import STORAGE_CHANNEL_ID, DEVELOPER_ID, is_admin
from database import Database
from cleaner import smart_clean_filename, get_file_type_icon

logger = logging.getLogger(__name__)


def extract_media_details(message: Message) -> Optional[Tuple[str, Optional[str], str, Optional[str], int]]:
    """
    Extract (file_id, file_unique_id, file_type, file_name, file_size) from a message.
    """
    if message.document:
        doc = message.document
        return doc.file_id, doc.file_unique_id, "document", doc.file_name, doc.file_size or 0
    elif message.video:
        vid = message.video
        return vid.file_id, vid.file_unique_id, "video", vid.file_name, vid.file_size or 0
    elif message.audio:
        aud = message.audio
        return aud.file_id, aud.file_unique_id, "audio", aud.file_name or aud.title, aud.file_size or 0
    elif message.photo:
        photo = message.photo[-1]  # Highest resolution
        return photo.file_id, photo.file_unique_id, "photo", "photo.jpg", photo.file_size or 0
    elif message.voice:
        v = message.voice
        return v.file_id, v.file_unique_id, "voice", "voice.ogg", v.file_size or 0
    elif message.animation:
        anim = message.animation
        return anim.file_id, anim.file_unique_id, "animation", anim.file_name, anim.file_size or 0
    elif message.video_note:
        vn = message.video_note
        return vn.file_id, vn.file_unique_id, "video_note", "video_note.mp4", vn.file_size or 0
    return None


def format_file_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes <= 0:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming media files sent by admins/developer.
    Stores the file, optionally mirrors to storage channel, and returns shareable link.
    """
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    # Restrict file upload/registration to admins & developer
    if not is_admin(user.id):
        return

    media_info = extract_media_details(message)
    if not media_info:
        return

    file_id, file_unique_id, file_type, file_name, file_size = media_info
    caption = message.caption or ""

    db: Database = context.bot_data["db"]
    source_chat_id = chat.id
    source_message_id = message.message_id

    # If storage channel is configured, copy the message to the storage channel
    if STORAGE_CHANNEL_ID:
        try:
            stored_msg = await context.bot.copy_message(
                chat_id=STORAGE_CHANNEL_ID,
                from_chat_id=chat.id,
                message_id=message.message_id,
                protect_content=False,
            )
            source_chat_id = STORAGE_CHANNEL_ID
            source_message_id = stored_msg.message_id
            logger.info("Mirrored file to storage channel %s (msg: %s)", STORAGE_CHANNEL_ID, source_message_id)
        except Exception as e:
            logger.warning("Could not mirror file to storage channel: %s. Using direct chat source.", e)

    clean_name = smart_clean_filename(file_name or caption)

    # Register in database
    file_code = await db.register_file(
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_type=file_type,
        file_name=clean_name,
        file_size=file_size,
        caption=caption,
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        uploaded_by=user.id,
    )

    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"
    share_link = f"https://t.me/{bot_username}?start=file_{file_code}"

    curr_mode = await db.get_delivery_mode()
    mode_text = (
        "🔒 **Mode 1 (View Only):** Recipients can view/stream, but cannot save or forward."
        if curr_mode.value == "view_only"
        else "⏱️ **Mode 2 (Download Allowed):** Recipients can save, but file will self-destruct shortly after delivery."
    )

    reply_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Test Share Link", url=share_link)],
        [InlineKeyboardButton("📋 Copy Link", switch_inline_query=file_code)],
    ])

    await message.reply_text(
        f"✅ **File Registered Successfully!**\n\n"
        f"• **Code:** `{file_code}`\n"
        f"• **Name:** `{clean_name}`\n"
        f"• **Type:** `{file_type}`\n"
        f"• **Size:** `{format_file_size(file_size)}`\n\n"
        f"🌐 **Shareable Link:**\n`{share_link}`\n\n"
        f"ℹ️ **Current Strategy:**\n{mode_text}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_keyboard,
    )


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Automatically handle incoming media posts in the configured storage channel.
    Indexes the file into the database and notifies the developer.
    """
    post = update.channel_post
    if not post:
        return

    # Restrict to configured storage channel
    if STORAGE_CHANNEL_ID and post.chat_id != STORAGE_CHANNEL_ID:
        return

    media_info = extract_media_details(post)
    if not media_info:
        return

    file_id, file_unique_id, file_type, file_name, file_size = media_info
    caption = post.caption or ""
    db: Database = context.bot_data["db"]

    # Check if already registered
    existing = await db.get_file_by_source_message(post.chat_id, post.message_id)
    clean_name = smart_clean_filename(file_name or caption)
    if existing:
        file_code = existing["file_code"]
    else:
        file_code = await db.register_file(
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_type=file_type,
            file_name=clean_name,
            file_size=file_size,
            caption=caption,
            source_chat_id=post.chat_id,
            source_message_id=post.message_id,
            uploaded_by=DEVELOPER_ID or 0,
        )
        logger.info(
            "Auto-registered new channel post %s from channel %s as code %s",
            post.message_id,
            post.chat_id,
            file_code,
        )

    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"
    share_link = f"https://t.me/{bot_username}?start=file_{file_code}"

    # Notify developer if configured
    if DEVELOPER_ID:
        try:
            await context.bot.send_message(
                chat_id=DEVELOPER_ID,
                text=(
                    f"📥 **New File Auto-Indexed from Storage Channel!**\n\n"
                    f"• **Code:** `{file_code}`\n"
                    f"• **Name:** `{clean_name}`\n"
                    f"• **Type:** `{file_type}`\n"
                    f"• **Size:** `{format_file_size(file_size)}`\n"
                    f"• **Source Msg ID:** `#{post.message_id}`\n\n"
                    f"🌐 **Shareable Link:**\n`{share_link}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning("Could not send auto-index notification to developer: %s", e)


async def index_range_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Bulk scan and register files in the storage channel within a range of message IDs.
    Usage: /index_range <start_id> <end_id>
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not is_admin(user.id):
        await message.reply_text(
            "⛔ **Access Denied:** Only administrators can index channel files.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not STORAGE_CHANNEL_ID:
        await message.reply_text(
            "❌ **STORAGE_CHANNEL_ID is not configured in .env!**\n"
            "Please set your channel ID first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if len(args) < 2:
        await message.reply_text(
            "ℹ️ **Usage:** `/index_range <start_id> <end_id>`\n\n"
            "**Example:** `/index_range 1 50`\n"
            "Scans messages #1 to #50 in your storage channel and automatically registers all media files into the database.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        start_id = int(args[0])
        end_id = int(args[1])
    except ValueError:
        await message.reply_text("❌ `start_id` and `end_id` must both be integers.")
        return

    if start_id <= 0 or end_id <= 0:
        await message.reply_text("❌ Message IDs must be positive numbers (greater than 0).")
        return

    if start_id > end_id:
        await message.reply_text("❌ `start_id` cannot be greater than `end_id`.")
        return

    total_to_scan = end_id - start_id + 1
    if total_to_scan > 500:
        await message.reply_text(
            f"⚠️ **Range too large ({total_to_scan} messages).**\n"
            f"To prevent Telegram rate-limits, please scan up to 500 messages at a time (e.g. `/index_range {start_id} {start_id + 499}`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await message.reply_text(
        f"🔍 **Starting scan in channel `{STORAGE_CHANNEL_ID}`...**\n"
        f"Scanning messages `#{start_id}` to `#{end_id}` ({total_to_scan} messages).\n"
        f"Please wait a moment...",
        parse_mode=ParseMode.MARKDOWN,
    )

    db: Database = context.bot_data["db"]
    new_indexed = 0
    already_indexed = 0
    skipped_count = 0

    for msg_id in range(start_id, end_id + 1):
        # Check if already registered
        existing = await db.get_file_by_source_message(STORAGE_CHANNEL_ID, msg_id)
        if existing:
            already_indexed += 1
            continue

        fwd = None
        try:
            fwd = await context.bot.forward_message(
                chat_id=user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=msg_id,
            )
        except telegram.error.RetryAfter as r:
            await asyncio.sleep(r.retry_after + 1)
            try:
                fwd = await context.bot.forward_message(
                    chat_id=user.id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=msg_id,
                )
            except Exception:
                skipped_count += 1
                continue
        except telegram.error.TelegramError:
            skipped_count += 1
            continue

        if fwd:
            media_info = extract_media_details(fwd)
            if media_info:
                file_id, file_unique_id, file_type, file_name, file_size = media_info
                caption = fwd.caption or ""
                clean_name = smart_clean_filename(file_name or caption)
                await db.register_file(
                    file_id=file_id,
                    file_unique_id=file_unique_id,
                    file_type=file_type,
                    file_name=clean_name,
                    file_size=file_size,
                    caption=caption,
                    source_chat_id=STORAGE_CHANNEL_ID,
                    source_message_id=msg_id,
                    uploaded_by=user.id,
                )
                new_indexed += 1
            else:
                skipped_count += 1

            # Delete the temporary forward
            try:
                await fwd.delete()
            except Exception:
                pass

        await asyncio.sleep(0.08)

    await status_msg.edit_text(
        f"✅ **Channel Scan Complete!**\n\n"
        f"• **Channel:** `{STORAGE_CHANNEL_ID}`\n"
        f"• **Range Scanned:** `#{start_id}` to `#{end_id}` ({total_to_scan} messages)\n"
        f"• **✨ New Files Indexed:** `{new_indexed}`\n"
        f"• **🔁 Already in Database:** `{already_indexed}`\n"
        f"• **⏭️ Non-Media / Deleted:** `{skipped_count}`\n\n"
        f"Use `/stats` to view your total file catalog.",
        parse_mode=ParseMode.MARKDOWN,
    )
