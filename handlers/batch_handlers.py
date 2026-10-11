"""
Batch and Single-File Link generator (File Store module).
Allows admins to create shareable links for individual files or entire batches of channel posts.
"""

from __future__ import annotations

import html
import re
import secrets
import asyncio
import logging
from typing import Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatType
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest

from config import is_admin, STORAGE_CHANNEL_ID
from database import Database
from delivery import deliver_file_to_user
from handlers.file_handlers import extract_media_details

logger = logging.getLogger(__name__)

LINK_REGEX = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/(?:c/)?([a-zA-Z0-9_]+)/(\d+)")


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a shareable link by replying to any media message: /link."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not is_admin(user.id):
        await message.reply_text("⛔ Only admins can generate shareable links.", parse_mode=ParseMode.HTML)
        return

    replied = message.reply_to_message
    if not replied:
        await message.reply_text(
            "📌 <b>Usage:</b> Reply to any document, video, audio, or photo with <code>/link</code> to get a direct access link.",
            parse_mode=ParseMode.HTML,
        )
        return

    media_info = extract_media_details(replied)
    if not media_info:
        await message.reply_text("❌ The replied message does not contain supported media.", parse_mode=ParseMode.HTML)
        return

    file_id, file_unique_id, file_type, file_name, file_size = media_info
    db: Database = context.bot_data["db"]

    # Check if already registered
    existing = await db.get_file_by_unique_id(file_unique_id) if file_unique_id else None
    if existing:
        file_code = existing["file_code"]
    else:
        file_code = await db.register_file(
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_type=file_type,
            file_name=file_name,
            file_size=file_size,
            caption=replied.caption,
            source_chat_id=replied.chat_id,
            source_message_id=replied.message_id,
            uploaded_by=user.id,
        )

    bot_info = await context.bot.get_me()
    share_link = f"https://t.me/{bot_info.username}?start=file_{file_code}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Open Share Link", url=share_link)]
    ])

    await message.reply_text(
        f"✅ <b>Permanent File Link Generated:</b>\n\n<code>{html.escape(share_link)}</code>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Generate a single batch link for multiple channel posts:
    Usage: /batch <first_message_url> <last_message_url>
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not is_admin(user.id):
        await message.reply_text("⛔ Only admins can create batch links.", parse_mode=ParseMode.HTML)
        return

    args = context.args or []
    if len(args) != 2:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/batch &lt;start_message_link&gt; &lt;end_message_link&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/batch https://t.me/c/1234567890/10 https://t.me/c/1234567890/25</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    first_url, last_url = args[0].strip(), args[1].strip()
    match1 = LINK_REGEX.match(first_url)
    match2 = LINK_REGEX.match(last_url)

    if not match1 or not match2:
        await message.reply_text("❌ Invalid Telegram message links provided.", parse_mode=ParseMode.HTML)
        return

    chat_raw1, msg_id1 = match1.group(1), int(match1.group(2))
    chat_raw2, msg_id2 = match2.group(1), int(match2.group(2))

    if chat_raw1 != chat_raw2:
        await message.reply_text("❌ Both links must belong to the same channel.", parse_mode=ParseMode.HTML)
        return

    start_id = min(msg_id1, msg_id2)
    end_id = max(msg_id1, msg_id2)
    count = end_id - start_id + 1

    if count > 100:
        await message.reply_text("⚠️ Batch size cannot exceed 100 messages at once.", parse_mode=ParseMode.HTML)
        return

    # Determine channel ID
    channel_target = int(f"-100{chat_raw1}") if chat_raw1.isdigit() else f"@{chat_raw1}"

    status_msg = await message.reply_text(
        f"⏳ <b>Processing batch range {start_id} → {end_id} ({count} posts)...</b>",
        parse_mode=ParseMode.HTML,
    )

    db: Database = context.bot_data["db"]
    file_codes: List[str] = []

    # Check already registered records first
    for msg_id in range(start_id, end_id + 1):
        file_rec = None
        if isinstance(channel_target, int):
            file_rec = await db.get_file_by_source_message(channel_target, msg_id)
        if not file_rec and STORAGE_CHANNEL_ID:
            file_rec = await db.get_file_by_source_message(STORAGE_CHANNEL_ID, msg_id)

        if file_rec:
            file_codes.append(file_rec["file_code"])
            continue

        # If not registered, attempt to copy / index from channel
        try:
            target_chat_id = STORAGE_CHANNEL_ID or channel_target
            copied = await context.bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=channel_target,
                message_id=msg_id,
            )
            media_info = extract_media_details(copied)
            if media_info:
                fid, f_uid, f_type, f_name, f_size = media_info
                code = await db.register_file(
                    file_id=fid,
                    file_unique_id=f_uid,
                    file_type=f_type,
                    file_name=f_name,
                    file_size=f_size,
                    caption=copied.caption,
                    source_chat_id=target_chat_id,
                    source_message_id=copied.message_id,
                    uploaded_by=user.id,
                )
                file_codes.append(code)
            await asyncio.sleep(0.3)
        except Exception:
            continue

    if not file_codes:
        await status_msg.edit_text("❌ No supported media files found in the specified range.")
        return

    batch_id = secrets.token_urlsafe(8)
    await db.save_batch_link(batch_id, file_codes, user.id)

    bot_info = await context.bot.get_me()
    batch_url = f"https://t.me/{bot_info.username}?start=batch_{batch_id}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Open Batch Link", url=batch_url)]
    ])

    await status_msg.edit_text(
        f"✅ <b>Batch Link Created!</b>\n\n"
        f"📁 <b>Total Files:</b> <code>{len(file_codes)}</code>\n"
        f"🔗 <b>Link:</b> <code>{html.escape(batch_url)}</code>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def deliver_batch_to_user(
    bot,
    db: Database,
    job_queue,
    chat_id: int,
    chat_type: str,
    batch_id: str,
    bot_username: str,
) -> None:
    """Delivers all files in a batch sequentially to the user."""
    file_codes = await db.get_batch_link(batch_id)
    if not file_codes:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ <b>Batch Not Found or Expired</b>\n\nThis batch link does not exist or has been removed.",
            parse_mode=ParseMode.HTML,
        )
        return

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"📦 <b>Starting delivery of {len(file_codes)} file(s)...</b>\nPlease wait a moment.",
        parse_mode=ParseMode.HTML,
    )

    delivered_count = 0
    for code in file_codes:
        file_rec = await db.get_file_by_code(code)
        if not file_rec:
            continue

        try:
            delivered = await deliver_file_to_user(
                bot=bot,
                db=db,
                job_queue=job_queue,
                chat_id=chat_id,
                chat_type=chat_type,
                file_record=file_rec,
                bot_username=bot_username,
            )
            if delivered:
                delivered_count += 1
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning("Error delivering file %s in batch: %s", code, e)

    try:
        await status_msg.edit_text(
            f"✅ <b>Batch Completed!</b> Delivered <code>{delivered_count}/{len(file_codes)}</code> files.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
