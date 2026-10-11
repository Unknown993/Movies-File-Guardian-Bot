"""
Inline Search module:
Allows searching and sharing files from any chat via @bot_username <query>.
Supports switch_inline_query_current_chat buttons.
"""

from __future__ import annotations

import logging
import html
from typing import List

from telegram import (
    Update,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import Database
from cleaner import smart_clean_filename, get_file_type_icon
from handlers.file_handlers import format_file_size

logger = logging.getLogger(__name__)


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries (@botusername <query>)."""
    inline_query: InlineQuery = update.inline_query
    if not inline_query:
        return

    query_str = inline_query.query.strip()
    db: Database = context.bot_data["db"]

    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"

    results: List[InlineQueryResultArticle] = []

    if not query_str:
        # If no query, return recent files
        files = await db.get_recent_files(limit=15)
    else:
        # Search by keyword
        files = await db.search_files(query_str, limit=20)

    for f in files:
        raw_name = f.get("file_name") or f.get("caption") or "Untitled File"
        clean_name = smart_clean_filename(raw_name)
        f_type = f.get("file_type", "")
        icon = get_file_type_icon(f_type, clean_name)
        size_str = format_file_size(f.get("file_size", 0))
        code = f.get("file_code", "")

        deep_link = f"https://t.me/{bot_username}?start=file_{code}"

        message_content = InputTextMessageContent(
            f"📁 <b>{html.escape(clean_name)}</b>\n\n"
            f"📦 <b>Size:</b> <code>{size_str}</code>\n"
            f"🏷️ <b>Type:</b> <code>{f_type.upper()}</code>\n\n"
            f"⚡ <i>Delivered with Content Protection</i>",
            parse_mode=ParseMode.HTML,
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📥 Get File ({size_str})", url=deep_link)]
        ])

        results.append(
            InlineQueryResultArticle(
                id=f"file_{code}",
                title=f"{icon} {clean_name}",
                description=f"Size: {size_str} | Type: {f_type.upper()}",
                input_message_content=message_content,
                reply_markup=keyboard,
            )
        )

    await inline_query.answer(results, cache_time=10, is_personal=True)
