"""
Delivery engine implementing Content Protection & File Delivery Strategy:
1. Mode 1 (View Only): protect_content=True
2. Mode 2 (Downloadable): copy_message(..., protect_content=False), source stripped,
   auto-expiry self-destruct timer, private DM / temp channel restrictions.
"""

from __future__ import annotations

import html
import logging
from typing import Optional, Dict, Any
from telegram import Bot, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError, BadRequest

from config import (
    DeliveryMode,
    ALLOWED_TEMP_CHANNELS,
)
from database import Database
from cleaner import smart_clean_filename, get_file_type_icon

logger = logging.getLogger(__name__)


def is_chat_allowed_for_download(chat_id: int, chat_type: str) -> bool:
    """
    Check if the chat is permitted for downloadable delivery (Mode 2).
    Mode 2 must be restricted to private DM or dedicated temporary download channels.
    """
    if chat_type == ChatType.PRIVATE:
        return True
    if chat_id in ALLOWED_TEMP_CHANNELS:
        return True
    return False


async def execute_auto_deletion(
    bot: Bot,
    db: Database,
    chat_id: int,
    file_message_id: int,
    notice_message_id: Optional[int] = None,
    record_id: Optional[int] = None,
) -> None:
    """
    Delete the file message and the accompanying notice message upon timer expiry.
    """
    # 1. Delete the shared file message
    try:
        await bot.delete_message(chat_id=chat_id, message_id=file_message_id)
        logger.info("Successfully self-destructed file message %s in chat %s", file_message_id, chat_id)
    except BadRequest as e:
        logger.warning(
            "Could not delete file message %s in chat %s: %s",
            file_message_id,
            chat_id,
            e.message,
        )
    except TelegramError as e:
        logger.error("Telegram error deleting file message: %s", e)

    # 2. Delete the notice message (if present)
    if notice_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=notice_message_id)
            logger.info("Deleted notice message %s in chat %s", notice_message_id, chat_id)
        except BadRequest as e:
            logger.debug("Notice message %s already removed or missing: %s", notice_message_id, e.message)
        except TelegramError as e:
            logger.error("Telegram error deleting notice message: %s", e)

    # 3. Mark deletion done in database
    if record_id:
        await db.mark_deletion_done(record_id, status="deleted")


async def deliver_file_to_user(
    bot: Bot,
    db: Database,
    job_queue,
    chat_id: int,
    chat_type: str,
    file_record: Dict[str, Any],
    bot_username: str,
) -> Optional[Message]:
    """
    Deliver a stored file according to the current DeliveryMode configuration.
    
    Returns the delivered Message object if successful, or None if restricted / failed.
    """
    current_mode = await db.get_delivery_mode()
    auto_delete_secs = await db.get_auto_delete_seconds()
    file_code = file_record["file_code"]
    source_chat_id = file_record.get("source_chat_id")
    source_message_id = file_record.get("source_message_id")
    file_id = file_record["file_id"]
    file_type = file_record.get("file_type", "document")
    file_name = file_record.get("file_name")
    raw_caption = file_record.get("caption") or ""

    # Auto smart-filter filename and generate clean caption
    clean_title = smart_clean_filename(file_name or raw_caption)
    icon = get_file_type_icon(file_type, file_name or clean_title)
    display_caption = f"{icon} <b>{html.escape(clean_title)}</b>"

    # =========================================================================
    # OPTION 2: Download Allowed with Auto-Expiry & No Source Attribution
    # =========================================================================
    if current_mode == DeliveryMode.DOWNLOADABLE:
        # Check Chat Restriction (Private DM or authorized temp download channels)
        if not is_chat_allowed_for_download(chat_id, chat_type):
            dm_link = f"https://t.me/{bot_username}?start=file_{file_code}"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get File in Private DM", url=dm_link)]
            ])
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ <b>File Delivery Restricted to Private DM</b>\n\n"
                    "This file is configured with <b>self-destruct download protection</b>.\n"
                    "To prevent unauthorized propagation in groups, files can only be delivered "
                    "in a private direct message or dedicated temporary download channels.\n\n"
                    "👉 Tap the button below to receive this file privately."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return None

        # Deliver file using copy_message (protect_content=False)
        # copy_message automatically strips all source channel headers / forward attribution!
        delivered_msg: Optional[Message] = None
        if source_chat_id and source_message_id:
            try:
                delivered_msg = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                    caption=display_caption,
                    parse_mode=ParseMode.HTML,
                    protect_content=False,
                )
            except TelegramError as e:
                logger.warning("copy_message failed from %s (msg %s): %s", source_chat_id, source_message_id, e)
                if file_id and not str(file_id).startswith("mtproto_"):
                    try:
                        delivered_msg = await _send_media_fallback(
                            bot=bot,
                            chat_id=chat_id,
                            file_id=file_id,
                            file_type=file_type,
                            caption=display_caption,
                            protect_content=False,
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramError:
                        delivered_msg = None
                if delivered_msg is None:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"❌ <b>Could not retrieve file from storage channel (<code>{source_chat_id}</code>).</b>\n\n"
                            f"Make sure <b>@{html.escape(bot_username)}</b> is added as an <b>Administrator</b> in the storage channel."
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                    return None
        else:
            # Fallback direct send with protect_content=False
            delivered_msg = await _send_media_fallback(
                bot=bot,
                chat_id=chat_id,
                file_id=file_id,
                file_type=file_type,
                caption=display_caption,
                protect_content=False,
                parse_mode=ParseMode.HTML,
            )

        # Increment access count
        await db.increment_access_count(file_record["id"])

        # Format human-readable countdown string
        minutes = auto_delete_secs // 60
        seconds = auto_delete_secs % 60
        if minutes > 0 and seconds > 0:
            time_str = f"{minutes} min {seconds} sec"
        elif minutes > 0:
            time_str = f"{minutes} minute{'s' if minutes > 1 else ''}"
        else:
            time_str = f"{seconds} seconds"

        # Send self-destruct warning notice
        notice_msg = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏳ <b>Self-Destruct Timer Activated ({time_str})</b>\n\n"
                f"• <b>Download Mode:</b> Active (Forward header stripped)\n"
                f"• <b>Auto-Expiry:</b> This file will automatically be deleted in <b>{time_str}</b>.\n\n"
                f"⚡ <i>Please download or save the file to your device now!</i>"
            ),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=delivered_msg.message_id,
        )

        # 1. Record in persistent database (for restart resilience)
        rec_id = await db.schedule_message_deletion(
            chat_id=chat_id,
            file_message_id=delivered_msg.message_id,
            notice_message_id=notice_msg.message_id,
            delay_seconds=auto_delete_secs,
        )

        # 2. Schedule deletion in active JobQueue
        if job_queue:
            job_queue.run_once(
                _job_auto_delete_callback,
                when=auto_delete_secs,
                data={
                    "chat_id": chat_id,
                    "file_message_id": delivered_msg.message_id,
                    "notice_message_id": notice_msg.message_id,
                    "record_id": rec_id,
                    "db": db,
                },
                name=f"autodel_{chat_id}_{delivered_msg.message_id}",
            )

        return delivered_msg

    # =========================================================================
    # OPTION 1 (Default): View Only with Content Protection
    # =========================================================================
    else:
        # Deliver file using copy_message with protect_content=True
        # Prevents saving, copying, or forwarding outside Telegram
        delivered_msg: Optional[Message] = None
        if source_chat_id and source_message_id:
            try:
                delivered_msg = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                    caption=display_caption,
                    parse_mode=ParseMode.HTML,
                    protect_content=True,
                )
            except TelegramError as e:
                logger.warning("copy_message failed from %s (msg %s): %s", source_chat_id, source_message_id, e)
                if file_id and not str(file_id).startswith("mtproto_"):
                    try:
                        delivered_msg = await _send_media_fallback(
                            bot=bot,
                            chat_id=chat_id,
                            file_id=file_id,
                            file_type=file_type,
                            caption=display_caption,
                            protect_content=True,
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramError:
                        delivered_msg = None
                if delivered_msg is None:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"❌ <b>Could not retrieve file from storage channel (<code>{source_chat_id}</code>).</b>\n\n"
                            f"Make sure <b>@{html.escape(bot_username)}</b> is added as an <b>Administrator</b> in the storage channel."
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                    return None
        else:
            # Fallback direct send with protect_content=True
            delivered_msg = await _send_media_fallback(
                bot=bot,
                chat_id=chat_id,
                file_id=file_id,
                file_type=file_type,
                caption=display_caption,
                protect_content=True,
                parse_mode=ParseMode.HTML,
            )

        await db.increment_access_count(file_record["id"])

        # Send Mode 1 status notice
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "🔒 <b>Content Protection Active (View Only)</b>\n\n"
                "• Forwarding, copying, and saving to device are disabled.\n"
                "• You can view, read, and stream media directly within Telegram's native player."
            ),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=delivered_msg.message_id,
            protect_content=True,
        )

        return delivered_msg


async def _job_auto_delete_callback(context) -> None:
    """JobQueue callback function triggered when the self-destruct timer expires."""
    data = context.job.data
    chat_id = data["chat_id"]
    file_msg_id = data["file_message_id"]
    notice_msg_id = data.get("notice_message_id")
    record_id = data.get("record_id")
    db: Database = data["db"]

    await execute_auto_deletion(
        bot=context.bot,
        db=db,
        chat_id=chat_id,
        file_message_id=file_msg_id,
        notice_message_id=notice_msg_id,
        record_id=record_id,
    )


async def _send_media_fallback(
    bot: Bot,
    chat_id: int,
    file_id: str,
    file_type: str,
    caption: str,
    protect_content: bool,
    parse_mode: Optional[str] = None,
) -> Message:
    """Fallback sender when source message id is not available."""
    type_lower = file_type.lower()
    if type_lower == "video":
        return await bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption or None,
            parse_mode=parse_mode,
            protect_content=protect_content,
        )
    elif type_lower == "photo":
        return await bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=caption or None,
            parse_mode=parse_mode,
            protect_content=protect_content,
        )
    elif type_lower == "audio":
        return await bot.send_audio(
            chat_id=chat_id,
            audio=file_id,
            caption=caption or None,
            parse_mode=parse_mode,
            protect_content=protect_content,
        )
    elif type_lower == "voice":
        return await bot.send_voice(
            chat_id=chat_id,
            voice=file_id,
            caption=caption or None,
            parse_mode=parse_mode,
            protect_content=protect_content,
        )
    elif type_lower == "animation":
        return await bot.send_animation(
            chat_id=chat_id,
            animation=file_id,
            caption=caption or None,
            parse_mode=parse_mode,
            protect_content=protect_content,
        )
    elif type_lower == "video_note":
        return await bot.send_video_note(
            chat_id=chat_id,
            video_note=file_id,
            protect_content=protect_content,
        )
    else:
        # Default to document
        return await bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption or None,
            parse_mode=parse_mode,
            protect_content=protect_content,
        )
