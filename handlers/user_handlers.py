"""
User handlers:
- /start (welcome & deep-link file delivery)
- /help (command reference)
"""

from __future__ import annotations

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatType
from telegram.ext import ContextTypes

from config import is_developer, is_admin
from database import Database
from delivery import deliver_file_to_user
from cleaner import smart_clean_filename, get_file_type_icon

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command, including deep-link file retrievals."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    db: Database = context.bot_data["db"]
    args = context.args or []

    # -------------------------------------------------------------
    # Deep-link File Retrieval: /start file_<code> or /start <code>
    # -------------------------------------------------------------
    if args:
        raw_payload = args[0]
        file_code = raw_payload.removeprefix("file_").strip()
        file_record = await db.get_file_by_code(file_code)

        if not file_record:
            await message.reply_text(
                "❌ **File Not Found or Expired**\n\n"
                "The requested file code does not exist, has been removed, "
                "or expired according to delivery policies.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        bot_user = await context.bot.get_me()
        bot_username = bot_user.username or "Bot"

        await deliver_file_to_user(
            bot=context.bot,
            db=db,
            job_queue=context.job_queue,
            chat_id=chat.id,
            chat_type=chat.type,
            file_record=file_record,
            bot_username=bot_username,
        )
        return

    # -------------------------------------------------------------
    # Standard Welcome Message
    # -------------------------------------------------------------
    curr_mode = await db.get_delivery_mode()
    mode_title = (
        "🔒 Mode 1 (View Only)" if curr_mode.value == "view_only" else "⏱️ Mode 2 (Download Allowed)"
    )

    dev_note = ""
    if is_developer(user.id):
        dev_note = (
            "\n\n👑 **Developer Detected:**\n"
            "• `/set_mode <view_only|downloadable>` - Switch delivery strategy\n"
            "• `/set_timer <seconds>` - Configure auto-destruct timer\n"
            "• `/get_mode` - View current settings\n"
            "• `/stats` - View bot analytics\n"
            "• Send any media file to this chat to generate a shareable link!"
        )

    await message.reply_text(
        f"👋 **Welcome, {user.first_name}!**\n\n"
        "This bot delivers files with strict **Content Protection & Privacy Strategies**:\n\n"
        "• **Mode 1 (View Only):** Prevents forwarding, saving, and copying. Media streams natively.\n"
        "• **Mode 2 (Download Allowed):** Delivers files with all source metadata stripped, and automatically deletes the file after a short timer to prevent unauthorized circulation.\n\n"
        f"⚙️ **Active Delivery Mode:** `{mode_title}`"
        f"{dev_note}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user = update.effective_user
    if not user:
        return

    text = (
        "📖 **Bot Commands & Usage Guide**\n\n"
        "**Finding & Getting Files:**\n"
        "• `/search <name>` - Search for files by keyword (e.g. `/search python`)\n"
        "• `/files` or `/list` - View recently indexed files\n"
        "• Send any word or title directly in chat to search\n"
        "• `/start <code>` - Retrieve a file by its unique code\n\n"
        "**General Commands:**\n"
        "• `/start` - Start the bot and view delivery status\n"
        "• `/help` - Show this help message\n"
    )

    if is_admin(user.id):
        text += (
            "\n**Admin & Storage Commands:**\n"
            "• `/index_range <start_id> <end_id>` - Bulk scan channel messages (e.g. `/index_range 1 50`)\n"
            "• `/get_mode` - Display active delivery mode and timer\n"
            "• `/stats` - Show file count and access statistics\n"
            "• Send or forward any file to register it and get a share link\n"
        )

    if is_developer(user.id):
        text += (
            "\n**Developer Commands:**\n"
            "• `/set_mode <view_only|downloadable>` - Toggle between Mode 1 and Mode 2\n"
            "• `/set_timer <seconds>` - Set auto-destruct duration (e.g. 180 or 300)\n"
        )

    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search for files in the database by keyword: /search <keyword>."""
    message = update.effective_message
    if not message:
        return

    query = " ".join(context.args or []).strip()
    if not query:
        await message.reply_text(
            "🔍 **Usage:** `/search <name>`\n\n"
            "**Example:** `/search python` or `/search notes`\n"
            "💡 *Tip: You can also just type any name directly in this chat!*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _perform_file_search(update, context, query)


async def list_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the latest indexed files: /files or /list."""
    message = update.effective_message
    if not message:
        return

    db: Database = context.bot_data["db"]
    recent = await db.get_recent_files(limit=10)

    if not recent:
        await message.reply_text(
            "📭 **No files have been indexed yet.**\n"
            "Upload files or run `/index_range 1 50` to index your storage channel.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    buttons = []
    text_lines = ["📁 **Recently Indexed Files:**\n"]
    for i, f in enumerate(recent, 1):
        clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
        icon = get_file_type_icon(f.get("file_type", ""), clean_name)
        text_lines.append(f"{i}. {icon} `{clean_name}`")
        buttons.append([InlineKeyboardButton(f"📥 Get: {clean_name[:28]}", callback_data=f"getfile_{f['file_code']}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("\n".join(text_lines), reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def handle_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allow users to simply send any filename or keyword to find it."""
    message = update.effective_message
    if not message or not message.text:
        return

    # Ignore command messages
    if message.text.startswith("/"):
        return

    query = message.text.strip()
    if len(query) < 2:
        return

    await _perform_file_search(update, context, query)


async def file_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle instant download when clicking a search result or /files button."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer("Fetching file...")

    file_code = query.data.removeprefix("getfile_").strip()
    db: Database = context.bot_data["db"]
    file_record = await db.get_file_by_code(file_code)

    if not file_record:
        await query.message.reply_text(
            "❌ **File Not Found or Expired**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"

    await deliver_file_to_user(
        bot=context.bot,
        db=db,
        job_queue=context.job_queue,
        chat_id=query.message.chat_id,
        chat_type=query.message.chat.type,
        file_record=file_record,
        bot_username=bot_username,
    )


async def _perform_file_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """Helper to query database and either deliver directly (if 1 match) or show buttons."""
    message = update.effective_message
    if not message:
        return

    db: Database = context.bot_data["db"]
    matches = await db.search_files(query, limit=8)

    if not matches:
        await message.reply_text(
            f"🔍 No files found matching **\"{query}\"**.\n\n"
            "• Check spelling or try a shorter title/keyword.\n"
            "• Use `/files` to browse recent files in the catalog.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"

    # If exactly 1 file matches, deliver it directly!
    if len(matches) == 1:
        file_record = matches[0]
        await deliver_file_to_user(
            bot=context.bot,
            db=db,
            job_queue=context.job_queue,
            chat_id=message.chat_id,
            chat_type=message.chat.type,
            file_record=file_record,
            bot_username=bot_username,
        )
        return

    # Multiple matches found: present quick-tap callback buttons
    buttons = []
    text_lines = [f"🔍 **Found {len(matches)} matching files for \"{query}\":**\n"]

    for i, f in enumerate(matches, 1):
        clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
        icon = get_file_type_icon(f.get("file_type", ""), clean_name)
        text_lines.append(f"{i}. {icon} `{clean_name}`")
        buttons.append([InlineKeyboardButton(f"📥 Get: {clean_name[:28]}", callback_data=f"getfile_{f['file_code']}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("\n".join(text_lines), reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
