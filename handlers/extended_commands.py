"""
Extended commands module:
- /ping, /alive: Bot latency and uptime check
- /settings: Interactive 8-row group settings & bot configuration panel
- /details, /reset_group, /resetallgroup, /reload: Group settings inspection & reset
- /set_caption, /set_fsub, /remove_fsub, /set_log_channel: Group customization commands
- /pm_search, /movie_update, /del_msg: Bot-level toggles & search history reset
- /top_search, /trendlist: Interactive top trending searches
- /send: Admin direct message relay to a user
- /delete, /deletefiles, /deleteall: Single, keyword-bulk, and full catalog file deletion
- /request (#request): User movie request system with interactive admin status buttons
- /admin_cmd, /group_cmd: Quick command reference sheets
- /logs: Recent work-related bot runtime logs (filtered of any file-indexing noise)
- /connect, /disconnect, /connections: PM connection management
- /imdb, /imbd: IMDb movie & series information lookup
- /users, /channel, /leave, /disable, /enable, /ban_user, /unban_user, /clear_junk, /clear_junk_group
"""

from __future__ import annotations

import os
import re
import json
import time
import html
import hashlib
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
    REQST_CHANNEL_ID,
    DeliveryMode,
    is_developer,
    is_admin,
    send_work_log,
)
from database import Database
from handlers.file_handlers import extract_media_details
from handlers.filter_handlers import get_query_hash, QUERY_CACHE, build_filter_keyboard, build_filter_result_caption, PAGE_SIZE
from script import Script

logger = logging.getLogger(__name__)

# Start timestamp for uptime
BOT_START_TIME = time.time()

# Temporary cache for /deletefiles keyword confirmation and /request titles
KILLFILES_CACHE: Dict[str, str] = {}
REQUEST_CACHE: Dict[str, str] = {}


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


async def _resolve_admin_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Resolve target group ID (either current group chat or user's active PM connection) and verify admin rights."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return None

    db: Database = context.bot_data["db"]
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if not is_admin(user.id):
            try:
                member = await chat.get_member(user.id)
                if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                    await message.reply_text("⛔ Only group administrators can use this command.", parse_mode=ParseMode.HTML)
                    return None
            except Exception:
                return None
        return chat.id

    active_id = await db.get_active_connection(user.id)
    if not active_id:
        await message.reply_text(
            "ℹ️ Use this command inside a group, or connect your group to PM first using <code>/connect &lt;group_id&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return None
    return active_id


# =============================================================================
# 1. /ping & /alive
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


async def alive_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check bot alive status: /alive."""
    message = update.effective_message
    if not message:
        return
    uptime_str = format_uptime(time.time() - BOT_START_TIME)
    bot_me = await context.bot.get_me()
    await message.reply_text(
        f"🤖 <b>{html.escape(bot_me.first_name or 'Guardian Bot')} Is Alive & Operational! ⚡</b>\n\n"
        f"⏱️ <b>Uptime:</b> <code>{uptime_str}</code>\n"
        f"🛡️ <b>Protection:</b> <code>Active</code>\n"
        f"🗄️ <b>Database:</b> <code>SQLite3 WAL Connected</code>",
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 2. /settings, /details, /reset_group, /resetallgroup, /reload
# =============================================================================

def _build_group_settings_panel(
    chat_id: int,
    chat_title: str,
    grp: Dict[str, Any],
    curr_mode: DeliveryMode,
    timer: int,
    paywall_on: bool,
    user_id: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Build the 8-row interactive group & bot settings panel matching Premium_Guardian."""
    safe_title = html.escape(chat_title or f"Chat {chat_id}")
    text = (
        f"⚙️ <b><u>Gʀᴏᴜᴘ & Bᴏᴛ Sᴇᴛᴛɪɴɢs Pᴀɴᴇʟ</u></b>\n\n"
        f"👥 <b>Gʀᴏᴜᴘ:</b> <code>{safe_title}</code> (<code>{chat_id}</code>)\n"
        f"📦 <b>Dᴇʟɪᴠᴇʀʏ Sᴛʀᴀᴛᴇɢʏ:</b> <code>{curr_mode.value.upper()} ({timer}s)</code>\n"
        f"💳 <b>Pᴀʏᴡᴀʟʟ:</b> <code>{'🔒 ON (Paid Only)' if paywall_on else '🟢 OFF (Free Access)'}</code>\n\n"
        f"👇 <i>Tᴀᴘ ᴀɴʏ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴛᴏɢɢʟᴇ:</i>"
    )

    btn_mode_lbl = "🔘 Bᴜᴛᴛᴏɴ" if grp.get("button", True) else "🔗 Tᴇxᴛ Lɪɴᴋ"
    sec_lbl = "✅ ON" if grp.get("file_secure", True) else "❌ OFF"
    imdb_lbl = "✅ ON" if grp.get("imdb", True) else "❌ OFF"
    spell_lbl = "✅ ON" if grp.get("spell_check", True) else "❌ OFF"
    welc_lbl = "✅ ON" if grp.get("welcome", True) else "❌ OFF"
    adel_lbl = "✅ ON" if grp.get("auto_delete", True) else "❌ OFF"
    maxb_lbl = "10 Fɪʟᴇs" if grp.get("max_btn", True) else "6 Fɪʟᴇs"
    afil_lbl = "✅ ON" if grp.get("auto_ffilter", True) else "❌ OFF"

    rows = [
        [
            InlineKeyboardButton("Rᴇsᴜʟᴛ Mᴏᴅᴇ", callback_data=f"st_grp_button_{chat_id}"),
            InlineKeyboardButton(btn_mode_lbl, callback_data=f"st_grp_button_{chat_id}"),
        ],
        [
            InlineKeyboardButton("Fɪʟᴇ Sᴇᴄᴜʀᴇ", callback_data=f"st_grp_file_secure_{chat_id}"),
            InlineKeyboardButton(sec_lbl, callback_data=f"st_grp_file_secure_{chat_id}"),
        ],
        [
            InlineKeyboardButton("IMDb Pᴏsᴛᴇʀ", callback_data=f"st_grp_imdb_{chat_id}"),
            InlineKeyboardButton(imdb_lbl, callback_data=f"st_grp_imdb_{chat_id}"),
        ],
        [
            InlineKeyboardButton("Sᴘᴇʟʟ Cʜᴇᴄᴋ", callback_data=f"st_grp_spell_check_{chat_id}"),
            InlineKeyboardButton(spell_lbl, callback_data=f"st_grp_spell_check_{chat_id}"),
        ],
        [
            InlineKeyboardButton("Wᴇʟᴄᴏᴍᴇ Msɢ", callback_data=f"st_grp_welcome_{chat_id}"),
            InlineKeyboardButton(welc_lbl, callback_data=f"st_grp_welcome_{chat_id}"),
        ],
        [
            InlineKeyboardButton("Aᴜᴛᴏ Dᴇʟᴇᴛᴇ", callback_data=f"st_grp_auto_delete_{chat_id}"),
            InlineKeyboardButton(adel_lbl, callback_data=f"st_grp_auto_delete_{chat_id}"),
        ],
        [
            InlineKeyboardButton("Mᴀx Bᴜᴛᴛᴏɴs", callback_data=f"st_grp_max_btn_{chat_id}"),
            InlineKeyboardButton(maxb_lbl, callback_data=f"st_grp_max_btn_{chat_id}"),
        ],
        [
            InlineKeyboardButton("Aᴜᴛᴏ Fɪʟᴛᴇʀ", callback_data=f"st_grp_auto_ffilter_{chat_id}"),
            InlineKeyboardButton(afil_lbl, callback_data=f"st_grp_auto_ffilter_{chat_id}"),
        ],
        [
            InlineKeyboardButton("📋 Dᴇᴛᴀɪʟs", callback_data=f"st_grp_details_{chat_id}"),
            InlineKeyboardButton("♻️ Rᴇsᴇᴛ Gʀᴏᴜᴘ", callback_data=f"st_grp_reset_{chat_id}"),
        ],
    ]

    if is_developer(user_id):
        m1_btn = "🔒 Mode 1 (View Only)" if curr_mode != DeliveryMode.VIEW_ONLY else "✅ Mode 1 Active"
        m2_btn = "⏱️ Mode 2 (Downloadable)" if curr_mode != DeliveryMode.DOWNLOADABLE else "✅ Mode 2 Active"
        rows.append([
            InlineKeyboardButton(m1_btn, callback_data="set_mode_view_only"),
            InlineKeyboardButton(m2_btn, callback_data="set_mode_downloadable"),
        ])

    if is_admin(user_id):
        pw_btn = "🟢 Disable Paywall (Make Free)" if paywall_on else "🔒 Enable Paywall (Paid Only)"
        rows.append([InlineKeyboardButton(pw_btn, callback_data="st_paywall_toggle")])

    rows.append([
        InlineKeyboardButton("🔄 Refresh Status", callback_data="admin_refresh_status"),
        InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"),
    ])

    return text, InlineKeyboardMarkup(rows)


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
    paywall_on = await db.is_paywall_enabled()

    target_chat_id = chat.id if chat else 0
    target_title = chat.title if chat and chat.title else "Private / Connected Group"

    if chat and chat.type == ChatType.PRIVATE:
        active_conn = await db.get_active_connection(user.id)
        if active_conn:
            target_chat_id = active_conn
            try:
                c_obj = await context.bot.get_chat(active_conn)
                target_title = c_obj.title or str(active_conn)
            except Exception:
                target_title = f"Group {active_conn}"

    grp = await db.get_group_settings(target_chat_id)
    welcome_enabled = await db.get_chat_welcome(target_chat_id) if target_chat_id else True
    grp["welcome"] = welcome_enabled

    text, markup = _build_group_settings_panel(
        chat_id=target_chat_id,
        chat_title=target_title,
        grp=grp,
        curr_mode=curr_mode,
        timer=timer,
        paywall_on=paywall_on,
        user_id=user.id,
    )

    await message.reply_text(
        text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings inline toggle callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    db: Database = context.bot_data["db"]
    user = query.from_user

    if data == "st_paywall_toggle":
        if not is_admin(user.id):
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
            cid = chat.id if chat else 0
            grp = await db.get_group_settings(cid)
            text, markup = _build_group_settings_panel(
                chat_id=cid,
                chat_title=chat.title if chat and chat.title else "Settings",
                grp=grp,
                curr_mode=curr_mode,
                timer=timer,
                paywall_on=new_val,
                user_id=user.id,
            )
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    elif data in ("st_paywall_on", "st_paywall_off"):
        if not is_admin(user.id):
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
        if not is_admin(user.id):
            await query.answer("Admin permission required.", show_alert=True)
            return
        subs = await db.get_all_active_subscriptions()
        await query.answer(f"Total active subscribers: {len(subs)}", show_alert=True)

    elif data.startswith("st_welcome_"):
        parts = data.split("_")
        action, chat_id = parts[2], int(parts[3])
        new_val = (action == "on")
        await db.set_chat_welcome(chat_id, new_val)
        await db.save_group_settings(chat_id, "welcome", new_val)
        await query.answer(f"Welcome messages set to {action.upper()}")

    elif data.startswith("st_grp_"):
        # Format: st_grp_<key>_<chat_id>
        rem = data.removeprefix("st_grp_")
        last_us = rem.rfind("_")
        if last_us == -1:
            return
        key = rem[:last_us]
        try:
            chat_id = int(rem[last_us + 1:])
        except ValueError:
            return

        grp = await db.get_group_settings(chat_id)
        if key == "details":
            details_txt = (
                f"📋 <b><u>Gʀᴏᴜᴘ Sᴇᴛᴛɪɴɢs Dᴇᴛᴀɪʟs</u></b>\n\n"
                f"🆔 <b>Cʜᴀᴛ ID:</b> <code>{chat_id}</code>\n"
                f"🔘 <b>Rᴇsᴜʟᴛ Mᴏᴅᴇ:</b> <code>{'Button' if grp.get('button', True) else 'Text Link'}</code>\n"
                f"🔐 <b>Fɪʟᴇ Sᴇᴄᴜʀᴇ:</b> <code>{grp.get('file_secure', True)}</code>\n"
                f"🎭 <b>IMDb:</b> <code>{grp.get('imdb', True)}</code>\n"
                f"🔤 <b>Sᴘᴇʟʟ Cʜᴇᴄᴋ:</b> <code>{grp.get('spell_check', True)}</code>\n"
                f"👋 <b>Wᴇʟᴄᴏᴍᴇ:</b> <code>{grp.get('welcome', True)}</code>\n"
                f"🗑️ <b>Aᴜᴛᴏ Dᴇʟᴇᴛᴇ:</b> <code>{grp.get('auto_delete', True)}</code>\n"
                f"📄 <b>Mᴀx Bᴜᴛᴛᴏɴs:</b> <code>{'10' if grp.get('max_btn', True) else '6'}</code>\n"
                f"⚡ <b>Aᴜᴛᴏ Fɪʟᴛᴇʀ:</b> <code>{grp.get('auto_ffilter', True)}</code>\n"
                f"📝 <b>Cᴀᴘᴛɪᴏɴ:</b> <code>{html.escape(str(grp.get('caption') or 'Default'))}</code>\n"
                f"📢 <b>Fᴏʀᴄᴇ Sᴜʙ:</b> <code>{grp.get('fsub') or 'Default'}</code>"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("« Bᴀᴄᴋ Tᴏ Sᴇᴛᴛɪɴɢs", callback_data=f"st_grp_back_{chat_id}")]
            ])
            try:
                await query.edit_message_text(details_txt, reply_markup=markup, parse_mode=ParseMode.HTML)
            except Exception:
                pass
            await query.answer()
            return

        if key == "reset":
            await db.reset_group_settings(chat_id)
            grp = await db.get_group_settings(chat_id)
            await query.answer("♻️ Group settings reset to defaults!", show_alert=True)
        elif key != "back":
            new_bool = not bool(grp.get(key, True))
            await db.save_group_settings(chat_id, key, new_bool)
            if key == "welcome":
                await db.set_chat_welcome(chat_id, new_bool)
            grp[key] = new_bool
            await query.answer(f"✅ Updated {key.replace('_', ' ').title()}!")
        else:
            await query.answer()

        curr_mode = await db.get_delivery_mode()
        timer = await db.get_auto_delete_seconds()
        paywall_on = await db.is_paywall_enabled()
        chat = query.message.chat if query.message else None
        text, markup = _build_group_settings_panel(
            chat_id=chat_id,
            chat_title=chat.title if chat and chat.title else f"Group {chat_id}",
            grp=grp,
            curr_mode=curr_mode,
            timer=timer,
            paywall_on=paywall_on,
            user_id=user.id,
        )
        try:
            await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def details_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View detailed group settings: /details."""
    message = update.effective_message
    if not message:
        return
    target_chat_id = await _resolve_admin_group_id(update, context)
    if not target_chat_id:
        return

    db: Database = context.bot_data["db"]
    grp = await db.get_group_settings(target_chat_id)
    text = (
        f"📋 <b><u>Gʀᴏᴜᴘ Sᴇᴛᴛɪɴɢs Dᴇᴛᴀɪʟs</u></b>\n\n"
        f"🆔 <b>Cʜᴀᴛ ID:</b> <code>{target_chat_id}</code>\n"
        f"🔘 <b>Rᴇsᴜʟᴛ Mᴏᴅᴇ:</b> <code>{'Button Mode' if grp.get('button', True) else 'Text Link Mode'}</code>\n"
        f"🔐 <b>Fɪʟᴇ Sᴇᴄᴜʀᴇ:</b> <code>{grp.get('file_secure', True)}</code>\n"
        f"🎭 <b>IMDb Pᴏsᴛᴇʀ:</b> <code>{grp.get('imdb', True)}</code>\n"
        f"🔤 <b>Sᴘᴇʟʟ Cʜᴇᴄᴋ:</b> <code>{grp.get('spell_check', True)}</code>\n"
        f"👋 <b>Wᴇʟᴄᴏᴍᴇ Msɢ:</b> <code>{grp.get('welcome', True)}</code>\n"
        f"🗑️ <b>Aᴜᴛᴏ Dᴇʟᴇᴛᴇ:</b> <code>{grp.get('auto_delete', True)}</code>\n"
        f"📄 <b>Mᴀx Bᴜᴛᴛᴏɴs:</b> <code>{'10' if grp.get('max_btn', True) else '6'}</code>\n"
        f"⚡ <b>Aᴜᴛᴏ Fɪʟᴛᴇʀ:</b> <code>{grp.get('auto_ffilter', True)}</code>\n"
        f"📝 <b>Cᴜsᴛᴏᴍ Cᴀᴘᴛɪᴏɴ:</b> <code>{html.escape(str(grp.get('caption') or 'Default'))}</code>\n"
        f"🏷 <b>IMDb Tᴇᴍᴘʟᴀᴛᴇ:</b> <code>{html.escape(str(grp.get('template') or 'Default'))}</code>\n"
        f"📢 <b>Fᴏʀᴄᴇ Sᴜʙ IDs:</b> <code>{grp.get('fsub') or 'Default'}</code>\n"
        f"📋 <b>Lᴏɢ Cʜᴀɴɴᴇʟ:</b> <code>{grp.get('log') or 'Default'}</code>"
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)


async def reset_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset settings for current/connected group: /reset_group."""
    message = update.effective_message
    if not message:
        return
    target_chat_id = await _resolve_admin_group_id(update, context)
    if not target_chat_id:
        return
    db: Database = context.bot_data["db"]
    await db.reset_group_settings(target_chat_id)
    await message.reply_text(
        f"♻️ Settings for group <code>{target_chat_id}</code> have been reset to default!",
        parse_mode=ParseMode.HTML,
    )


async def resetallgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to reset all group settings across the bot: /resetallgroup."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return
    db: Database = context.bot_data["db"]
    count = await db.reset_all_group_settings()
    await message.reply_text(
        f"♻️ Reset settings for all <code>{count}</code> configured group(s) to default!",
        parse_mode=ParseMode.HTML,
    )


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload group admin status and connect group to user PM: /reload."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ Use <code>/reload</code> inside a group chat.", parse_mode=ParseMode.HTML)
        return
    db: Database = context.bot_data["db"]
    await db.add_or_update_chat(chat.id, chat.title, chat.type)
    await db.add_connection(user.id, chat.id)
    await message.reply_text(
        f"✅ <b>Group Reloaded & Connected!</b>\n"
        f"👥 <b>Group:</b> <code>{html.escape(chat.title or str(chat.id))}</code>",
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 2B. Group Customization Commands (/set_caption, /set_fsub, /remove_fsub, /set_log_channel)
# =============================================================================

async def set_caption_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set custom file caption for a group: /set_caption <text>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    target_chat_id = await _resolve_admin_group_id(update, context)
    if not target_chat_id:
        return

    caption_txt = " ".join(context.args or []).strip()
    if not caption_txt and message.reply_to_message and message.reply_to_message.text:
        caption_txt = message.reply_to_message.text.strip()

    if not caption_txt:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/set_caption &lt;custom caption&gt;</code>\n"
            "Available placeholders: <code>{file_name}</code>, <code>{file_size}</code>, <code>{caption}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    db: Database = context.bot_data["db"]
    await db.save_group_settings(target_chat_id, "caption", caption_txt)
    await message.reply_text(
        f"✅ <b>Custom File Caption Saved for Group <code>{target_chat_id}</code>!</b>\n\n"
        f"<code>{html.escape(caption_txt)}</code>",
        parse_mode=ParseMode.HTML,
    )
    await send_work_log(
        context.bot,
        db,
        f"📝 <b>#Set_Caption</b>\n\n"
        f"👤 <b>Admin:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'Admin')}</a>\n"
        f"👥 <b>Group ID:</b> <code>{target_chat_id}</code>\n"
        f"💬 <b>Caption:</b> <code>{html.escape(caption_txt[:200])}</code>",
    )


async def set_fsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set Force Subscribe channel IDs for a group: /set_fsub <channel_id>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    target_chat_id = await _resolve_admin_group_id(update, context)
    if not target_chat_id:
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/set_fsub -1001234567890</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    fsub_ids = []
    for raw in args:
        cleaned = raw.strip()
        if cleaned.lstrip("-").isdigit():
            fsub_ids.append(int(cleaned))

    if not fsub_ids:
        await message.reply_text("❌ Please provide valid numeric channel ID(s) starting with <code>-100</code>.", parse_mode=ParseMode.HTML)
        return

    db: Database = context.bot_data["db"]
    await db.save_group_settings(target_chat_id, "fsub", fsub_ids)
    await message.reply_text(
        f"✅ <b>Force Subscribe Channel(s) Set for Group <code>{target_chat_id}</code>:</b>\n"
        f"<code>{', '.join(str(x) for x in fsub_ids)}</code>",
        parse_mode=ParseMode.HTML,
    )
    await send_work_log(
        context.bot,
        db,
        f"📢 <b>#Fsub_Channel_Set</b>\n\n"
        f"👤 <b>Admin:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'Admin')}</a>\n"
        f"👥 <b>Group ID:</b> <code>{target_chat_id}</code>\n"
        f"📢 <b>Channels:</b> <code>{', '.join(str(x) for x in fsub_ids)}</code>",
    )


async def remove_fsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove group-specific Force Subscribe channels: /remove_fsub."""
    message = update.effective_message
    if not message:
        return
    target_chat_id = await _resolve_admin_group_id(update, context)
    if not target_chat_id:
        return
    db: Database = context.bot_data["db"]
    await db.save_group_settings(target_chat_id, "fsub", [])
    await message.reply_text(
        f"✅ Removed custom Force Subscribe channels for group <code>{target_chat_id}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def set_log_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set operational log channel ID: /set_log_channel <channel_id>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/set_log_channel -1001234567890</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    ch_id = int(args[0])
    db: Database = context.bot_data["db"]
    await db.set_log_channel(ch_id)
    await message.reply_text(
        f"✅ <b>Operational Work Log Channel Set To:</b> <code>{ch_id}</code>\n"
        f"<i>Only work-related logs (New Users, Groups, VIP Subscriptions, Requests, Errors) will be sent there.</i>",
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 2C. Bot-Level Toggles & Trending Searches (/pm_search, /movie_update, /del_msg, /top_search)
# =============================================================================

async def pm_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to toggle Bot PM auto-filter search: /pm_search <on|off>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    args = context.args or []
    if not args:
        curr = await db.get_pm_search_enabled()
        await message.reply_text(
            f"🔍 <b>Bot PM Search Status:</b> <code>{'✅ ON' if curr else '❌ OFF'}</code>\n\n"
            f"Usage: <code>/pm_search on</code> or <code>/pm_search off</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    val = args[0].strip().lower() in ("on", "true", "1", "yes", "enable")
    await db.set_pm_search_enabled(val)
    await message.reply_text(
        f"✅ <b>Bot PM Search is now {'ENABLED 🟢' if val else 'DISABLED 🔴'}!</b>",
        parse_mode=ParseMode.HTML,
    )


async def movie_update_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to toggle movie update notifications: /movie_update <on|off>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    args = context.args or []
    if not args:
        curr = await db.get_movie_update_enabled()
        await message.reply_text(
            f"🎬 <b>Movie Update Notifications:</b> <code>{'✅ ON' if curr else '❌ OFF'}</code>\n\n"
            f"Usage: <code>/movie_update on</code> or <code>/movie_update off</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    val = args[0].strip().lower() in ("on", "true", "1", "yes", "enable")
    await db.set_movie_update_enabled(val)
    await message.reply_text(
        f"✅ <b>Movie Update Notifications are now {'ENABLED 🟢' if val else 'DISABLED 🔴'}!</b>",
        parse_mode=ParseMode.HTML,
    )


async def del_msg_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to clear top search history list: /del_msg."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    cleared = await db.clear_search_history()
    await message.reply_text(
        f"🗑️ Cleared <code>{cleared}</code> trending search queries from history!",
        parse_mode=ParseMode.HTML,
    )


async def top_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display interactive Top Searches / Trendlist: /top_search or /trendlist."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    top_items = await db.get_top_searches(limit=20)
    if not top_items:
        await message.reply_text(
            "📊 <b>No trending searches recorded yet!</b>\n"
            "Search for any movie or series to populate the trending list.",
            parse_mode=ParseMode.HTML,
        )
        return

    rows = []
    row = []
    lines = ["🔥 <b><u>Tᴏᴘ Tʀᴇɴᴅɪɴɢ Sᴇᴀʀᴄʜᴇs</u></b>\n"]
    for idx, (q_str, cnt) in enumerate(top_items, 1):
        lines.append(f"{idx}. <code>{html.escape(q_str.title())}</code> ({cnt} searches)")
        q_hash = get_query_hash(q_str)
        row.append(InlineKeyboardButton(f"🎬 {q_str.title()[:20]}", callback_data=f"fsp_{user.id}_{q_hash}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close")])

    lines.append("\n👇 <i>Tᴀᴘ ᴀɴʏ ᴛɪᴛʟᴇ ʙᴇʟᴏᴡ ᴛᴏ sᴇᴀʀᴄʜ ɪɴsᴛᴀɴᴛʟʏ:</i>")
    await message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 2D. /send, /deletefiles, /request, /admin_cmd, /group_cmd
# =============================================================================

async def send_user_msg_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to send a replied message directly to a specific user: /send <user_id>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    args = context.args or []
    if not args or not args[0].isdigit() or not message.reply_to_message:
        await message.reply_text(
            "📌 <b>Usage:</b> Reply to any message with <code>/send &lt;user_id&gt;</code> to deliver it to that user.",
            parse_mode=ParseMode.HTML,
        )
        return

    target_uid = int(args[0])
    try:
        await context.bot.copy_message(
            chat_id=target_uid,
            from_chat_id=message.chat_id,
            message_id=message.reply_to_message.message_id,
        )
        await message.reply_text(f"✅ Message successfully sent to user <code>{target_uid}</code>!", parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ Failed to send message to <code>{target_uid}</code>: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def deletefiles_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to bulk delete files matching a keyword: /deletefiles <keyword>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    keyword = " ".join(context.args or []).strip()
    if not keyword:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/deletefiles &lt;keyword&gt;</code>\n"
            "Example: <code>/deletefiles Pushpa 480p</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    db: Database = context.bot_data["db"]
    count = await db.count_files_by_keyword(keyword)
    if count == 0:
        await message.reply_text(
            f"📭 No indexed files found matching <b>\"{html.escape(keyword)}\"</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    kw_hash = hashlib.md5(keyword.lower().encode("utf-8")).hexdigest()[:10]
    KILLFILES_CACHE[kw_hash] = keyword

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🗑️ Yes, Delete {count} File(s)", callback_data=f"killfiles_yes_{kw_hash}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu_close")],
    ])
    await message.reply_text(
        f"⚠️ <b><u>Confirm Bulk File Deletion</u></b>\n\n"
        f"🔍 <b>Keyword:</b> <code>{html.escape(keyword)}</code>\n"
        f"📁 <b>Matching Files:</b> <code>{count}</code>\n\n"
        f"Are you sure you want to permanently delete all matching records from the catalog?",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def deletefiles_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmation button for /deletefiles."""
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_admin(user.id):
        await query.answer("⛔ Admin permission required.", show_alert=True)
        return

    kw_hash = query.data.removeprefix("killfiles_yes_")
    keyword = KILLFILES_CACHE.pop(kw_hash, None)
    if not keyword:
        await query.answer("⚠️ Confirmation expired. Run /deletefiles again.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    deleted = await db.delete_files_by_keyword(keyword)
    await query.answer(f"🗑️ Deleted {deleted} file(s)!", show_alert=True)
    try:
        await query.edit_message_text(
            f"🗑️ <b>Bulk Deletion Complete!</b>\n\n"
            f"• <b>Keyword:</b> <code>{html.escape(keyword)}</code>\n"
            f"• <b>Files Removed:</b> <code>{deleted}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User command to request a movie/series from admins: /request <title> or #request <title>."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return

    raw_text = message.text or ""
    if raw_text.startswith("/"):
        req_title = " ".join(context.args or []).strip()
    else:
        req_title = re.sub(r"^#(?:request|req)\s*", "", raw_text.strip(), flags=re.IGNORECASE).strip()

    if not req_title or len(req_title) < 2:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/request &lt;Movie or Series Name + Year&gt;</code>\n"
            "Example: <code>/request Avatar (2022) 1080p Dual Audio</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    db: Database = context.bot_data["db"]
    req_hash = hashlib.md5(f"{user.id}:{req_title}".encode("utf-8")).hexdigest()[:8]
    REQUEST_CACHE[req_hash] = req_title
    safe_user = html.escape(user.first_name or "User")
    safe_title = html.escape(req_title)

    await message.reply_text(
        f"✅ <b>Request Submitted!</b>\n\n"
        f"🎬 <b>Requested Title:</b> <code>{safe_title}</code>\n"
        f"👤 <b>Requested By:</b> {safe_user}\n\n"
        f"<i>Our administrators have been notified and will update you once it is uploaded!</i>",
        parse_mode=ParseMode.HTML,
    )

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Uploaded", callback_data=f"reqopt_up_{user.id}_{req_hash}"),
            InlineKeyboardButton("📌 Already Available", callback_data=f"reqopt_al_{user.id}_{req_hash}"),
        ],
        [
            InlineKeyboardButton("❌ Unavailable", callback_data=f"reqopt_un_{user.id}_{req_hash}"),
            InlineKeyboardButton("🚫 Reject", callback_data=f"reqopt_rj_{user.id}_{req_hash}"),
        ],
    ])

    await send_work_log(
        context.bot,
        db,
        f"📩 <b>#Request</b>\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={user.id}'>{safe_user}</a> (<code>{user.id}</code>)\n"
        f"👥 <b>Chat:</b> <code>{html.escape(chat.title or 'Private DM')}</code>\n"
        f"🎬 <b>Title:</b> <code>{safe_title}</code>",
        reply_markup=admin_kb,
        channel_override=REQST_CHANNEL_ID,
    )


async def request_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin status buttons on a user movie request (reqopt_<action>_<uid>_<hash>)."""
    query = update.callback_query
    if not query or not query.data:
        return

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Only administrators can update request status.", show_alert=True)
        return

    parts = query.data.split("_")
    if len(parts) < 4:
        return

    action = parts[1]
    target_uid = int(parts[2])
    req_hash = parts[3]
    req_title = REQUEST_CACHE.get(req_hash, "your requested title")

    status_map = {
        "up": ("✅ Uploaded", f"🎉 Good news! Your requested title <b>{html.escape(req_title)}</b> has been uploaded! Search for it now."),
        "al": ("📌 Already Available", f"ℹ️ Your requested title <b>{html.escape(req_title)}</b> is already available in our catalog! Please check your spelling and search again."),
        "un": ("❌ Unavailable", f"⚠️ Sorry, your requested title <b>{html.escape(req_title)}</b> is currently unavailable."),
        "rj": ("🚫 Rejected", f"🚫 Your request for <b>{html.escape(req_title)}</b> was rejected by administrators."),
    }

    badge, user_notice = status_map.get(action, ("Updated", "Your request status has been updated."))
    try:
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"📬 <b><u>Rᴇǫᴜᴇsᴛ Sᴛᴀᴛᴜs Uᴘᴅᴀᴛᴇ</u></b>\n\n{user_notice}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await query.answer(f"Marked as: {badge}", show_alert=True)
    try:
        orig_html = query.message.text_html if query.message else ""
        await query.edit_message_text(
            f"{orig_html}\n\n<b>Status:</b> {badge} (by {html.escape(query.from_user.first_name or 'Admin')})",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def admin_cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display full admin commands list: /admin_cmd."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return
    await message.reply_text(Script.ADMIN_TXT, parse_mode=ParseMode.HTML)


async def group_cmd_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display full group management commands list: /group_cmd."""
    message = update.effective_message
    if not message:
        return
    await message.reply_text(Script.GROUPMANAGER_TXT, parse_mode=ParseMode.HTML)


# =============================================================================
# 3. /logs (Work-Related Only — Filters Out File Indexing Noise)
# =============================================================================

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send recent work-related runtime logs: /logs."""
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
            raw_lines = f.readlines()

        # Filter out any historical file-indexing or mirroring noise lines
        lines = [
            ln for ln in raw_lines
            if "Auto-registered new channel post" not in ln
            and "Mirrored file to storage channel" not in ln
        ]

        recent = lines[-50:] if len(lines) > 50 else lines
        text = "".join(recent).strip() or "No work logs recorded yet."
        escaped_text = html.escape(text)

        if len(escaped_text) < 3800:
            await message.reply_text(
                f"📋 <b>Recent Work Logs (Last {len(recent)} lines):</b>\n\n<pre>{escaped_text}</pre>",
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
            f"✅ Successfully connected to <b>{safe_title}</b>!\nYou can now manage filters and settings from PM.",
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
                InlineKeyboardButton("⚙️ Group Settings", callback_data=f"st_grp_back_{cid}"),
            ],
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
    Delegates directly to the high-speed MTProto indexer.
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
