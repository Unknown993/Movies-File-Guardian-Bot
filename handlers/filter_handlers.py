"""
Filtering module:
1. Auto-Filter with Quality, Language, Season, Send All, Button/Text Mode, and button-lock protection.
2. Manual Filters per group (/filter, /filters, /del, /delall).
3. Global Filters (/gfilter, /gfilters, /delg, /delallg).
"""

from __future__ import annotations

import time
import hashlib
import html
import logging
import math
import difflib
from typing import Optional, Dict, List
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from config import (
    BUTTON_LOCK_TEXT,
    QUALITIES,
    LANGUAGES,
    SEASONS,
    DeliveryMode,
    is_developer,
    is_admin,
    send_work_log,
)
from database import Database
from delivery import deliver_file_to_user, is_chat_allowed_for_download
from cleaner import smart_clean_filename, get_file_type_icon
from handlers.file_handlers import format_file_size
from handlers.payment_handlers import check_user_access, send_paywall_alert

logger = logging.getLogger(__name__)

# In-memory query hash cache to bypass Telegram's 64-byte callback_data limit
QUERY_CACHE: Dict[str, str] = {}
PAGE_SIZE = 8


def get_query_hash(query: str) -> str:
    """Generate a short hash for search query caching."""
    h = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()[:10]
    QUERY_CACHE[h] = query.strip()
    return h


def build_filter_result_caption(
    query_text: str,
    total_count: int,
    user_first_name: str,
    elapsed_sec: float = 0.02,
    files: Optional[list] = None,
    button_mode: bool = True,
    bot_username: str = "Bot",
) -> str:
    """Build detailed header (and optional text-mode links) matching Premium_Guardian."""
    safe_q = html.escape(query_text)
    safe_user = html.escape(user_first_name or "User")
    header = (
        f"🏷 <b>Tɪᴛʟᴇ :</b> <code>{safe_q}</code>\n"
        f"🧱 <b>Tᴏᴛᴀʟ Fɪʟᴇs :</b> <code>{total_count}</code>\n"
        f"⏰ <b>Rᴇsᴜʟᴛ Iɴ :</b> <code>{elapsed_sec:.2f} Sᴇᴄᴏɴᴅs</code>\n"
        f"📝 <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> {safe_user}"
    )

    if not button_mode and files:
        link_lines = ["\n"]
        for idx, f in enumerate(files, 1):
            clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
            size_str = format_file_size(f.get("file_size", 0))
            url = f"https://t.me/{bot_username}?start=file_{f['file_code']}"
            link_lines.append(
                f"{idx}. <a href='{url}'>[{html.escape(size_str)}] {html.escape(clean_name)}</a>"
            )
        header += "\n".join(link_lines)

    return header


def build_filter_keyboard(
    files: list,
    total_count: int,
    page: int,
    query_hash: str,
    req_user_id: int,
    button_mode: bool = True,
    page_size: int = PAGE_SIZE,
) -> InlineKeyboardMarkup:
    """
    Build paginated inline keyboard for auto-filter results, including:
    - Row 1: Remove Ads / VIP | Send All
    - Row 2: Quality | Language | Season
    - File rows (when button_mode=True)
    - Pagination navigation row
    """
    buttons = [
        [
            InlineKeyboardButton("💎 VIP / Rᴇᴍᴏᴠᴇ Aᴅs", callback_data="show_plans"),
            InlineKeyboardButton("📦 Sᴇɴᴅ Aʟʟ", callback_data=f"fall_{req_user_id}_{query_hash}_{page}"),
        ],
        [
            InlineKeyboardButton("🎬 Qᴜᴀʟɪᴛʏ", callback_data=f"fqm_{req_user_id}_{query_hash}"),
            InlineKeyboardButton("🌐 Lᴀɴɢᴜᴀɢᴇ", callback_data=f"flm_{req_user_id}_{query_hash}"),
            InlineKeyboardButton("📺 Sᴇᴀsᴏɴ", callback_data=f"fsm_{req_user_id}_{query_hash}"),
        ],
    ]

    if button_mode:
        for f in files:
            clean_name = smart_clean_filename(f.get("file_name") or f.get("caption"))
            size_str = format_file_size(f.get("file_size", 0))
            btn_text = f"🔗 {size_str} ≽ {clean_name[:28]}"
            buttons.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"fl_{req_user_id}_{f['file_code']}",
                )
            ])

    # Pagination navigation row
    effective_page_size = max(1, page_size)
    total_pages = max(1, math.ceil(total_count / effective_page_size))
    nav_row = []

    if page > 0:
        nav_row.append(
            InlineKeyboardButton("⬅️ Bᴀᴄᴋ", callback_data=f"fp_{req_user_id}_{query_hash}_{page - 1}")
        )

    nav_row.append(
        InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data=f"fp_noop_{req_user_id}")
    )

    if page + 1 < total_pages:
        nav_row.append(
            InlineKeyboardButton("Nᴇxᴛ ➡️", callback_data=f"fp_{req_user_id}_{query_hash}_{page + 1}")
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
    1. Checks #request / #req tags.
    2. Checks custom manual and global keyword filters.
    3. If not matched, triggers the Auto-Filter search engine.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not message.text or not chat or not user:
        return

    if message.text.startswith("/"):
        return

    # Support #request or #req hashtag in groups/PM
    lower_txt = message.text.strip().lower()
    if lower_txt.startswith("#request") or lower_txt.startswith("#req"):
        from handlers.extended_commands import request_command
        await request_command(update, context)
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

    # Register user & chat (and log #NewGroup if brand new group)
    await db.add_or_update_user(user.id, user.first_name, user.username)
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        is_new_chat = await db.add_or_update_chat(chat.id, chat.title, chat.type)
        if is_new_chat:
            await send_work_log(
                context.bot,
                db,
                f"👥 <b>#NewGroup</b>\n\n"
                f"🏷 <b>Tɪᴛʟᴇ:</b> {html.escape(chat.title or 'Group')}\n"
                f"🆔 <b>Cʜᴀᴛ ID:</b> <code>{chat.id}</code>\n"
                f"👤 <b>Aᴄᴛɪᴠᴀᴛᴇᴅ Bʏ:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a>",
            )

    # Check paywall access in private DM
    if chat.type == ChatType.PRIVATE and not await check_user_access(db, user.id):
        await send_paywall_alert(context.bot, chat.id, user.first_name)
        return

    # Check if PM Search is disabled by admin
    if chat.type == ChatType.PRIVATE and not is_admin(user.id):
        if hasattr(db, "get_pm_search_enabled") and not await db.get_pm_search_enabled():
            await message.reply_text(
                "⚠️ <b>PM Sᴇᴀʀᴄʜ Is Cᴜʀʀᴇɴᴛʟʏ Dɪsᴀʙʟᴇᴅ!</b>\n\n"
                "Pʟᴇᴀsᴇ sᴇᴀʀᴄʜ ғᴏʀ ᴍᴏᴠɪᴇs ᴀɴᴅ sᴇʀɪᴇs ɪɴ ᴏᴜʀ official ᴍᴏᴠɪᴇ ɢʀᴏᴜᴘ.",
                parse_mode=ParseMode.HTML,
            )
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

    # Fetch group settings if in group
    grp_settings = await db.get_group_settings(chat.id) if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] else {
        "button": True,
        "spell_check": True,
        "auto_ffilter": True,
        "max_btn": True,
    }
    if not grp_settings.get("auto_ffilter", True):
        return

    page_size = 10 if grp_settings.get("max_btn", True) else 6
    button_mode = grp_settings.get("button", True)

    # Record search query in trending history
    if hasattr(db, "record_search_query"):
        try:
            await db.record_search_query(query_text)
        except Exception:
            pass

    # 2. Trigger Auto-Filter
    t0 = time.perf_counter()
    matches, total_count = await db.search_files_paginated(query_text, offset=0, limit=page_size)
    elapsed = max(0.01, time.perf_counter() - t0)

    if not matches:
        # Check spelling suggestions using difflib if spell_check is enabled
        if grp_settings.get("spell_check", True):
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

        if len(query_text) >= 3:
            await send_work_log(
                context.bot,
                db,
                f"🔍 <b>#NoResults</b>\n\n"
                f"👤 <b>Usᴇʀ:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a> (<code>{user.id}</code>)\n"
                f"💬 <b>Qᴜᴇʀʏ:</b> <code>{html.escape(query_text[:100])}</code>",
            )

        if chat.type == ChatType.PRIVATE:
            await message.reply_text(
                f"🔍 No files found matching <b>\"{html.escape(query_text)}\"</b>.\n\n"
                "• Check your spelling.\n"
                "• Try searching with fewer words.\n"
                "• Use <code>/request &lt;name&gt;</code> to request it from admins!",
                parse_mode=ParseMode.HTML,
            )
        return

    bot_me = await context.bot.get_me()
    bot_username = getattr(bot_me, "username", None) or "Bot"

    q_hash = get_query_hash(query_text)
    markup = build_filter_keyboard(
        files=matches,
        total_count=total_count,
        page=0,
        query_hash=q_hash,
        req_user_id=user.id,
        button_mode=button_mode,
        page_size=page_size,
    )

    caption = build_filter_result_caption(
        query_text=query_text,
        total_count=total_count,
        user_first_name=user.first_name or "User",
        elapsed_sec=elapsed,
        files=matches,
        button_mode=button_mode,
        bot_username=bot_username,
    )

    await message.reply_text(
        caption,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# =============================================================================
# Callback Query Handlers (Pagination, Quality, Language, Season, Send All)
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

    if query.from_user.id != req_user_id and not is_admin(query.from_user.id):
        alert_msg = BUTTON_LOCK_TEXT.format(name=query.from_user.first_name)
        await query.answer(alert_msg, show_alert=True)
        return

    search_query = QUERY_CACHE.get(q_hash)
    if not search_query:
        await query.answer("Session expired. Please search again.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    chat = query.message.chat if query.message else None
    grp_settings = await db.get_group_settings(chat.id) if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] else {
        "button": True,
        "max_btn": True,
    }
    page_size = 10 if grp_settings.get("max_btn", True) else 6
    button_mode = grp_settings.get("button", True)

    offset = page * page_size
    t0 = time.perf_counter()
    matches, total_count = await db.search_files_paginated(search_query, offset=offset, limit=page_size)
    elapsed = max(0.01, time.perf_counter() - t0)

    if not matches:
        await query.answer("No more files found.", show_alert=True)
        return

    bot_me = await context.bot.get_me()
    bot_username = getattr(bot_me, "username", None) or "Bot"

    markup = build_filter_keyboard(
        files=matches,
        total_count=total_count,
        page=page,
        query_hash=q_hash,
        req_user_id=req_user_id,
        button_mode=button_mode,
        page_size=page_size,
    )

    caption = build_filter_result_caption(
        query_text=search_query,
        total_count=total_count,
        user_first_name=query.from_user.first_name or "User",
        elapsed_sec=elapsed,
        files=matches,
        button_mode=button_mode,
        bot_username=bot_username,
    )

    try:
        await query.edit_message_text(
            caption,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await query.answer()


async def filter_extra_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle Quality, Language, Season menus & selections, plus Send All:
    - fqm_<uid>_<qhash> : Open Quality Menu
    - fqs_<uid>_<qhash>_<quality> : Filter by Quality
    - flm_<uid>_<qhash> : Open Language Menu
    - fls_<uid>_<qhash>_<lang> : Filter by Language
    - fsm_<uid>_<qhash> : Open Season Menu
    - fss_<uid>_<qhash>_<season> : Filter by Season
    - fall_<uid>_<qhash>_<page> : Send All files on current page
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        return

    prefix = parts[0]
    req_user_id = int(parts[1])
    q_hash = parts[2]

    # Button Lock check
    if query.from_user.id != req_user_id and not is_admin(query.from_user.id):
        alert_msg = BUTTON_LOCK_TEXT.format(name=query.from_user.first_name)
        await query.answer(alert_msg, show_alert=True)
        return

    base_query = QUERY_CACHE.get(q_hash)
    if not base_query:
        await query.answer("Session expired. Please search again.", show_alert=True)
        return

    db: Database = context.bot_data["db"]

    # 1. Quality Menu
    if prefix == "fqm":
        rows = []
        row = []
        for q in QUALITIES:
            row.append(InlineKeyboardButton(q, callback_data=f"fqs_{req_user_id}_{q_hash}_{q.lower()}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("« Bᴀᴄᴋ Tᴏ Rᴇsᴜʟᴛs", callback_data=f"fp_{req_user_id}_{q_hash}_0")])
        text = (
            f"🎬 <b><u>Sᴇʟᴇᴄᴛ Vɪᴅᴇᴏ Qᴜᴀʟɪᴛʏ</u></b>\n\n"
            f"🏷 <b>Tɪᴛʟᴇ:</b> <code>{html.escape(base_query)}</code>\n"
            f"👇 <i>Cʜᴏᴏsᴇ ʏᴏᴜʀ ᴘʀᴇғᴇʀʀᴇᴅ ʀᴇsᴏʟᴜᴛɪᴏɴ:</i>"
        )
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 2. Language Menu
    if prefix == "flm":
        rows = []
        row = []
        for label, lang_kw in LANGUAGES.items():
            row.append(InlineKeyboardButton(label, callback_data=f"fls_{req_user_id}_{q_hash}_{lang_kw}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("« Bᴀᴄᴋ Tᴏ Rᴇsᴜʟᴛs", callback_data=f"fp_{req_user_id}_{q_hash}_0")])
        text = (
            f"🌐 <b><u>Sᴇʟᴇᴄᴛ Aᴜᴅɪᴏ Lᴀɴɢᴜᴀɢᴇ</u></b>\n\n"
            f"🏷 <b>Tɪᴛʟᴇ:</b> <code>{html.escape(base_query)}</code>\n"
            f"👇 <i>Cʜᴏᴏsᴇ ʏᴏᴜʀ ᴘʀᴇғᴇʀʀᴇᴅ ʟᴀɴɢᴜᴀɢᴇ:</i>"
        )
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 3. Season Menu
    if prefix == "fsm":
        rows = []
        row = []
        for s in SEASONS:
            row.append(InlineKeyboardButton(s, callback_data=f"fss_{req_user_id}_{q_hash}_{s.lower()}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("« Bᴀᴄᴋ Tᴏ Rᴇsᴜʟᴛs", callback_data=f"fp_{req_user_id}_{q_hash}_0")])
        text = (
            f"📺 <b><u>Sᴇʟᴇᴄᴛ Sᴇᴀsᴏɴ</u></b>\n\n"
            f"🏷 <b>Tɪᴛʟᴇ:</b> <code>{html.escape(base_query)}</code>\n"
            f"👇 <i>Cʜᴏᴏsᴇ ᴛʜᴇ sᴇᴀsᴏɴ ʏᴏᴜ ᴡᴀɴᴛ:</i>"
        )
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer()
        return

    # 4. Quality / Language / Season Selection
    if prefix in ("fqs", "fls", "fss") and len(parts) >= 4:
        modifier = parts[3]
        refined_query = f"{base_query} {modifier}".strip()
        chat = query.message.chat if query.message else None
        grp_settings = await db.get_group_settings(chat.id) if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] else {
            "button": True,
            "max_btn": True,
        }
        page_size = 10 if grp_settings.get("max_btn", True) else 6
        button_mode = grp_settings.get("button", True)

        t0 = time.perf_counter()
        matches, total_count = await db.search_files_paginated(refined_query, offset=0, limit=page_size)
        elapsed = max(0.01, time.perf_counter() - t0)

        if not matches:
            await query.answer(f"❌ No files found for '{refined_query}'.", show_alert=True)
            return

        new_hash = get_query_hash(refined_query)
        bot_me = await context.bot.get_me()
        bot_username = getattr(bot_me, "username", None) or "Bot"

        markup = build_filter_keyboard(
            files=matches,
            total_count=total_count,
            page=0,
            query_hash=new_hash,
            req_user_id=req_user_id,
            button_mode=button_mode,
            page_size=page_size,
        )
        caption = build_filter_result_caption(
            query_text=refined_query,
            total_count=total_count,
            user_first_name=query.from_user.first_name or "User",
            elapsed_sec=elapsed,
            files=matches,
            button_mode=button_mode,
            bot_username=bot_username,
        )
        try:
            await query.edit_message_text(
                caption,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
        await query.answer(f"✅ Filtered by {modifier.upper()}!")
        return

    # 5. Send All Files on Current Page
    if prefix == "fall":
        page = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0
        if not await check_user_access(db, query.from_user.id):
            await query.answer("🔒 Premium subscription required! Tap /plan to subscribe.", show_alert=True)
            return

        chat = query.message.chat if query.message else None
        grp_settings = await db.get_group_settings(chat.id) if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] else {
            "max_btn": True,
        }
        page_size = 10 if grp_settings.get("max_btn", True) else 6
        offset = page * page_size
        matches, _ = await db.search_files_paginated(base_query, offset=offset, limit=page_size)
        if not matches:
            await query.answer("No files found on this page.", show_alert=True)
            return

        bot_me = await context.bot.get_me()
        bot_username = getattr(bot_me, "username", None) or "Bot"
        await query.answer(f"📦 Sending {len(matches)} file(s)...")

        target_chat_id = query.from_user.id
        target_chat_type = ChatType.PRIVATE
        delivered_count = 0

        for f_rec in matches:
            ok = await deliver_file_to_user(
                bot=context.bot,
                db=db,
                job_queue=context.job_queue,
                chat_id=target_chat_id,
                chat_type=target_chat_type,
                file_record=f_rec,
                bot_username=bot_username,
            )
            if ok:
                delivered_count += 1

        if chat and chat.type != ChatType.PRIVATE:
            if delivered_count > 0:
                await query.message.reply_text(
                    f"✅ Hey {html.escape(query.from_user.first_name or 'User')}, I have sent <b>{delivered_count}</b> file(s) to your Private Chat!",
                    parse_mode=ParseMode.HTML,
                )
            else:
                start_url = f"https://t.me/{bot_username}?start=help"
                await query.message.reply_text(
                    f"⚠️ Hey {html.escape(query.from_user.first_name or 'User')}, please start me in Private Chat first so I can send all files to you!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤖 Start Bot in PM", url=start_url)]]),
                    parse_mode=ParseMode.HTML,
                )


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
    t0 = time.perf_counter()
    matches, total_count = await db.search_files_paginated(search_query, offset=0, limit=PAGE_SIZE)
    elapsed = max(0.01, time.perf_counter() - t0)
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
    caption = build_filter_result_caption(
        query_text=search_query,
        total_count=total_count,
        user_first_name=query.from_user.first_name or "User",
        elapsed_sec=elapsed,
        files=matches,
    )
    try:
        await query.message.edit_text(caption, reply_markup=markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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
