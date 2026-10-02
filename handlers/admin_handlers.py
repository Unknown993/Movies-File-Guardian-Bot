"""
Admin and Developer command handlers:
- /set_mode <view_only|downloadable> (Developer only)
- /get_mode or /mode
- /set_timer <seconds>
- /stats
- Inline keyboard mode toggles
"""

from __future__ import annotations

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import (
    DEVELOPER_ID,
    DeliveryMode,
    is_developer,
    is_admin,
)
from database import Database

logger = logging.getLogger(__name__)


def build_mode_keyboard(current_mode: DeliveryMode) -> InlineKeyboardMarkup:
    """Build inline keyboard for quick mode switching."""
    v_mark = "✅ " if current_mode == DeliveryMode.VIEW_ONLY else ""
    d_mark = "✅ " if current_mode == DeliveryMode.DOWNLOADABLE else ""

    keyboard = [
        [
            InlineKeyboardButton(
                f"{v_mark}🔒 Mode 1: View Only",
                callback_data="set_mode_view_only",
            )
        ],
        [
            InlineKeyboardButton(
                f"{d_mark}⏱️ Mode 2: Downloadable (Auto-Expiry)",
                callback_data="set_mode_downloadable",
            )
        ],
        [
            InlineKeyboardButton("📊 System Status", callback_data="admin_refresh_status")
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def format_mode_summary(mode: DeliveryMode, timer_secs: int) -> str:
    """Format readable markdown explanation of current delivery mode."""
    minutes = timer_secs // 60
    seconds = timer_secs % 60
    timer_str = f"{minutes}m {seconds}s" if minutes and seconds else (f"{minutes}m" if minutes else f"{seconds}s")

    if mode == DeliveryMode.VIEW_ONLY:
        return (
            "🛡️ **Current Delivery Mode: Mode 1 (View Only)**\n\n"
            "• **Content Protection:** `protect_content=True` 🔒\n"
            "• **Forwarding / Saving:** Completely disabled by Telegram.\n"
            "• **Access:** In-app viewing/streaming only.\n"
            "• **Auto-Deletion:** Inactive."
        )
    else:
        return (
            "⚡ **Current Delivery Mode: Mode 2 (Download Allowed)**\n\n"
            "• **Content Protection:** `protect_content=False` 🔓\n"
            "• **Delivery Method:** `copy_message` (Stripped source metadata / no forward header)\n"
            f"• **Auto-Destruct Timer:** Active ({timer_str})\n"
            "• **Delivery Restriction:** Private DM & authorized temp channels only."
        )


async def set_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /set_mode <view_only|downloadable>
    Restricted strictly to DEVELOPER_ID.
    """
    user = update.effective_user
    if not user or not is_developer(user.id):
        await update.effective_message.reply_text(
            "⛔ **Access Denied**\n\n"
            "Only the bot **Developer** (`DEVELOPER_ID`) is authorized to configure file delivery modes.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    args = context.args or []

    # If no argument supplied, show interactive menu
    if not args:
        curr_mode = await db.get_delivery_mode()
        timer = await db.get_auto_delete_seconds()
        text = (
            f"{format_mode_summary(curr_mode, timer)}\n\n"
            "**Developer Controls:**\n"
            "Select an option below or use:\n"
            "`/set_mode view_only`\n"
            "`/set_mode downloadable`"
        )
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_mode_keyboard(curr_mode),
        )
        return

    # Parse argument
    target_mode_raw = args[0]
    try:
        new_mode = DeliveryMode.from_str(target_mode_raw)
    except ValueError:
        await update.effective_message.reply_text(
            f"❌ **Invalid Mode:** `{target_mode_raw}`\n\n"
            "Allowed options are:\n"
            "• `view_only` (Mode 1: Native content protection, no saving/forwarding)\n"
            "• `downloadable` (Mode 2: Download allowed, stripped headers, auto-destruct timer)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await db.set_delivery_mode(new_mode)
    timer = await db.get_auto_delete_seconds()

    await update.effective_message.reply_text(
        f"✅ **Delivery Mode Successfully Updated!**\n\n"
        f"{format_mode_summary(new_mode, timer)}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_mode_keyboard(new_mode),
    )


async def get_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /get_mode or /mode - display current mode details."""
    user = update.effective_user
    if not user or not is_admin(user.id):
        await update.effective_message.reply_text(
            "⛔ This command is restricted to administrators and the developer.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    curr_mode = await db.get_delivery_mode()
    timer = await db.get_auto_delete_seconds()

    reply_markup = build_mode_keyboard(curr_mode) if is_developer(user.id) else None

    await update.effective_message.reply_text(
        format_mode_summary(curr_mode, timer),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )


async def set_timer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /set_timer <seconds> to configure Mode 2 self-destruct delay."""
    user = update.effective_user
    if not user or not is_developer(user.id):
        await update.effective_message.reply_text(
            "⛔ Only the bot Developer can adjust the self-destruct timer.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    args = context.args or []
    if not args or not args[0].isdigit():
        await update.effective_message.reply_text(
            "⚠️ **Usage:** `/set_timer <seconds>`\n\n"
            "Example:\n"
            "• `/set_timer 180` (3 minutes - default)\n"
            "• `/set_timer 300` (5 minutes)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    seconds = int(args[0])
    if seconds < 10 or seconds > 86400:
        await update.effective_message.reply_text(
            "❌ Timer must be between 10 seconds and 86400 seconds (24 hours).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    await db.set_auto_delete_seconds(seconds)

    minutes = seconds // 60
    rem_secs = seconds % 60
    time_str = f"{minutes}m {rem_secs}s" if minutes and rem_secs else (f"{minutes} minutes" if minutes else f"{seconds} seconds")

    await update.effective_message.reply_text(
        f"⏱️ **Self-Destruct Timer Updated!**\n\n"
        f"Files delivered in **Mode 2 (Downloadable)** will now auto-delete after **{time_str}** ({seconds}s).",
        parse_mode=ParseMode.MARKDOWN,
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command."""
    user = update.effective_user
    if not user or not is_admin(user.id):
        await update.effective_message.reply_text(
            "⛔ This command is restricted to administrators.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    stats = await db.get_statistics()

    timer_secs = stats["auto_delete_seconds"]
    text = (
        "📊 **Bot System & Storage Statistics**\n\n"
        f"• **Delivery Mode:** `{stats['delivery_mode']}`\n"
        f"• **Auto-Delete Timer:** `{timer_secs} seconds`\n"
        f"• **Total Registered Files:** `{stats['total_files']}`\n"
        f"• **Total Access Events:** `{stats['total_accesses']}`\n"
        f"• **Pending Destruct Jobs:** `{stats['pending_deletions']}`\n"
        f"• **Developer ID:** `{DEVELOPER_ID}`\n"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def mode_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks for mode switches."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if not user or not is_developer(user.id):
        await query.answer("⛔ Only the developer can change modes.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    data = query.data

    if data == "set_mode_view_only":
        await db.set_delivery_mode(DeliveryMode.VIEW_ONLY)
    elif data == "set_mode_downloadable":
        await db.set_delivery_mode(DeliveryMode.DOWNLOADABLE)
    elif data == "admin_refresh_status":
        pass  # Just re-render status

    curr_mode = await db.get_delivery_mode()
    timer = await db.get_auto_delete_seconds()

    text = (
        f"{format_mode_summary(curr_mode, timer)}\n\n"
        "**Developer Controls:**\n"
        "Click a button below to switch mode:"
    )

    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_mode_keyboard(curr_mode),
        )
    except Exception as e:
        logger.debug("Inline menu edit exception (content identical): %s", e)
