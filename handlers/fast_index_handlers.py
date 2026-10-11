"""
High-Speed In-Bot Channel Media Indexer (Telethon MTProto).
Enables fast, direct channel indexing inside the Telegram bot without sending or copying files to the channel.

Commands:
    /fast_index [start_id] [end_id]
    /fast_index resume
    /fast
"""

from __future__ import annotations

import os
import sys
import html
import time
import shutil
import secrets
import asyncio
import logging
from pathlib import Path
from typing import Optional, Set, Tuple
import aiosqlite

from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import telegram.error

from config import BASE_DIR, STORAGE_CHANNEL_ID, DATABASE_PATH, is_admin
from cleaner import smart_clean_filename

logger = logging.getLogger(__name__)

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
TWO_FA_PASSWORD = os.getenv("TELEGRAM_2FA_PASSWORD")


async def get_db_gap_info(db_path: Path | str, storage_channel_id: int) -> Tuple[int, int, int, int]:
    """
    Analyzes SQLite files table to detect existing files, max ID, and resume point.
    Returns: (total_files, resume_from_id, max_existing_id, gap_size)
    """
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute(
            "SELECT source_message_id FROM files WHERE source_chat_id = ? ORDER BY source_message_id ASC;",
            (storage_channel_id,),
        ) as cur:
            rows = await cur.fetchall()
            ids = [r[0] for r in rows if r[0] is not None]

    if not ids:
        return 0, 0, 0, 0

    total_files = len(ids)
    max_id = ids[-1]

    # Find largest unindexed gap
    max_gap_start = 0
    max_gap_size = 0
    for i in range(len(ids) - 1):
        diff = ids[i + 1] - ids[i]
        if diff > max_gap_size:
            max_gap_size = diff
            max_gap_start = ids[i]

    if max_gap_size > 1000:
        return total_files, max_gap_start, max_id, max_gap_size
    else:
        return total_files, max_id, max_id, 0


async def fast_index_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    High-speed in-bot channel indexer using Telethon MTProto.
    Indexes files directly from Telegram servers into the bot database without sending,
    forwarding, or copying any messages into the channel!

    Usage:
        /fast_index              -> Automatically resumes from the unindexed gap to channel latest
        /fast_index <start> <end> -> Indexes specific message range (e.g. /fast_index 373801 400000)
        /fast_index <start>      -> Indexes from <start> to channel latest
        /fast_index resume       -> Resumes from where indexing left off
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not is_admin(user.id):
        await message.reply_text(
            "⛔ <b>Access Denied:</b> Only administrators can run fast indexing.",
            parse_mode=ParseMode.HTML,
        )
        return

    if context.bot_data.get("is_indexing"):
        await message.reply_text(
            "⚠️ <b>An indexing task is already running!</b>\n"
            "Use <code>/stop_index</code> or tap the stop button on the active progress message to halt it first.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Check if triggered via inline callback button (fastidx_<channel_id>_<end_id>)
    override_target = context.bot_data.pop("_override_index_target", None)

    replied = message.reply_to_message
    fwd_chat_id, fwd_msg_id, fwd_chat_title = (None, None, None)
    if replied:
        from handlers.file_handlers import extract_forward_channel_info
        fwd_chat_id, fwd_msg_id, fwd_chat_title = extract_forward_channel_info(replied)

    if override_target:
        target_channel_id, override_end_id = override_target
    else:
        target_channel_id = fwd_chat_id or STORAGE_CHANNEL_ID
        override_end_id = None

    if not target_channel_id:
        await message.reply_text(
            "❌ <b>No target channel specified!</b>\n"
            "Either set <code>STORAGE_CHANNEL_ID</code> in <code>.env</code> or forward a message from your channel and reply with <code>/index</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not API_ID or not API_HASH:
        await message.reply_text(
            "❌ <b>Telegram API Credentials Required for Fast Indexer</b>\n\n"
            "Please add <code>TELEGRAM_API_ID</code> and <code>TELEGRAM_API_HASH</code> from <a href='https://my.telegram.org'>my.telegram.org</a> to your <code>.env</code> file.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        from telethon import TelegramClient, errors
        from telethon.sessions import MemorySession, StringSession
    except ImportError:
        await message.reply_text(
            "❌ Telethon is not installed. Install with: <code>pip install telethon</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Check database and gap info for the target channel
    total_files, resume_id, max_db_id, gap_size = await get_db_gap_info(DATABASE_PATH, target_channel_id)

    args = context.args or []
    start_id: int
    end_id: Optional[int] = None

    if override_end_id is not None:
        end_id = override_end_id
        start_id = resume_id if (0 < resume_id < end_id) else 1
    elif fwd_msg_id and not args:
        end_id = fwd_msg_id
        start_id = resume_id if (0 < resume_id < end_id) else 1
    elif len(args) >= 2 and args[0].isdigit() and args[1].isdigit():
        start_id = int(args[0])
        end_id = int(args[1])
        if start_id <= 0 or end_id < start_id:
            await message.reply_text("❌ Invalid range specified. Start ID must be > 0 and <= End ID.")
            return
    elif len(args) == 1 and args[0].isdigit():
        start_id = int(args[0])
        end_id = fwd_msg_id
    else:
        # Default or 'resume': start from resume_id (gap start or max_db_id)
        start_id = resume_id if resume_id > 0 else 1
        end_id = fwd_msg_id

    stop_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Stop Indexing", callback_data="stop_indexing")]
    ])

    status_msg = await message.reply_text(
        f"⚡ <b>Connecting Fast MTProto Indexer...</b>\n\n"
        f"• <b>Channel:</b> <code>{target_channel_id}</code>\n"
        f"• <b>Database Catalog:</b> <code>{total_files:,}</code> files indexed\n"
        f"• <b>Starting From:</b> <code>#{start_id:,}</code>\n\n"
        f"Connecting to Telegram MTProto...",
        parse_mode=ParseMode.HTML,
        reply_markup=stop_keyboard,
    )

    session_str = os.getenv("TELEGRAM_SESSION_STRING", "").strip()
    base_session_file = BASE_DIR / "indexer_session.session"
    runtime_session_base = BASE_DIR / f"indexer_bot_runtime_{os.getpid()}"
    runtime_session_file = BASE_DIR / f"indexer_bot_runtime_{os.getpid()}.session"

    if session_str:
        client = TelegramClient(StringSession(session_str), int(API_ID), API_HASH)
    else:
        if base_session_file.exists():
            try:
                shutil.copy2(base_session_file, runtime_session_file)
            except Exception as e:
                logger.warning("Could not copy session file to runtime copy: %s", e)
                runtime_session_base = BASE_DIR / "indexer_session"
        else:
            runtime_session_base = BASE_DIR / "indexer_session"
        client = TelegramClient(str(runtime_session_base), int(API_ID), API_HASH)

    using_bot_mtproto = False
    channel = None

    try:
        await client.connect()
        user_authed = await client.is_user_authorized()
        if user_authed:
            try:
                channel = await client.get_entity(target_channel_id)
            except Exception:
                channel_id_pos = int(str(target_channel_id).removeprefix("-100").removeprefix("-"))
                try:
                    channel = await client.get_entity(channel_id_pos)
                except Exception:
                    try:
                        async for dialog in client.iter_dialogs():
                            if dialog.id in (target_channel_id, -channel_id_pos):
                                channel = dialog.entity
                                break
                    except Exception:
                        pass

        # If user session is not authorized or user account is not in that channel,
        # fall back to Bot MTProto session using BOT_TOKEN!
        if not channel:
            await client.disconnect()
            from config import BOT_TOKEN
            client = TelegramClient(MemorySession(), int(API_ID), API_HASH)
            await client.start(bot_token=BOT_TOKEN)
            using_bot_mtproto = True
            try:
                channel = await client.get_entity(target_channel_id)
            except Exception:
                channel_id_pos = int(str(target_channel_id).removeprefix("-100").removeprefix("-"))
                channel = await client.get_entity(channel_id_pos)
    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Could not access channel <code>{target_channel_id}</code> via MTProto:</b>\n"
            f"<code>{html.escape(str(e))}</code>\n\n"
            f"Make sure the bot is added as an Administrator in the channel.",
            parse_mode=ParseMode.HTML,
        )
        try:
            await client.disconnect()
        except Exception:
            pass
        if runtime_session_file.exists():
            try:
                runtime_session_file.unlink()
            except Exception:
                pass
        return

    # Determine channel's latest message if end_id not specified
    if end_id is None:
        if not using_bot_mtproto:
            latest_channel_id = 0
            async for m in client.iter_messages(channel, limit=1):
                latest_channel_id = m.id
                break
            end_id = latest_channel_id
        else:
            await status_msg.edit_text(
                "📌 <b>Please specify the end message ID or forward the latest file from the channel and reply with <code>/index</code>.</b>",
                parse_mode=ParseMode.HTML,
            )
            await client.disconnect()
            return

    total_target = max(1, end_id - start_id + 1)

    # Set active indexing state
    context.bot_data["is_indexing"] = True
    context.bot_data["cancel_indexing"] = False
    context.bot_data["indexing_task"] = asyncio.current_task()

    new_indexed = 0
    skipped_count = 0
    total_scanned = 0
    start_time = time.time()
    last_edit_time = time.time()
    cancelled = False
    current_mid = start_id

    async def _process_mtproto_message(
        msg,
        db,
        existing_ids: Set[int],
        existing_signatures: Set[Tuple[str, int]],
        existing_unique_ids: Set[str],
    ) -> None:
        nonlocal current_mid, total_scanned, skipped_count, new_indexed, last_edit_time
        if not msg or getattr(msg, "empty", False):
            return
        current_mid = msg.id
        total_scanned += 1

        if msg.id in existing_ids:
            skipped_count += 1
        elif getattr(msg, "file", None):
            raw_name = msg.file.name or getattr(msg, "text", "") or ""
            clean_name = smart_clean_filename(raw_name)
            file_size = msg.file.size or 0
            doc_obj = getattr(getattr(msg, "media", None), "document", None)
            doc_uid = f"tgdoc_{doc_obj.id}" if doc_obj and getattr(doc_obj, "id", None) else f"unique_{target_channel_id}_{msg.id}"
            sig = (clean_name.lower(), file_size)

            # Skip if this exact file (by Telegram document ID or filename + size) is already indexed
            if (
                doc_uid in existing_unique_ids
                or (clean_name and clean_name != "Media File" and file_size > 0 and sig in existing_signatures)
            ):
                skipped_count += 1
                existing_ids.add(msg.id)
            else:
                file_type = "video" if getattr(msg, "video", None) else ("audio" if getattr(msg, "audio", None) else "document")
                file_code = secrets.token_urlsafe(10)[:10]

                await db.execute(
                    """
                    INSERT INTO files (
                        file_code, file_id, file_unique_id, file_type, file_name,
                        file_size, caption, source_chat_id, source_message_id, uploaded_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        file_code,
                        f"mtproto_{target_channel_id}_{msg.id}",
                        doc_uid,
                        file_type,
                        clean_name,
                        file_size,
                        getattr(msg, "text", "") or "",
                        target_channel_id,
                        msg.id,
                        user.id,
                    ),
                )
                new_indexed += 1
                existing_ids.add(msg.id)
                existing_unique_ids.add(doc_uid)
                if clean_name and clean_name != "Media File" and file_size > 0:
                    existing_signatures.add(sig)

                if new_indexed % 50 == 0:
                    await db.commit()

        now = time.time()
        if now - last_edit_time >= 2.5:
            elapsed = now - start_time
            speed = new_indexed / elapsed if elapsed > 0 else 0
            progress_pct = min(100.0, ((current_mid - start_id + 1) / total_target) * 100) if total_target > 0 else 0
            try:
                await status_msg.edit_text(
                    f"⚡ <b>Fast MTProto Indexer Active!</b>\n\n"
                    f"• <b>Channel:</b> <code>{target_channel_id}</code>\n"
                    f"• <b>Range:</b> <code>#{start_id:,}</code> → <code>#{end_id:,}</code> ({progress_pct:.1f}%)\n"
                    f"• <b>Current Message:</b> <code>#{current_mid:,}</code>\n"
                    f"• <b>✨ New Files Indexed:</b> <code>{new_indexed:,}</code>\n"
                    f"• <b>🔁 Skipped (Duplicates/Cataloged):</b> <code>{skipped_count:,}</code>\n"
                    f"• <b>🚀 Speed:</b> <code>{speed:.1f} files/sec</code>\n\n"
                    f"🛡️ <i>Zero messages sent to channel. Auto-skipping duplicate files.</i>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=stop_keyboard,
                )
                last_edit_time = now
            except telegram.error.RetryAfter as r:
                last_edit_time = now + r.retry_after
            except Exception:
                pass

    try:
        async with aiosqlite.connect(str(DATABASE_PATH)) as db:
            await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA synchronous = NORMAL;")

            # Load existing IDs in range to avoid duplicates
            async with db.execute(
                "SELECT source_message_id FROM files WHERE source_chat_id = ? AND source_message_id BETWEEN ? AND ?;",
                (target_channel_id, start_id, end_id),
            ) as cur:
                rows = await cur.fetchall()
                existing_ids: Set[int] = {r[0] for r in rows if r[0] is not None}

            # Load existing (lower(file_name), file_size) and file_unique_id across entire catalog to prevent duplicate files
            async with db.execute(
                "SELECT LOWER(file_name), file_size, file_unique_id FROM files WHERE file_name IS NOT NULL;"
            ) as cur:
                sig_rows = await cur.fetchall()
                existing_signatures: Set[Tuple[str, int]] = {
                    (r[0], r[1]) for r in sig_rows if r[0] and r[0] != "media file" and (r[1] or 0) > 0
                }
                existing_unique_ids: Set[str] = {
                    r[2] for r in sig_rows if r[2] and not str(r[2]).startswith("unique_")
                }

            if not using_bot_mtproto:
                iter_kwargs = {
                    "min_id": max(0, start_id - 1),
                    "reverse": True,
                }
                if end_id:
                    iter_kwargs["max_id"] = end_id + 1

                async for msg in client.iter_messages(channel, **iter_kwargs):
                    if context.bot_data.get("cancel_indexing"):
                        cancelled = True
                        break
                    await _process_mtproto_message(msg, db, existing_ids, existing_signatures, existing_unique_ids)
            else:
                # Bot MTProto mode: fetch messages by ID in batches of 100
                batch_size = 100
                for batch_start in range(start_id, end_id + 1, batch_size):
                    if context.bot_data.get("cancel_indexing"):
                        cancelled = True
                        break
                    batch_ids = list(range(batch_start, min(end_id + 1, batch_start + batch_size)))
                    msgs = await client.get_messages(channel, ids=batch_ids)
                    if not isinstance(msgs, list):
                        msgs = [msgs]
                    for msg in msgs:
                        if context.bot_data.get("cancel_indexing"):
                            cancelled = True
                            break
                        await _process_mtproto_message(msg, db, existing_ids, existing_signatures, existing_unique_ids)

            await db.commit()

    except asyncio.CancelledError:
        cancelled = True
    except errors.FloodWaitError as fw:
        logger.warning("Telegram MTProto FloodWait: %s seconds", fw.seconds)
        cancelled = True
    except Exception as e:
        logger.error("Error during fast indexing: %s", e, exc_info=True)
    finally:
        context.bot_data["is_indexing"] = False
        context.bot_data["cancel_indexing"] = False
        context.bot_data["indexing_task"] = None
        try:
            await client.disconnect()
        except Exception:
            pass
        if runtime_session_file.exists():
            try:
                runtime_session_file.unlink()
            except Exception:
                pass

    elapsed_total = time.time() - start_time
    avg_speed = new_indexed / elapsed_total if elapsed_total > 0 else 0

    if cancelled:
        await status_msg.edit_text(
            f"🛑 <b>Fast Indexing Stopped by Administrator!</b>\n\n"
            f"• <b>Channel:</b> <code>{target_channel_id}</code>\n"
            f"• <b>✨ Files Saved:</b> <code>{new_indexed:,}</code>\n"
            f"• <b>🔁 Already in Catalog:</b> <code>{skipped_count:,}</code>\n"
            f"• <b>Stopped at Message:</b> <code>#{current_mid:,}</code>\n"
            f"• <b>⏱️ Duration:</b> <code>{elapsed_total:.1f}s</code> ({avg_speed:.1f} files/sec)\n\n"
            f"All progress indexed before stopping is safely saved in the database.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await status_msg.edit_text(
            f"🎉 <b>Fast Channel Indexing Complete!</b>\n\n"
            f"• <b>Channel:</b> <code>{target_channel_id}</code>\n"
            f"• <b>Range Scanned:</b> <code>#{start_id:,}</code> to <code>#{end_id:,}</code> ({total_scanned:,} messages)\n"
            f"• <b>✨ New Files Indexed:</b> <code>{new_indexed:,}</code>\n"
            f"• <b>🔁 Skipped Existing:</b> <code>{skipped_count:,}</code>\n"
            f"• <b>⏱️ Time Taken:</b> <code>{elapsed_total:.1f}s</code> ({avg_speed:.1f} files/sec)\n\n"
            f"Use <code>/stats</code> to view total catalog.",
            parse_mode=ParseMode.HTML,
        )


async def fast_index_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle click on '⚡ Index Channel (Up to #msg_id)' inline button."""
    query = update.callback_query
    if not query or not query.data:
        return

    user = update.effective_user
    if not user or not is_admin(user.id):
        await query.answer("⛔ Only administrators can index channels.", show_alert=True)
        return

    # Format: fastidx_<channel_id>_<end_id>
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.answer("❌ Invalid callback data.", show_alert=True)
        return

    try:
        target_channel_id = int(parts[1])
        target_end_id = int(parts[2])
    except ValueError:
        await query.answer("❌ Invalid channel or message ID.", show_alert=True)
        return

    await query.answer("⚡ Starting Fast MTProto Indexer...")
    context.bot_data["_override_index_target"] = (target_channel_id, target_end_id)
    await fast_index_command(update, context)

