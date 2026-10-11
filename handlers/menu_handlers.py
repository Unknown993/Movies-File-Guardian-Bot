"""
Interactive Navigation & Callback Menus module:
Faithfully replicates all buttons, characteristics, and sub-menus of MR.Guardian_bot / Professor-Bot:
- Start Menu with Add To Group, Search, Help, About
- Help Category Hub (Admin Panel, Filters, Connect, File Store, Extra Mode, Group Manager, Bot Status)
- Filter Sub-menus (AutoFilter, ManualFilter, GlobalFilter, Button Format)
- Real-time Bot and Server Status with live refresh
- Source Code and About pages
- Close button functionality
"""

from __future__ import annotations

import html
import time
import shutil
import logging
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatType
from telegram.ext import ContextTypes

from config import is_admin, is_developer
from database import Database
from script import Script
from handlers.file_handlers import format_file_size
from handlers.extended_commands import format_uptime, BOT_START_TIME

logger = logging.getLogger(__name__)


def get_start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Build the main Start keyboard matching MR.Guardian_bot."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕️ Aᴅᴅ Mᴇ Tᴏ Yᴏᴜʀ Cʜᴀᴛ ➕", url=f"https://t.me/{bot_username}?startgroup=true")
        ],
        [
            InlineKeyboardButton("Sᴇᴀʀᴄʜ 🔎", switch_inline_query_current_chat=""),
            InlineKeyboardButton("Aʙᴏᴜᴛ ✨", callback_data="menu_about"),
        ],
        [
            InlineKeyboardButton("💎 VIP & Pʟᴀɴs", callback_data="show_plans"),
            InlineKeyboardButton("Hᴇʟᴘ 🕸️", callback_data="menu_help"),
        ]
    ])


def get_help_keyboard() -> InlineKeyboardMarkup:
    """Build the main Help menu keyboard with all category buttons."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ Aᴅᴍɪɴ Pᴀɴᴇʟ ⚙️", callback_data="menu_admin")
        ],
        [
            InlineKeyboardButton("💎 VIP & Pʟᴀɴs", callback_data="show_plans"),
            InlineKeyboardButton("👤 Mʏ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ", callback_data="show_myplan"),
        ],
        [
            InlineKeyboardButton("Fɪʟᴛᴇʀs", callback_data="menu_filters"),
            InlineKeyboardButton("Cᴏɴɴᴇᴄᴛ", callback_data="menu_connect"),
        ],
        [
            InlineKeyboardButton("Fɪʟᴇ Sᴛᴏʀᴇ", callback_data="menu_filestore"),
            InlineKeyboardButton("Exᴛʀᴀ Mᴏᴅᴇ", callback_data="menu_extramod"),
        ],
        [
            InlineKeyboardButton("Gʀᴏᴜᴘ Mᴀɴᴀɢᴇʀ", callback_data="menu_gpmanager"),
            InlineKeyboardButton("Bᴏᴛ Sᴛᴀᴛᴜs ❄️", callback_data="menu_stats"),
        ],
        [
            InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"),
            InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_start"),
        ]
    ])


async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all interactive menu button callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    user = update.effective_user
    db: Database = context.bot_data["db"]

    bot_me = await context.bot.get_me()
    bot_name = html.escape(str(bot_me.first_name or "TeleBot"))
    bot_username = bot_me.username or "Bot"
    user_name = html.escape(str(user.first_name if user else "User"))

    if data == "menu_close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    elif data == "menu_start":
        text = Script.START_TXT.format(user=user_name, bot=bot_name)
        reply_markup = get_start_keyboard(bot_username)
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_help":
        text = Script.HELP_TXT.format(user=user_name)
        reply_markup = get_help_keyboard()
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_about":
        text = Script.ABOUT_TXT.format(bot=bot_name)
        buttons = [
            [InlineKeyboardButton("Sᴏᴜʀᴄᴇ Cᴏᴅᴇ 📜", callback_data="menu_source")],
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_start")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_source":
        text = Script.SOURCE_TXT
        buttons = [
            [InlineKeyboardButton("Sᴏᴜʀᴄᴇ Cᴏᴅᴇ", url="https://github.com/Unknown993/PROFESSOR-BOT")],
            [InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_about")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_filters":
        text = Script.FILTER_TXT
        buttons = [
            [
                InlineKeyboardButton("AᴜᴛᴏFɪʟᴛᴇʀ", callback_data="menu_autofilter"),
                InlineKeyboardButton("MᴀɴᴜᴀʟFɪʟᴛᴇʀ", callback_data="menu_manualfilter"),
            ],
            [
                InlineKeyboardButton("GʟᴏʙᴀʟFɪʟᴛᴇʀ", callback_data="menu_globalfilter"),
            ],
            [
                InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"),
                InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help"),
            ]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_autofilter":
        text = Script.AUTOFILTER_TXT
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_filters")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_manualfilter":
        text = Script.MANUELFILTER_TXT
        buttons = [
            [InlineKeyboardButton("Bᴜᴛᴛᴏɴ Fᴏʀᴍᴀᴛ", callback_data="menu_btnformat")],
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_filters")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_globalfilter":
        text = Script.GLOBALFILTER_TXT
        buttons = [
            [InlineKeyboardButton("Bᴜᴛᴛᴏɴ Fᴏʀᴍᴀᴛ", callback_data="menu_btnformat")],
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_filters")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_btnformat":
        text = Script.BUTTON_TXT
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_filters")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_connect":
        text = Script.CONNECTION_TXT
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_filestore":
        text = Script.FILE_TXT
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_extramod":
        text = Script.EXTRAMOD_TXT
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_gpmanager":
        text = Script.GROUPMANAGER_TXT
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()

    elif data == "menu_stats":
        total_files = await db.get_total_files_count()
        total_users = await db.get_total_users_count()
        all_chats = await db.get_all_chats()
        total_chats = len(all_chats)
        db_size_bytes = db.get_db_size()
        db_size_str = format_file_size(db_size_bytes)
        uptime_str = format_uptime(time.time() - BOT_START_TIME)

        text = Script.STATUS_TXT.format(
            files=total_files,
            users=total_users,
            chats=total_chats,
            db_size=db_size_str,
            uptime=uptime_str,
        )
        buttons = [
            [InlineKeyboardButton("⟳ Rᴇғʀᴇsʜ", callback_data="menu_stats")],
            [InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer("Status Refreshed! ❄️")

    elif data == "menu_admin":
        if not user or not is_admin(user.id):
            return await query.answer("Sᴏʀʀʏ Tʜɪs Mᴇɴᴜ Oɴʟʏ Fᴏʀ Mʏ Aᴅᴍɪɴs ⚒️", show_alert=True)

        total, used, free = shutil.disk_usage(".")
        disk_total_str = format_file_size(total)
        disk_used_str = format_file_size(used)
        disk_free_str = format_file_size(free)
        disk_percent = round((used / total) * 100, 1) if total > 0 else 0

        cpu_percent = psutil.cpu_percent() if psutil else 0
        ram_percent = psutil.virtual_memory().percent if psutil else 0
        uptime_str = format_uptime(time.time() - BOT_START_TIME)

        server_stats = Script.SERVER_STATS.format(
            uptime=uptime_str,
            cpu=cpu_percent,
            ram=ram_percent,
            disk_total=disk_total_str,
            disk_used=disk_used_str,
            disk_percent=disk_percent,
            disk_free=disk_free_str,
        )

        full_text = f"{server_stats}\n\n{Script.ADMIN_TXT}"
        buttons = [
            [InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close"), InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="menu_help")]
        ]
        try:
            await query.edit_message_text(full_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
