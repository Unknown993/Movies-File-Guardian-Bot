"""
File handling and storage registration module.
Admins can upload, forward, or register files to generate secure deep-links.
"""

from __future__ import annotations

import asyncio
import html
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


def extract_forward_channel_info(message: Message) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Extract (channel_id, message_id, channel_title) from a forwarded channel post.
    Compatible with both Telegram Bot API 7.0+ (message.forward_origin) and legacy attributes.
    """
    fwd_origin = getattr(message, "forward_origin", None)
    if fwd_origin is not None:
        origin_chat = getattr(fwd_origin, "chat", None) or getattr(fwd_origin, "sender_chat", None)
        origin_msg_id = getattr(fwd_origin, "message_id", None)
        if origin_chat is not None and isinstance(getattr(origin_chat, "id", None), int):
            return origin_chat.id, origin_msg_id, getattr(origin_chat, "title", None)

    fwd_chat = getattr(message, "forward_from_chat", None)
    if fwd_chat is not None and isinstance(getattr(fwd_chat, "id", None), int):
        fwd_msg_id = getattr(message, "forward_from_message_id", None)
        if not isinstance(fwd_msg_id, int):
            fwd_msg_id = None
        return fwd_chat.id, fwd_msg_id, getattr(fwd_chat, "title", None)

    return None, None, None


async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming media files sent or forwarded by admins/developer.
    Stores the file, optionally mirrors direct uploads to storage channel, and returns shareable link
    plus one-click channel indexing options when forwarded from a channel.
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

    fwd_chat_id, fwd_msg_id, fwd_chat_title = extract_forward_channel_info(message)
    is_already_in_storage = (chat.id == STORAGE_CHANNEL_ID) or (fwd_chat_id is not None)

    # Only mirror to storage channel if it is a direct upload (not forwarded from a channel)
    if STORAGE_CHANNEL_ID and not is_already_in_storage:
        try:
            stored_msg = await context.bot.copy_message(
                chat_id=STORAGE_CHANNEL_ID,
                from_chat_id=chat.id,
                message_id=message.message_id,
                protect_content=False,
            )
            source_chat_id = STORAGE_CHANNEL_ID
            source_message_id = stored_msg.message_id
            logger.debug("Mirrored file to storage channel %s (msg: %s)", STORAGE_CHANNEL_ID, source_message_id)
        except Exception as e:
            logger.warning("Could not mirror file to storage channel: %s. Using direct chat source.", e)
    elif fwd_chat_id is not None:
        source_chat_id = fwd_chat_id
        if fwd_msg_id:
            source_message_id = fwd_msg_id
    elif chat.id == STORAGE_CHANNEL_ID:
        source_chat_id = STORAGE_CHANNEL_ID

    clean_name = smart_clean_filename(file_name or caption)

    # Register in database (or reuse existing code if already indexed from that channel post)
    existing = await db.get_file_by_source_message(source_chat_id, source_message_id)
    if isinstance(existing, dict) and "file_code" in existing:
        file_code = existing["file_code"]
    else:
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
        "🔒 <b>Mode 1 (View Only):</b> Recipients can view/stream, but cannot save or forward."
        if curr_mode.value == "view_only"
        else "⏱️ <b>Mode 2 (Download Allowed):</b> Recipients can save, but file will self-destruct shortly after delivery."
    )

    buttons = [
        [InlineKeyboardButton("🔗 Test Share Link", url=share_link)],
        [InlineKeyboardButton("📋 Copy Link", switch_inline_query=str(file_code))],
    ]
    if fwd_chat_id is not None and fwd_msg_id is not None:
        buttons.append([
            InlineKeyboardButton(
                f"⚡ Index Channel (Up to #{fwd_msg_id})",
                callback_data=f"fastidx_{fwd_chat_id}_{fwd_msg_id}",
            )
        ])

    reply_keyboard = InlineKeyboardMarkup(buttons)

    channel_line = ""
    if fwd_chat_id is not None:
        ch_label = f"{fwd_chat_title} ({fwd_chat_id})" if fwd_chat_title else str(fwd_chat_id)
        channel_line = f"• <b>Source Channel:</b> <code>{html.escape(ch_label)}</code> (Msg <code>#{source_message_id}</code>)\n"

    await message.reply_text(
        f"✅ <b>File Registered Successfully!</b>\n\n"
        f"• <b>Code:</b> <code>{html.escape(str(file_code))}</code>\n"
        f"• <b>Name:</b> <code>{html.escape(str(clean_name))}</code>\n"
        f"• <b>Type:</b> <code>{html.escape(str(file_type))}</code>\n"
        f"• <b>Size:</b> <code>{html.escape(str(format_file_size(file_size)))}</code>\n"
        f"{channel_line}\n"
        f"🌐 <b>Shareable Link:</b>\n<code>{html.escape(str(share_link))}</code>\n\n"
        f"ℹ️ <b>Current Strategy:</b>\n{mode_text}",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_keyboard,
    )


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Automatically handle incoming media posts in the configured storage channel.
    Silently indexes the file into the database without sending any channel or log noise.
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
    if not existing:
        await db.register_file(
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

async def index_range_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Bulk scan and register files in the storage channel within a range of message IDs.
    Delegates directly to high-speed MTProto indexer:
    - Never posts to storage channel
    - Never forwards or cleans up messages in PM
    - Pure, silent database indexing with live progress card in chat
    """
    from handlers.fast_index_handlers import fast_index_command
    await fast_index_command(update, context)


async def stop_index_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop any currently active channel indexing process: /stop_index."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not is_admin(user.id):
        await message.reply_text(
            "⛔ **Access Denied:** Only administrators can use this command.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not context.bot_data.get("is_indexing"):
        await message.reply_text(
            "ℹ️ **No indexing process is currently running.**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    context.bot_data["cancel_indexing"] = True
    task = context.bot_data.get("indexing_task")
    if task and not task.done():
        task.cancel()

    await message.reply_text(
        "🛑 **Stopping channel indexing...**\n"
        "The active indexing process has been requested to halt. All progress up to this moment is saved.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def stop_indexing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle click on the inline '🛑 Stop Indexing' button."""
    query = update.callback_query
    if not query:
        return

    user = update.effective_user
    if not user or not is_admin(user.id):
        await query.answer("⛔ Only admins can stop indexing.", show_alert=True)
        return

    if not context.bot_data.get("is_indexing"):
        await query.answer("ℹ️ Indexing is not currently active.", show_alert=True)
        return

    context.bot_data["cancel_indexing"] = True
    task = context.bot_data.get("indexing_task")
    if task and not task.done():
        task.cancel()

    await query.answer("🛑 Stopping indexing process...", show_alert=True)
