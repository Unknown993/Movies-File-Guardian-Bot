"""
Extended commands module:
- /ping: Bot latency and uptime check
- /settings: Interactive bot & group settings panel
- /logs: Recent bot runtime logs
- /connect, /disconnect, /connections: PM connection management
- /delete, /deleteall: File deletion from catalog
- /imdb, /imbd: IMDb movie & series information lookup
- /users: Registered user list
- /index: Channel media indexing
- /leave: Command bot to leave a chat
- /disable, /enable: Chat disabling & enabling
- /ban_user, /unban_user: Bot-level user banning
- /channel: Connected channel list
- /clear_junk, /clear_junk_group: Database cleanup of dead users/groups
"""

from __future__ import annotations

import os
import re
import json
import time
import html
import asyncio
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.constants import ParseMode, ChatMemberStatus, ChatType, ChatAction
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest, Forbidden

from config import (
    DEVELOPER_ID,
    STORAGE_CHANNEL_ID,
    AUTH_CHANNEL_ID,
    DeliveryMode,
    is_developer,
    is_admin,
)
from database import Database
from handlers.file_handlers import extract_media_details

logger = logging.getLogger(__name__)

# Start timestamp for uptime
BOT_START_TIME = time.time()


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable days, hours, minutes, seconds."""
    secs = int(seconds)
    days = secs // 86400
    hours = (secs % 86400) // 3600
    minutes = (secs % 3600) // 60
    s = secs % 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{s}s")
    return " ".join(parts)


# =============================================================================
# 1. /ping
# =============================================================================

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check bot response time and uptime: /ping."""
    message = update.effective_message
    if not message:
        return

    start_time = time.time()
    temp_msg = await message.reply_text("🏓 **Pinging...**", parse_mode=ParseMode.MARKDOWN)
    latency_ms = round((time.time() - start_time) * 1000, 2)
    uptime_str = format_uptime(time.time() - BOT_START_TIME)

    await temp_msg.edit_text(
        f"🏓 **Pong!**\n\n"
        f"⚡ **Latency:** `{latency_ms} ms`\n"
        f"⏰ **Uptime:** `{uptime_str}`",
        parse_mode=ParseMode.MARKDOWN,
    )


# =============================================================================
# 2. /settings
# =============================================================================

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display interactive settings menu: /settings."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    curr_mode = await db.get_delivery_mode()
    timer = await db.get_auto_delete_seconds()
    welcome_enabled = await db.get_chat_welcome(chat.id) if chat else True
    paywall_on = await db.is_paywall_enabled()

    text = (
        "⚙️ **Bot & Chat Configuration Panel**\n\n"
        f"• **Delivery Strategy:** `{curr_mode.value.upper()}`\n"
        f"• **Auto-Delete Timer:** `{timer}s`\n"
        f"• **Paid-Only Paywall:** `{'🔒 ON (Paid Only)' if paywall_on else '🟢 OFF (Free Access)'}`\n"
        f"• **Welcome Greetings:** `{'ON' if welcome_enabled else 'OFF'}`\n"
        f"• **Force Sub Channel:** `{'Configured' if AUTH_CHANNEL_ID else 'Disabled'}`\n"
        f"• **Storage Channel:** `{'Configured' if STORAGE_CHANNEL_ID else 'Not set'}`"
    )

    buttons = []
    if is_developer(user.id):
        m1_btn = "🔒 Set Mode 1 (View Only)" if curr_mode != DeliveryMode.VIEW_ONLY else "✅ Mode 1 Active"
        m2_btn = "⏱️ Set Mode 2 (Downloadable)" if curr_mode != DeliveryMode.DOWNLOADABLE else "✅ Mode 2 Active"
        buttons.append([InlineKeyboardButton(m1_btn, callback_data="set_mode_view_only")])
        buttons.append([InlineKeyboardButton(m2_btn, callback_data="set_mode_downloadable")])

    if is_admin(user.id):
        pw_btn = "🟢 Disable Paywall (Make Free)" if paywall_on else "🔒 Enable Paywall (Paid Only)"
        buttons.append([InlineKeyboardButton(pw_btn, callback_data="st_paywall_toggle")])

    if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        w_text = "❌ Turn Off Welcome" if welcome_enabled else "✅ Turn On Welcome"
        w_val = "off" if welcome_enabled else "on"
        buttons.append([InlineKeyboardButton(w_text, callback_data=f"st_welcome_{w_val}_{chat.id}")])

    buttons.append([InlineKeyboardButton("🔄 Refresh Status", callback_data="admin_refresh_status")])

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings inline toggle callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    db: Database = context.bot_data["db"]

    if data == "st_paywall_toggle":
        if not is_admin(query.from_user.id):
            await query.answer("Admin permission required.", show_alert=True)
            return
        curr = await db.is_paywall_enabled()
        new_val = not curr
        await db.set_paywall_enabled(new_val)
        await query.answer(f"Paywall is now {'LOCKED (Paid Only)' if new_val else 'OPEN (Free Access)'}", show_alert=True)
        try:
            curr_mode = await db.get_delivery_mode()
            timer = await db.get_auto_delete_seconds()
            chat = query.message.chat if query.message else None
            welcome_enabled = await db.get_chat_welcome(chat.id) if chat else True
            text = (
                "⚙️ **Bot & Chat Configuration Panel**\n\n"
                f"• **Delivery Strategy:** `{curr_mode.value.upper()}`\n"
                f"• **Auto-Delete Timer:** `{timer}s`\n"
                f"• **Paid-Only Paywall:** `{'🔒 ON (Paid Only)' if new_val else '🟢 OFF (Free Access)'}`\n"
                f"• **Welcome Greetings:** `{'ON' if welcome_enabled else 'OFF'}`\n"
                f"• **Force Sub Channel:** `{'Configured' if AUTH_CHANNEL_ID else 'Disabled'}`\n"
                f"• **Storage Channel:** `{'Configured' if STORAGE_CHANNEL_ID else 'Not set'}`"
            )
            buttons = []
            if is_developer(query.from_user.id):
                m1_btn = "🔒 Set Mode 1 (View Only)" if curr_mode != DeliveryMode.VIEW_ONLY else "✅ Mode 1 Active"
                m2_btn = "⏱️ Set Mode 2 (Downloadable)" if curr_mode != DeliveryMode.DOWNLOADABLE else "✅ Mode 2 Active"
                buttons.append([InlineKeyboardButton(m1_btn, callback_data="set_mode_view_only")])
                buttons.append([InlineKeyboardButton(m2_btn, callback_data="set_mode_downloadable")])
            if is_admin(query.from_user.id):
                pw_btn = "🟢 Disable Paywall (Make Free)" if new_val else "🔒 Enable Paywall (Paid Only)"
                buttons.append([InlineKeyboardButton(pw_btn, callback_data="st_paywall_toggle")])
            if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                w_text = "❌ Turn Off Welcome" if welcome_enabled else "✅ Turn On Welcome"
                w_val = "off" if welcome_enabled else "on"
                buttons.append([InlineKeyboardButton(w_text, callback_data=f"st_welcome_{w_val}_{chat.id}")])
            buttons.append([InlineKeyboardButton("🔄 Refresh Status", callback_data="admin_refresh_status")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    elif data in ("st_paywall_on", "st_paywall_off"):
        if not is_admin(query.from_user.id):
            await query.answer("Admin permission required.", show_alert=True)
            return
        new_val = (data == "st_paywall_on")
        await db.set_paywall_enabled(new_val)
        await query.answer(f"Paywall is now {'LOCKED (Paid Only)' if new_val else 'OPEN (Free Access)'}", show_alert=True)
        try:
            status_text = "🔒 **ON (Paid Members Only)**" if new_val else "🟢 **OFF (Free Access for All)**"
            buttons = [
                [
                    InlineKeyboardButton("Turn ON 🔒", callback_data="st_paywall_on"),
                    InlineKeyboardButton("Turn OFF 🟢", callback_data="st_paywall_off"),
                ],
                [InlineKeyboardButton("📊 View Premium Users", callback_data="st_view_premiums")],
            ]
            await query.edit_message_text(
                f"🛡️ **Paywall Access Control**\n\n"
                f"**Current State:** {status_text}\n\n"
                f"When **ON**, users without an active paid subscription cannot search or receive files.\n"
                f"When **OFF**, anyone can freely search and receive files.",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    elif data == "st_view_premiums":
        if not is_admin(query.from_user.id):
            await query.answer("Admin permission required.", show_alert=True)
            return
        subs = await db.get_all_active_subscriptions()
        await query.answer(f"Total active subscribers: {len(subs)}", show_alert=True)

    elif data.startswith("st_welcome_"):
        parts = data.split("_")
        action, chat_id = parts[2], int(parts[3])
        new_val = (action == "on")
        await db.set_chat_welcome(chat_id, new_val)
        await query.answer(f"Welcome messages set to {action.upper()}")
        try:
            w_text = "❌ Turn Off Welcome" if new_val else "✅ Turn On Welcome"
            w_val = "off" if new_val else "on"
            curr_mode = await db.get_delivery_mode()
            timer = await db.get_auto_delete_seconds()
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 Mode 1 (View Only)", callback_data="set_mode_view_only")],
                [InlineKeyboardButton("⏱️ Mode 2 (Downloadable)", callback_data="set_mode_downloadable")],
                [InlineKeyboardButton(w_text, callback_data=f"st_welcome_{w_val}_{chat_id}")],
                [InlineKeyboardButton("🔄 Refresh Status", callback_data="admin_refresh_status")],
            ])
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            pass


# =============================================================================
# 3. /logs
# =============================================================================

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send recent runtime logs: /logs."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    from config import BASE_DIR
    log_path = str(BASE_DIR / "bot.log")
    if not os.path.exists(log_path):
        await message.reply_text("📋 No log file found (<code>bot.log</code>). Logging directly to console.", parse_mode=ParseMode.HTML)
        return

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        recent = lines[-50:] if len(lines) > 50 else lines
        text = "".join(recent).strip()
        escaped_text = html.escape(text)

        if len(escaped_text) < 3800:
            await message.reply_text(
                f"📋 <b>Recent Logs (Last {len(recent)} lines):</b>\n\n<pre>{escaped_text}</pre>",
                parse_mode=ParseMode.HTML,
            )
        else:
            with open(log_path, "rb") as log_file:
                await message.reply_document(document=log_file, caption="📋 Full runtime log file.")
    except Exception as e:
        await message.reply_text(f"❌ Error reading logs: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


# =============================================================================
# 4. /connect, /disconnect, /connections
# =============================================================================

async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Connect a group to user PM: /connect [group_id]."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return

    target_chat_id: Optional[int] = None
    db: Database = context.bot_data["db"]

    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_id = chat.id
    elif chat.type == ChatType.PRIVATE:
        args = context.args or []
        if not args:
            await message.reply_text(
                "📌 **Usage in Private DM:** `/connect <group_id>`\n\n"
                "Get your Group ID by typing `/id` inside your group.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            target_chat_id = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid Group ID format.", parse_mode=ParseMode.MARKDOWN)
            return

    # Verify user is admin in that group
    try:
        member = await context.bot.get_chat_member(chat_id=target_chat_id, user_id=user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER] and not is_admin(user.id):
            await message.reply_text("⛔ You must be an administrator in that group to connect.", parse_mode=ParseMode.MARKDOWN)
            return
    except Exception as e:
        await message.reply_text(
            f"❌ Could not verify group membership. Make sure the bot is in that group.\nError: <code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_chat = await context.bot.get_chat(target_chat_id)
        chat_title = target_chat.title or str(target_chat_id)
    except Exception:
        chat_title = str(target_chat_id)

    added = await db.add_connection(user.id, target_chat_id)
    safe_title = html.escape(chat_title)
    if added:
        await message.reply_text(
            f"✅ Successfully connected to <b>{safe_title}</b>!\nYou can now manage filters and files from PM.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(f"ℹ️ Already connected to <b>{safe_title}</b>.", parse_mode=ParseMode.HTML)


async def disconnect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disconnect from a chat: /disconnect [chat_id]."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return

    db: Database = context.bot_data["db"]
    target_chat_id: Optional[int] = None

    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_id = chat.id
    elif chat.type == ChatType.PRIVATE:
        args = context.args or []
        if args and args[0].lstrip("-").isdigit():
            target_chat_id = int(args[0])
        else:
            await message.reply_text("Run `/connections` to view your connected groups.", parse_mode=ParseMode.MARKDOWN)
            return

    deleted = await db.delete_connection(user.id, target_chat_id)
    if deleted:
        await message.reply_text("✅ Successfully disconnected.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply_text("❌ Not connected to this chat.", parse_mode=ParseMode.MARKDOWN)


async def connections_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all connected chats with interactive management buttons: /connections."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    chat_ids = await db.get_user_connections(user.id)
    if not chat_ids:
        await message.reply_text("📭 You have no active group connections.\nUse `/connect <group_id>` to connect.", parse_mode=ParseMode.MARKDOWN)
        return

    buttons = []
    lines = ["🔗 **Your Connected Groups:**\n\n*Tap any group to manage connection, disconnect, or delete:*"]
    for cid in chat_ids:
        try:
            c = await context.bot.get_chat(cid)
            title = c.title or str(cid)
        except Exception:
            title = f"Group {cid}"
        buttons.append([InlineKeyboardButton(f"👥 {title}", callback_data=f"conn_view_{cid}")])

    buttons.append([InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close")])

    await message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def connection_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle interactive connection management callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    user = update.effective_user
    db: Database = context.bot_data["db"]

    if data.startswith("conn_view_"):
        cid = int(data.split("_")[2])
        try:
            c = await context.bot.get_chat(cid)
            title = c.title or str(cid)
        except Exception:
            title = str(cid)

        text = f"👥 <b>Group:</b> <code>{html.escape(title)}</code>\n🆔 <b>Group ID:</b> <code>{cid}</code>\n\n<i>Select an action below:</i>"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ Disconnect", callback_data=f"conn_dis_{cid}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"conn_del_{cid}"),
            ],
            [InlineKeyboardButton("« Back", callback_data="conn_back")]
        ])
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data.startswith("conn_dis_"):
        cid = int(data.split("_")[2])
        await db.delete_connection(user.id, cid)
        await query.answer("Disconnected from group!", show_alert=True)
        await _show_connections_menu(query, context, user.id, db)

    elif data.startswith("conn_del_"):
        cid = int(data.split("_")[2])
        await db.delete_connection(user.id, cid)
        await query.answer("Connection deleted!", show_alert=True)
        await _show_connections_menu(query, context, user.id, db)

    elif data == "conn_back":
        await _show_connections_menu(query, context, user.id, db)
        await query.answer()


async def _show_connections_menu(query, context, user_id: int, db: Database) -> None:
    """Helper to display the refreshed connections menu."""
    chat_ids = await db.get_user_connections(user_id)
    if not chat_ids:
        try:
            await query.edit_message_text("📭 You have no active group connections.\nUse `/connect <group_id>` to connect.", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        return

    buttons = []
    lines = ["🔗 **Your Connected Groups:**\n\n*Tap any group to manage connection, disconnect, or delete:*"]
    for cid in chat_ids:
        try:
            c = await context.bot.get_chat(cid)
            title = c.title or str(cid)
        except Exception:
            title = f"Group {cid}"
        buttons.append([InlineKeyboardButton(f"👥 {title}", callback_data=f"conn_view_{cid}")])

    buttons.append([InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close")])
    try:
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


# =============================================================================
# 5. /delete & /deleteall
# =============================================================================

async def delete_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a specific file from the catalog: /delete [code or reply to media]."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    file_code: Optional[str] = None

    if message.reply_to_message:
        replied = message.reply_to_message
        media_info = extract_media_details(replied)
        if media_info:
            _, f_uid, _, _, _ = media_info
            if f_uid:
                rec = await db.get_file_by_unique_id(f_uid)
                if rec:
                    file_code = rec["file_code"]
        if not file_code and replied.chat_id and replied.message_id:
            rec = await db.get_file_by_source_message(replied.chat_id, replied.message_id)
            if rec:
                file_code = rec["file_code"]

    if not file_code and context.args:
        file_code = context.args[0].strip().removeprefix("file_")

    if not file_code:
        await message.reply_text(
            "📌 **Usage:** Reply to a file with `/delete` or type `/delete <file_code>`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    deleted = await db.delete_file_by_code(file_code)
    if deleted:
        await message.reply_text(f"🗑️ File `{file_code}` deleted from database.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply_text(f"❌ File `{file_code}` not found in database.", parse_mode=ParseMode.MARKDOWN)


async def deleteall_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete all indexed files (Developer only): /deleteall."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not is_developer(user.id):
        await message.reply_text("⛔ Only the primary bot developer can wipe the file catalog.", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    deleted_count = await db.delete_all_files()
    await message.reply_text(f"🗑️ Catalog purged: Deleted `{deleted_count}` files from database.", parse_mode=ParseMode.MARKDOWN)


# =============================================================================
# 6. /imdb (and /imbd)
# =============================================================================

async def imdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch movie/series information from IMDb: /imdb <title>."""
    message = update.effective_message
    if not message:
        return

    args = context.args or []
    if not args:
        await message.reply_text("📌 **Usage:** `/imdb <movie or series name>`\nExample: `/imdb Inception`", parse_mode=ParseMode.MARKDOWN)
        return

    query_str = " ".join(args).strip()
    status_msg = await message.reply_text(
        f"🔍 Searching IMDb for <b>\"{html.escape(query_str)}\"</b>...",
        parse_mode=ParseMode.HTML,
    )

    encoded = urllib.parse.quote(query_str.lower())
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{encoded}.json"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.warning("IMDb lookup error for %s: %s", query_str, e)
        await status_msg.edit_text("❌ Could not connect to IMDb. Try again later.")
        return

    results = data.get("d", [])
    if not results:
        await status_msg.edit_text(
            f"❌ No IMDb results found for <b>\"{html.escape(query_str)}\"</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Pick the top result
    top = results[0]
    title = top.get("l", query_str)
    year = top.get("y", "Unknown")
    actors = top.get("s", "Not listed")
    media_type = top.get("qid", top.get("q", "feature")).capitalize()
    imdb_id = top.get("id", "")
    imdb_url = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "https://www.imdb.com"

    poster_info = top.get("i")
    poster_url = poster_info.get("imageUrl") if poster_info else None

    caption = (
        f"🎬 <b>{html.escape(str(title))}</b> ({html.escape(str(year))})\n\n"
        f"🏷️ <b>Type:</b> {html.escape(str(media_type))}\n"
        f"👥 <b>Cast:</b> {html.escape(str(actors))}\n"
        f"🆔 <b>IMDb ID:</b> <code>{html.escape(str(imdb_id))}</code>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ View on IMDb", url=imdb_url)]
    ])

    await status_msg.delete()

    if poster_url:
        try:
            await message.reply_photo(
                photo=poster_url,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception:
            pass

    await message.reply_text(
        caption,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 7. /users
# =============================================================================

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get list of registered bot users: /users."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    users = await db.get_all_users_details()
    if not users:
        await message.reply_text("📭 No registered users found.", parse_mode=ParseMode.MARKDOWN)
        return

    lines = [f"👥 <b>Registered Bot Users ({len(users)}):</b>\n"]
    plain_lines = [f"Registered Bot Users ({len(users)}):\n"]
    for i, u in enumerate(users, 1):
        raw_name = u.get("first_name") or "User"
        raw_uname = f"@{u['username']}" if u.get("username") else "No username"
        safe_name = html.escape(raw_name)
        safe_uname = html.escape(raw_uname)
        lines.append(
            f"{i}. <a href='tg://user?id={u['user_id']}'>{safe_name}</a> - <code>{u['user_id']}</code> ({safe_uname})"
        )
        plain_lines.append(f"{i}. {raw_name} - {u['user_id']} ({raw_uname})")

    out_text = "\n".join(lines)
    if len(out_text) < 4000:
        await message.reply_text(out_text, parse_mode=ParseMode.HTML)
    else:
        filename = "users_list.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(plain_lines))
        with open(filename, "rb") as doc_file:
            await message.reply_document(document=doc_file, caption=f"👥 Total Users: {len(users)}")
        try:
            os.remove(filename)
        except Exception:
            pass


# =============================================================================
# 8. /index (Channel media indexing command)
# =============================================================================

async def index_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Channel media indexing command: /index [start_id] [end_id].
    Delegates directly to the high-speed MTProto indexer:
    - Never posts to the storage channel
    - Never forwards or cleans up messages in PM
    - Pure, silent database indexing with live progress card in chat
    """
    from handlers.fast_index_handlers import fast_index_command
    await fast_index_command(update, context)


# =============================================================================
# 9. /leave
# =============================================================================

async def leave_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command bot to leave a chat: /leave [chat_id]."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or not is_admin(user.id):
        return

    args = context.args or []
    if args and args[0].lstrip("-").isdigit():
        target_chat_id = int(args[0])
    elif chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_id = chat.id
    else:
        await message.reply_text(
            "📌 <b>Usage in Private DM:</b> <code>/leave &lt;chat_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await context.bot.send_message(
            chat_id=target_chat_id,
            text="👋 <b>Goodbye!</b> My admin has requested me to leave this chat.",
            parse_mode=ParseMode.HTML,
        )
        await context.bot.leave_chat(chat_id=target_chat_id)
        if target_chat_id != chat.id:
            await message.reply_text(f"✅ Successfully left chat <code>{target_chat_id}</code>.", parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ Failed to leave chat: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


# =============================================================================
# 10. /disable & /enable
# =============================================================================

async def disable_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable a chat and make bot leave: /disable <chat_id> [reason]."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or not is_admin(user.id):
        return

    args = context.args or []
    if not args:
        if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await message.reply_text(
                "📌 <b>Usage:</b> <code>/disable &lt;chat_id&gt; [reason]</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        target_chat_id = chat.id
        reason = "Disabled by Administrator"
    else:
        try:
            target_chat_id = int(args[0])
            reason = " ".join(args[1:]).strip() or "Disabled by Administrator"
        except ValueError:
            await message.reply_text("📌 <b>Usage:</b> <code>/disable &lt;chat_id&gt; [reason]</code>", parse_mode=ParseMode.HTML)
            return

    db: Database = context.bot_data["db"]
    await db.disable_chat(target_chat_id, reason)
    safe_reason = html.escape(reason)

    try:
        await context.bot.send_message(
            chat_id=target_chat_id,
            text=f"🚫 <b>Chat Disabled</b>\n\nThis chat has been disabled by bot administrators.\nReason: <code>{safe_reason}</code>",
            parse_mode=ParseMode.HTML,
        )
        await context.bot.leave_chat(chat_id=target_chat_id)
    except Exception:
        pass

    await message.reply_text(f"🔒 Chat <code>{target_chat_id}</code> disabled: <code>{safe_reason}</code>", parse_mode=ParseMode.HTML)


async def enable_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-enable a chat: /enable <chat_id>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await message.reply_text("Usage: `/enable <chat_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    target_chat_id = int(args[0])
    db: Database = context.bot_data["db"]
    enabled = await db.enable_chat(target_chat_id)
    if enabled:
        await message.reply_text(f"🔓 Chat `{target_chat_id}` re-enabled successfully.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply_text(f"ℹ️ Chat `{target_chat_id}` was not disabled or not found in database.", parse_mode=ParseMode.MARKDOWN)


# =============================================================================
# 11. /ban_user & /unban_user
# =============================================================================

async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban a user from using the bot: /ban_user <user_id|reply> [reason]."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    target_id: Optional[int] = None
    reason: str = "Violating bot usage policies"

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        if context.args:
            reason = " ".join(context.args)
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])
        if len(context.args) > 1:
            reason = " ".join(context.args[1:])

    if not target_id:
        await message.reply_text("📌 <b>Usage:</b> Reply to a user or type <code>/ban_user &lt;user_id&gt; [reason]</code>", parse_mode=ParseMode.HTML)
        return

    db: Database = context.bot_data["db"]
    await db.ban_user(target_id, reason)
    await message.reply_text(
        f"🔨 User <code>{target_id}</code> banned from bot.\nReason: <code>{html.escape(reason)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a user: /unban_user <user_id|reply>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    target_id: Optional[int] = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])

    if not target_id:
        await message.reply_text("Usage: Reply to a user or type `/unban_user <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    unbanned = await db.unban_user(target_id)
    if unbanned:
        await message.reply_text(f"✅ User `{target_id}` unbanned.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply_text(f"ℹ️ User `{target_id}` was not banned.", parse_mode=ParseMode.MARKDOWN)


# =============================================================================
# 12. /channel
# =============================================================================

async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get list of connected storage channels: /channel."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    channels = await db.get_indexed_channels()
    if STORAGE_CHANNEL_ID and STORAGE_CHANNEL_ID not in channels:
        channels.append(STORAGE_CHANNEL_ID)

    if not channels:
        await message.reply_text("📭 No storage channels currently connected.", parse_mode=ParseMode.MARKDOWN)
        return

    lines = ["📑 <b>Connected Storage Channels:</b>\n"]
    for cid in channels:
        try:
            c = await context.bot.get_chat(cid)
            lines.append(f"• <b>{html.escape(c.title or str(cid))}</b> (<code>{cid}</code>)")
        except Exception:
            lines.append(f"• Channel ID: <code>{cid}</code>")

    lines.append(f"\n<b>Total Channels:</b> <code>{len(channels)}</code>")
    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# =============================================================================
# 13. /clear_junk & /clear_junk_group
# =============================================================================

async def clear_junk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove deleted or blocked users from the database: /clear_junk."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    user_ids = await db.get_all_users()
    if not user_ids:
        await message.reply_text("📭 No users in database to clean.", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await message.reply_text(f"🧹 Scanning `{len(user_ids)}` users for dead accounts...", parse_mode=ParseMode.MARKDOWN)

    cleaned = 0
    active = 0

    for uid in user_ids:
        try:
            await context.bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)
            active += 1
        except (Forbidden, BadRequest):
            # User blocked bot or account deleted
            await db.delete_user(uid)
            cleaned += 1
        except Exception:
            active += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"🧹 **User Cleanup Complete!**\n\n"
        f"• Total Checked: `{len(user_ids)}`\n"
        f"• Active Users: `{active}`\n"
        f"• Dead/Blocked Removed: `{cleaned}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def clear_junk_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove deleted or unreachable groups from the database: /clear_junk_group."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    chats = await db.get_all_chats()
    if not chats:
        await message.reply_text("📭 No groups in database to clean.", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await message.reply_text(f"🧹 Scanning `{len(chats)}` groups for removed entries...", parse_mode=ParseMode.MARKDOWN)

    cleaned = 0
    active = 0

    for c in chats:
        cid = c["chat_id"]
        try:
            member = await context.bot.get_chat_member(chat_id=cid, user_id=context.bot.id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]:
                await db.delete_chat(cid)
                cleaned += 1
            else:
                active += 1
        except Exception:
            await db.delete_chat(cid)
            cleaned += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"🧹 **Group Cleanup Complete!**\n\n"
        f"• Total Checked: `{len(chats)}`\n"
        f"• Active Groups: `{active}`\n"
        f"• Removed Groups Cleaned: `{cleaned}`",
        parse_mode=ParseMode.MARKDOWN,
    )
