"""
User handlers:
- /start (welcome, referral tracking, #NewUser work log, & deep-link file delivery)
- /help (command reference)
"""

from __future__ import annotations

import html
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatType
from telegram.ext import ContextTypes

from config import is_developer, is_admin, get_ist_greeting, send_work_log, PREMIUM_LOGS
from database import Database
from delivery import deliver_file_to_user
from cleaner import smart_clean_filename, get_file_type_icon
from handlers.fsub_helper import is_user_subscribed, send_fsub_alert
from handlers.batch_handlers import deliver_batch_to_user
from handlers.payment_handlers import check_user_access, send_paywall_alert, split_date_time_ist
from script import Script
from handlers.menu_handlers import get_start_keyboard, get_help_keyboard

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command, including referral links and deep-link file retrievals."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    db: Database = context.bot_data["db"]
    # Check if user is banned
    is_banned, ban_reason = await db.is_user_banned(user.id)
    if is_banned:
        await message.reply_text(
            f"🚫 <b>Access Denied</b>\n\nYou have been banned from using this bot.\n<b>Reason:</b> <code>{html.escape(str(ban_reason))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Register user in SQLite and log #NewUser if this is their first time
    is_new_user = await db.add_or_update_user(user.id, user.first_name, user.username)
    if is_new_user:
        await send_work_log(
            context.bot,
            db,
            f"👤 <b>#NewUser</b>\n\n"
            f"🏷 <b>Nᴀᴍᴇ:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a>\n"
            f"🆔 <b>Usᴇʀ ID:</b> <code>{user.id}</code>\n"
            f"🔗 <b>Usᴇʀɴᴀᴍᴇ:</b> {'@' + html.escape(user.username) if user.username else 'None'}",
        )

    args = context.args or []

    # -------------------------------------------------------------
    # Deep-link Retrieval: /start reff_<id> | file_<code> | batch_<id>
    # -------------------------------------------------------------
    if args:
        raw_payload = args[0]
        bot_user = await context.bot.get_me()
        bot_username = bot_user.username or "Bot"

        # Check for referral deep-link: /start reff_<referrer_id>
        if raw_payload.startswith("reff_"):
            ref_str = raw_payload.removeprefix("reff_").strip()
            if ref_str.isdigit():
                referrer_id = int(ref_str)
                if referrer_id != user.id and hasattr(db, "mark_user_referred"):
                    newly_referred = await db.mark_user_referred(user.id, referrer_id)
                    if newly_referred:
                        new_pts = await db.add_refer_points(referrer_id, 10)
                        if new_pts >= 100:
                            await db.set_refer_points(referrer_id, new_pts - 100)
                            sub = await db.add_or_extend_subscription(
                                user_id=referrer_id,
                                plan_name="Referral Reward (1 Month VIP)",
                                stars=0,
                                duration_seconds=30 * 86400,
                            )
                            exp_date, exp_time = split_date_time_ist(sub["expires_at"])
                            try:
                                await context.bot.send_message(
                                    chat_id=referrer_id,
                                    text=(
                                        f"🎉 <b><u>Cᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴs! Rᴇғᴇʀʀᴀʟ Rᴇᴡᴀʀᴅ Uɴʟᴏᴄᴋᴇᴅ</u></b> 🏆\n\n"
                                        f"You reached <b>100 Referral Points</b> and unlocked <b>1 Month Free VIP Subscription</b>!\n"
                                        f"⌛ <b>Expires On:</b> <code>{exp_date} | {exp_time} IST</code>"
                                    ),
                                    parse_mode=ParseMode.HTML,
                                )
                            except Exception:
                                pass
                            await send_work_log(
                                context.bot,
                                db,
                                f"🏆 <b>#Referral_Reward</b>\n\n"
                                f"👤 <b>Referrer ID:</b> <code>{referrer_id}</code>\n"
                                f"🎁 <b>Reward:</b> <code>1 Month Free VIP (100 Points)</code>\n"
                                f"⌛ <b>Expiry:</b> <code>{exp_date} {exp_time} IST</code>",
                                channel_override=PREMIUM_LOGS,
                            )
                        else:
                            try:
                                await context.bot.send_message(
                                    chat_id=referrer_id,
                                    text=(
                                        f"🔗 <b><u>Nᴇᴡ Rᴇғᴇʀʀᴀʟ Bᴏɴᴜs! (+10 Pᴏɪɴᴛs)</u></b>\n\n"
                                        f"👤 <b>Joined User:</b> {html.escape(user.first_name or 'User')}\n"
                                        f"🏆 <b>Total Points:</b> <code>{new_pts} / 100</code>"
                                    ),
                                    parse_mode=ParseMode.HTML,
                                )
                            except Exception:
                                pass
            # Fall through to standard welcome message after recording referral
        else:
            # Check for /start help
            if raw_payload.lower() == "help":
                await message.reply_text(
                    Script.HELP_TXT.format(user=html.escape(user.first_name or "User")),
                    reply_markup=get_help_keyboard(),
                    parse_mode=ParseMode.HTML,
                )
                return

            # Check for /start plan or /start buy deep links
            if raw_payload.lower() in ("plan", "plans", "buy", "vip"):
                from handlers.payment_handlers import plan_command
                await plan_command(update, context)
                return

            if raw_payload.startswith("buy_"):
                try:
                    stars_val = int(raw_payload.removeprefix("buy_"))
                    from handlers.payment_handlers import send_star_invoice
                    sent = await send_star_invoice(
                        bot=context.bot,
                        chat_id=chat.id,
                        user_id=user.id,
                        stars_amount=stars_val,
                        db=db,
                    )
                    if sent:
                        return
                except (ValueError, IndexError):
                    pass
                from handlers.payment_handlers import plan_command
                await plan_command(update, context)
                return

            # Force Subscription Check
            if not await is_user_subscribed(context.bot, user.id):
                await send_fsub_alert(context.bot, chat.id, raw_payload, bot_username)
                return

            # Paywall / Paid-Only Access Check
            if not await check_user_access(db, user.id):
                await send_paywall_alert(context.bot, chat.id, user.first_name)
                return

            # 1. Batch Link Delivery
            if raw_payload.startswith("batch_"):
                batch_id = raw_payload.removeprefix("batch_").strip()
                await deliver_batch_to_user(
                    bot=context.bot,
                    db=db,
                    job_queue=context.job_queue,
                    chat_id=chat.id,
                    chat_type=chat.type,
                    batch_id=batch_id,
                    bot_username=bot_username,
                )
                return

            # 2. Single File Delivery
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
    # Standard Welcome Message & Interactive Menu
    # -------------------------------------------------------------
    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"
    bot_name = bot_user.first_name or "TeleBot"

    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        grp_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("ℹ️ Hᴇʟᴘ", url=f"https://t.me/{bot_username}?start=help")],
            [InlineKeyboardButton("Sᴇᴀʀᴄʜ 🔎", switch_inline_query_current_chat="")],
        ])
        await message.reply_text(
            f"✨ Hello {user.first_name}! Add me as admin to search and filter files.",
            reply_markup=grp_btn,
        )
        return

    welcome_text = Script.START_TXT.format(
        user=html.escape(user.first_name or "User"),
        bot=html.escape(bot_name),
        wish=get_ist_greeting(),
    )
    reply_markup = get_start_keyboard(bot_username)

    await message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command with interactive category menus."""
    user = update.effective_user
    if not user:
        return

    await update.effective_message.reply_text(
        Script.HELP_TXT.format(user=html.escape(user.first_name or "User")),
        reply_markup=get_help_keyboard(),
        parse_mode=ParseMode.HTML,
    )


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
    user = update.effective_user
    if not message:
        return

    db: Database = context.bot_data["db"]
    if user and not await check_user_access(db, user.id):
        await send_paywall_alert(context.bot, message.chat_id, user.first_name)
        return

    recent = await db.get_recent_files(limit=10)

    if not recent:
        await message.reply_text(
            "📭 **No files have been indexed yet.**\n"
            "Upload files or run `/index_range 1 50` to index your storage channel.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    buttons = []
    text_lines = ["📁 <b>Recently Indexed Files:</b>\n"]
    for i, f in enumerate(recent, 1):
        clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
        icon = get_file_type_icon(f.get("file_type", ""), clean_name)
        text_lines.append(f"{i}. {icon} <code>{html.escape(clean_name)}</code>")
        buttons.append([InlineKeyboardButton(f"📥 Get: {clean_name[:28]}", callback_data=f"getfile_{f['file_code']}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("\n".join(text_lines), reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def handle_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allow users to simply send any filename or keyword to find it."""
    message = update.effective_message
    if not message or not message.text:
        return

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

    db: Database = context.bot_data["db"]
    if not await check_user_access(db, query.from_user.id):
        await query.answer("🔒 Premium subscription required! Tap /plan to subscribe.", show_alert=True)
        return

    await query.answer("Fetching file...")

    file_code = query.data.removeprefix("getfile_").strip()
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
    user = update.effective_user
    if not message:
        return

    db: Database = context.bot_data["db"]
    if user and not await check_user_access(db, user.id):
        await send_paywall_alert(context.bot, message.chat_id, user.first_name)
        return
    if hasattr(db, "record_search_query"):
        try:
            await db.record_search_query(query)
        except Exception:
            pass
    matches = await db.search_files(query, limit=8)

    if not matches:
        await message.reply_text(
            f"🔍 No files found matching <b>\"{html.escape(query)}\"</b>.\n\n"
            "• Check spelling or try a shorter title/keyword.\n"
            "• Use <code>/files</code> to browse recent files in the catalog.",
            parse_mode=ParseMode.HTML,
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
    text_lines = [f"🔍 <b>Found {len(matches)} matching files for \"{html.escape(query)}\":</b>\n"]

    for i, f in enumerate(matches, 1):
        clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
        icon = get_file_type_icon(f.get("file_type", ""), clean_name)
        text_lines.append(f"{i}. {icon} <code>{html.escape(clean_name)}</code>")
        buttons.append([InlineKeyboardButton(f"📥 Get: {clean_name[:28]}", callback_data=f"getfile_{f['file_code']}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("\n".join(text_lines), reply_markup=reply_markup, parse_mode=ParseMode.HTML)
