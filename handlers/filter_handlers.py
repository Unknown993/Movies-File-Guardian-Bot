"""
Filtering module:
1. Auto-Filter with paginated inline buttons and button-lock protection.
2. Manual Filters per group (/filter, /filters, /del, /delall).
3. Global Filters (/gfilter, /gfilters, /delg, /delallg).
"""

from __future__ import annotations

import hashlib
import html
import logging
import math
import difflib
from typing import Optional, Dict
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from config import BUTTON_LOCK_TEXT, DeliveryMode, is_developer, is_admin
from database import Database
from delivery import deliver_file_to_user, is_chat_allowed_for_download
from cleaner import smart_clean_filename, get_file_type_icon
from handlers.file_handlers import format_file_size
from handlers.payment_handlers import check_user_access, send_paywall_alert

logger = logging.getLogger(__name__)

# In-memory query hash cache to bypass Telegram's 64-byte callback_data limit
QUERY_CACHE: Dict[str, str] = {}
PAGE_SIZE = 6


def get_query_hash(query: str) -> str:
    """Generate a short hash for search query caching."""
    h = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()[:10]
    QUERY_CACHE[h] = query.strip()
    return h


def build_filter_keyboard(
    files: list,
    total_count: int,
    page: int,
    query_hash: str,
    req_user_id: int,
) -> InlineKeyboardMarkup:
    """Build paginated inline keyboard for auto-filter results."""
    buttons = []
    for f in files:
        clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
        size_str = format_file_size(f.get("file_size", 0))
        btn_text = f"[{size_str}] {clean_name[:26]}"
        buttons.append([
            InlineKeyboardButton(
                btn_text,
                callback_data=f"fl_{req_user_id}_{f['file_code']}",
            )
        ])

    # Pagination navigation row
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE))
    nav_row = []

    if page > 0:
        nav_row.append(
            InlineKeyboardButton("⬅️ Back", callback_data=f"fp_{req_user_id}_{query_hash}_{page - 1}")
        )

    nav_row.append(
        InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data=f"fp_noop_{req_user_id}")
    )

    if page + 1 < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"fp_{req_user_id}_{query_hash}_{page + 1}")
        )

    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(buttons)


# =============================================================================
# Auto-Filter & Custom Filter Message Interceptor
# =============================================================================

async def handle_filter_or_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Listens to incoming text messages in groups and PM (non-command).
    1. Checks custom manual and global keyword filters.
    2. If not matched, triggers the Auto-Filter search engine.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not message.text or not chat or not user:
        return

    # Ignore command messages
    if message.text.startswith("/"):
        return

    db: Database = context.bot_data["db"]

    # Check if user is banned
    is_banned, ban_reason = await db.is_user_banned(user.id)
    if is_banned:
        if chat.type == ChatType.PRIVATE:
            await message.reply_text(
                f"🚫 **Access Denied**\n\nYou are banned from using this bot.\n**Reason:** `{ban_reason}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # Check if chat is disabled
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        is_disabled, _ = await db.is_chat_disabled(chat.id)
        if is_disabled:
            return

    # Register user & chat
    await db.add_or_update_user(user.id, user.first_name, user.username)
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await db.add_or_update_chat(chat.id, chat.title, chat.type)

    # Check paywall access in private DM
    if chat.type == ChatType.PRIVATE and not await check_user_access(db, user.id):
        await send_paywall_alert(context.bot, chat.id, user.first_name)
        return

    query_text = message.text.strip()
    if len(query_text) < 2:
        return

    # 1. Check custom filters
    custom_filt = await db.get_filter(chat.id, query_text)
    if custom_filt:
        reply_txt = custom_filt.get("reply_text") or ""
        file_id = custom_filt.get("file_id")
        if file_id:
            try:
                await message.reply_document(document=file_id, caption=reply_txt)
                return
            except Exception:
                pass
        if reply_txt:
            await message.reply_text(reply_txt)
            return

    # 2. Trigger Auto-Filter
    offset = 0
    matches, total_count = await db.search_files_paginated(query_text, offset=offset, limit=PAGE_SIZE)
    if not matches:
        # Check spelling suggestions using difflib
        all_names = await db.get_all_filenames(limit=1000)
        candidates = set()
        for fn in all_names:
            c_name = smart_clean_filename(fn)
            candidates.add(c_name)
            for part in c_name.split():
                if len(part) >= 3:
                    candidates.add(part)
        close_matches = difflib.get_close_matches(query_text, list(candidates), n=4, cutoff=0.5)
        if close_matches:
            buttons = []
            for cm in close_matches:
                cm_hash = get_query_hash(cm)
                buttons.append([InlineKeyboardButton(f"🎬 {cm[:32]}", callback_data=f"fsp_{user.id}_{cm_hash}")])
            buttons.append([InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close")])
            await message.reply_text(
                f"🔍 I couldn't find any file matching <b>\"{html.escape(query_text)}\"</b>.\n\n"
                "<b>Did you mean any one of these?</b> 👇",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML,
            )
            return

        # In groups, do not spam if no file is found unless it's in PM
        if chat.type == ChatType.PRIVATE:
            await message.reply_text(
                f"🔍 No files found matching <b>\"{html.escape(query_text)}\"</b>.\n\n"
                "• Check your spelling.\n"
                "• Try searching with fewer words.",
                parse_mode=ParseMode.HTML,
            )
        return

    q_hash = get_query_hash(query_text)
    markup = build_filter_keyboard(
        files=matches,
        total_count=total_count,
        page=0,
        query_hash=q_hash,
        req_user_id=user.id,
    )

    caption = (
        f"🔍 <b>Found {total_count} file(s) for:</b> <code>{html.escape(query_text)}</code>\n"
        f"👤 <b>Requested by:</b> {html.escape(user.first_name or 'User')}"
    )

    await message.reply_text(
        caption,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# Callback Query Handlers (Pagination & Button Lock)
# =============================================================================

async def filter_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination clicks (fp_<user_id>_<query_hash>_<page>)."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    if data.startswith("fp_noop_"):
        await query.answer()
        return

    parts = data.split("_")
    if len(parts) < 4:
        return

    _, req_user_id_str, q_hash, page_str = parts[:4]
    req_user_id = int(req_user_id_str)
    page = int(page_str)

    # Button Lock check
    if query.from_user.id != req_user_id and not is_admin(query.from_user.id):
        alert_msg = BUTTON_LOCK_TEXT.format(name=query.from_user.first_name)
        await query.answer(alert_msg, show_alert=True)
        return

    search_query = QUERY_CACHE.get(q_hash)
    if not search_query:
        await query.answer("Session expired. Please search again.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    offset = page * PAGE_SIZE
    matches, total_count = await db.search_files_paginated(search_query, offset=offset, limit=PAGE_SIZE)

    if not matches:
        await query.answer("No more files found.", show_alert=True)
        return

    markup = build_filter_keyboard(
        files=matches,
        total_count=total_count,
        page=page,
        query_hash=q_hash,
        req_user_id=req_user_id,
    )

    caption = (
        f"🔍 <b>Found {total_count} file(s) for:</b> <code>{html.escape(search_query)}</code>\n"
        f"👤 <b>Requested by:</b> {html.escape(query.from_user.first_name or 'User')}"
    )

    try:
        await query.edit_message_text(
            caption,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await query.answer()


async def filter_file_click_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file button clicks (fl_<user_id>_<file_code>)."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split("_", 2)
    if len(parts) < 3:
        return

    _, req_user_id_str, file_code = parts
    req_user_id = int(req_user_id_str)

    # Button Lock check
    if query.from_user.id != req_user_id and not is_admin(query.from_user.id):
        alert_msg = BUTTON_LOCK_TEXT.format(name=query.from_user.first_name)
        await query.answer(alert_msg, show_alert=True)
        return

    db: Database = context.bot_data["db"]
    # Paywall Access Check
    if not await check_user_access(db, query.from_user.id):
        await query.answer("🔒 Premium subscription required! Tap /plan to subscribe.", show_alert=True)
        return

    file_record = await db.get_file_by_code(file_code)
    if not file_record:
        await query.answer("❌ File not found or expired.", show_alert=True)
        return

    bot_user = await context.bot.get_me()
    bot_username = bot_user.username or "Bot"
    curr_mode = await db.get_delivery_mode()
    chat_type = query.message.chat.type if query.message else ChatType.PRIVATE
    chat_id = query.message.chat_id if query.message else query.from_user.id

    # If clicked in group and delivery mode is Downloadable (Mode 2), redirect to DM
    if chat_type != ChatType.PRIVATE and curr_mode == DeliveryMode.DOWNLOADABLE:
        if not is_chat_allowed_for_download(chat_id, chat_type):
            dm_url = f"https://t.me/{bot_username}?start=file_{file_code}"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get File in Private DM", url=dm_url)]
            ])
            await query.message.reply_text(
                f"⚠️ <b>Self-Destruct File Delivery</b>\n\n"
                f"Hey {html.escape(query.from_user.first_name or 'User')}, this file is downloadable with self-destruct protection.\n"
                f"Click below to receive it securely in your private chat.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            await query.answer()
            return

    await query.answer("Delivering file...")
    await deliver_file_to_user(
        bot=context.bot,
        db=db,
        job_queue=context.job_queue,
        chat_id=chat_id,
        chat_type=chat_type,
        file_record=file_record,
        bot_username=bot_username,
    )


async def filter_spelling_click_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle clicking on a spelling suggestion button (fsp_<user_id>_<query_hash>)."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split("_")
    if len(parts) < 3:
        return

    _, req_user_id_str, q_hash = parts[:3]
    req_user_id = int(req_user_id_str)

    if query.from_user.id != req_user_id and not is_admin(query.from_user.id):
        alert_text = BUTTON_LOCK_TEXT.format(name=query.from_user.first_name)
        await query.answer(alert_text, show_alert=True)
        return

    search_query = QUERY_CACHE.get(q_hash)
    if not search_query:
        await query.answer("Query expired. Please search again.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    matches, total_count = await db.search_files_paginated(search_query, offset=0, limit=PAGE_SIZE)
    if not matches:
        await query.answer("No files found.", show_alert=True)
        return

    markup = build_filter_keyboard(
        files=matches,
        total_count=total_count,
        page=0,
        query_hash=q_hash,
        req_user_id=req_user_id,
    )
    caption = (
        f"🔍 <b>Found {total_count} file(s) for:</b> <code>{html.escape(search_query)}</code>\n"
        f"👤 <b>Requested by:</b> {html.escape(query.from_user.first_name or 'User')}"
    )
    try:
        await query.message.edit_text(caption, reply_markup=markup, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await query.answer()



# =============================================================================
# Manual Filters Commands (/filter, /filters, /del, /delall)
# =============================================================================

async def _resolve_filter_target_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, require_owner: bool = False) -> Optional[int]:
    """Resolve target group chat_id (from group chat or active PM connection) and check admin rights."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return None

    db: Database = context.bot_data["db"]

    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_id = chat.id
        if not is_admin(user.id):
            member = await chat.get_member(user.id)
            allowed = [ChatMemberStatus.OWNER] if require_owner else [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
            if member.status not in allowed:
                await message.reply_text("⛔ Only group administrators can manage filters.", parse_mode=ParseMode.HTML)
                return None
        return target_chat_id

    # In Private DM, check active /connect group connection
    active_id = await db.get_active_connection(user.id)
    if not active_id:
        await message.reply_text(
            "ℹ️ Use this command inside a group, or connect your group to PM first using <code>/connect &lt;group_id&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return None

    if not is_admin(user.id):
        try:
            member = await context.bot.get_chat_member(chat_id=active_id, user_id=user.id)
            allowed = [ChatMemberStatus.OWNER] if require_owner else [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
            if member.status not in allowed:
                await message.reply_text("⛔ Only group administrators can manage filters.", parse_mode=ParseMode.HTML)
                return None
        except Exception:
            await message.reply_text("❌ Could not verify your admin permissions in the connected group.", parse_mode=ParseMode.HTML)
            return None

    return active_id


async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a manual filter in a group: /filter <keyword> <reply> or reply to media."""
    message = update.effective_message
    if not message:
        return

    target_chat_id = await _resolve_filter_target_chat(update, context)
    if not target_chat_id:
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/filter &lt;keyword&gt; &lt;reply text&gt;</code>\n"
            "Or reply to any text/photo/document with <code>/filter &lt;keyword&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    keyword = args[0].strip().lower()
    reply_text = " ".join(args[1:]).strip() if len(args) > 1 else ""
    file_id = None

    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text and not reply_text:
            reply_text = replied.text
        elif replied.document:
            file_id = replied.document.file_id
            reply_text = reply_text or replied.caption or ""
        elif replied.photo:
            file_id = replied.photo[-1].file_id
            reply_text = reply_text or replied.caption or ""
        elif replied.video:
            file_id = replied.video.file_id
            reply_text = reply_text or replied.caption or ""

    if not reply_text and not file_id:
        await message.reply_text("❌ Please specify reply text or reply to a media message.", parse_mode=ParseMode.HTML)
        return

    db: Database = context.bot_data["db"]
    await db.add_filter(target_chat_id, keyword, reply_text, file_id)
    await message.reply_text(f"✅ Filter <b>\"{html.escape(keyword)}\"</b> added successfully!", parse_mode=ParseMode.HTML)


async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View all filters in a group: /filters."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    db: Database = context.bot_data["db"]
    target_chat_id = chat.id
    chat_label = chat.title or "this chat"

    if chat.type == ChatType.PRIVATE:
        active_id = await db.get_active_connection(user.id)
        if not active_id:
            await message.reply_text(
                "ℹ️ Use <code>/filters</code> inside a group, or connect a group first with <code>/connect &lt;group_id&gt;</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        target_chat_id = active_id
        chat_label = f"Chat {active_id}"

    filts = await db.get_chat_filters(target_chat_id)
    if not filts:
        await message.reply_text("📭 No custom filters found in this chat.", parse_mode=ParseMode.HTML)
        return

    lines = [f"📋 <b>Custom Filters for {html.escape(chat_label)}:</b>\n"]
    for i, f in enumerate(filts, 1):
        lines.append(f"{i}. <code>{html.escape(f['keyword'])}</code>")

    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def del_filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a specific filter: /del <keyword>."""
    message = update.effective_message
    if not message:
        return

    target_chat_id = await _resolve_filter_target_chat(update, context)
    if not target_chat_id:
        return

    args = context.args or []
    if not args:
        await message.reply_text("📌 <b>Usage:</b> <code>/del &lt;keyword&gt;</code>", parse_mode=ParseMode.HTML)
        return

    kw = args[0].strip().lower()
    db: Database = context.bot_data["db"]
    deleted = await db.delete_filter(target_chat_id, kw)
    if deleted:
        await message.reply_text(f"🗑️ Filter <b>\"{html.escape(kw)}\"</b> deleted.", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"❌ Filter <b>\"{html.escape(kw)}\"</b> not found.", parse_mode=ParseMode.HTML)


async def delall_filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete all filters in a group: /delall."""
    message = update.effective_message
    if not message:
        return

    target_chat_id = await _resolve_filter_target_chat(update, context, require_owner=True)
    if not target_chat_id:
        return

    db: Database = context.bot_data["db"]
    count = await db.delete_all_filters(target_chat_id)
    await message.reply_text(f"🗑️ Cleared <code>{count}</code> filters from this group.", parse_mode=ParseMode.HTML)


# =============================================================================
# Global Filters Commands (/gfilter, /gfilters, /delg, /delallg)
# =============================================================================

async def gfilter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a global filter across all groups: /gfilter <keyword> <reply>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    args = context.args or []
    if not args:
        await message.reply_text("📌 <b>Usage:</b> <code>/gfilter &lt;keyword&gt; &lt;reply text&gt;</code>", parse_mode=ParseMode.HTML)
        return

    keyword = args[0].strip().lower()
    reply_text = " ".join(args[1:]).strip() if len(args) > 1 else ""
    file_id = None

    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.text and not reply_text:
            reply_text = replied.text
        elif replied.document:
            file_id = replied.document.file_id
            reply_text = reply_text or replied.caption or ""
        elif replied.photo:
            file_id = replied.photo[-1].file_id
            reply_text = reply_text or replied.caption or ""

    if not reply_text and not file_id:
        await message.reply_text("❌ Provide reply text or reply to a media message.", parse_mode=ParseMode.HTML)
        return

    db: Database = context.bot_data["db"]
    await db.add_filter(0, keyword, reply_text, file_id)
    await message.reply_text(f"🌐 Global filter <b>\"{html.escape(keyword)}\"</b> created!", parse_mode=ParseMode.HTML)


async def gfilters_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all global filters: /gfilters."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    filts = await db.get_global_filters()
    if not filts:
        await message.reply_text("📭 No global filters set.", parse_mode=ParseMode.HTML)
        return

    lines = ["🌐 <b>Global Filters:</b>\n"]
    for i, f in enumerate(filts, 1):
        lines.append(f"{i}. <code>{html.escape(f['keyword'])}</code>")

    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def delg_filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a global filter: /delg <keyword>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    args = context.args or []
    if not args:
        await message.reply_text("📌 <b>Usage:</b> <code>/delg &lt;keyword&gt;</code>", parse_mode=ParseMode.HTML)
        return

    kw = args[0].strip().lower()
    db: Database = context.bot_data["db"]
    deleted = await db.delete_filter(0, kw)
    if deleted:
        await message.reply_text(f"🗑️ Global filter <b>\"{html.escape(kw)}\"</b> deleted.", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"❌ Global filter <b>\"{html.escape(kw)}\"</b> not found.", parse_mode=ParseMode.HTML)


async def delallg_filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete all global filters: /delallg."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    db: Database = context.bot_data["db"]
    count = await db.delete_all_filters(0)
    await message.reply_text(f"🗑️ Deleted all <code>{count}</code> global filters.", parse_mode=ParseMode.HTML)
