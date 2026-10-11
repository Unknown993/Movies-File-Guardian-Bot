"""
Extra features module ported from MR.Guardian_bot / Professor-Bot:
- /json: Inspect raw Telegram message structure as JSON
- /font: Convert text into stylish/fancy Unicode fonts
- /share: Generate Telegram shareable links
- /password, /genpass: Secure password generator
- /written: Convert replied text into a downloadable document file
- /restart: Admin/Developer bot restart
- /set_template, /get_template: Custom IMDb and file caption template manager
- /dkick: Group cleanup for deleted accounts
- /instatus: Group member status inspector
- /inkick: Inactive member cleanup helper
"""

from __future__ import annotations

import os
import sys
import html
import json
import secrets
import string
import logging
from urllib.parse import quote
from typing import Optional

from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest, Forbidden

from config import is_admin, is_developer
from database import Database
from handlers.moderation_handlers import is_caller_admin

logger = logging.getLogger(__name__)


# =============================================================================
# 1. /json
# =============================================================================

async def json_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send formatted JSON representation of a message: /json [reply]."""
    message = update.effective_message
    if not message:
        return

    target_msg = message.reply_to_message or message
    if hasattr(target_msg, "to_dict") and callable(target_msg.to_dict):
        data = target_msg.to_dict()
    elif hasattr(target_msg, "__dict__"):
        data = {k: str(v) for k, v in target_msg.__dict__.items() if not k.startswith("_")}
    else:
        data = str(target_msg)
    json_text = json.dumps(data, indent=2, ensure_ascii=False, default=str)

    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✘ Cʟᴏsᴇ", callback_data="menu_close")]])
    escaped_json = html.escape(json_text)

    if len(escaped_json) <= 3800:
        await message.reply_text(f"<pre>{escaped_json}</pre>", parse_mode=ParseMode.HTML, reply_markup=btn)
    else:
        filename = f"message_{target_msg.message_id}.json"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(json_text)
            with open(filename, "rb") as doc_file:
                await message.reply_document(
                    document=doc_file,
                    caption=f"📋 Message JSON Dump ({len(json_text)} bytes)",
                    reply_markup=btn,
                )
        finally:
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception:
                pass


# =============================================================================
# 2. /font
# =============================================================================

# Unicode character translation dictionaries for stylish fonts
FONTS = {
    "Typewriter": {
        "a": "𝚊", "b": "𝚋", "c": "𝚌", "d": "𝚍", "e": "𝚎", "f": "𝚏", "g": "𝚐", "h": "𝚑", "i": "𝚒", "j": "𝚓", "k": "𝚔", "l": "𝚕", "m": "𝚖", "n": "𝚗", "o": "𝚘", "p": "𝚙", "q": "𝚚", "r": "𝚛", "s": "𝚜", "t": "𝚝", "u": "𝚞", "v": "𝚟", "w": "𝚠", "x": "𝚡", "y": "𝚢", "z": "𝚣",
        "A": "𝙰", "B": "𝙱", "C": "𝙲", "D": "𝙳", "E": "𝙴", "F": "𝙵", "G": "𝙶", "H": "𝙷", "I": "𝙸", "J": "𝙹", "K": "𝙺", "L": "𝙻", "M": "𝙼", "N": "𝙽", "O": "𝙾", "P": "𝙿", "Q": "𝚀", "R": "𝚁", "S": "𝚂", "T": "𝚃", "U": "𝚄", "V": "𝚅", "W": "𝚆", "X": "𝚇", "Y": "𝚈", "Z": "𝚉",
        "0": "𝟶", "1": "𝟷", "2": "𝟸", "3": "𝟹", "4": "𝟺", "5": "𝟻", "6": "𝟼", "7": "𝟽", "8": "𝟾", "9": "𝟿"
    },
    "Bold": {
        "a": "𝗮", "b": "𝗯", "c": "𝗰", "d": "𝗱", "e": "𝗲", "f": "𝗳", "g": "𝗴", "h": "𝗵", "i": "𝗶", "j": "𝗷", "k": "𝗸", "l": "𝗹", "m": "𝗺", "n": "𝗻", "o": "𝗼", "p": "𝗽", "q": "𝗾", "r": "𝗿", "s": "𝘀", "t": "𝘁", "u": "𝘂", "v": "𝘃", "w": "𝘄", "x": "𝘅", "y": "𝘆", "z": "𝘇",
        "A": "𝗔", "B": "𝗕", "C": "𝗖", "D": "𝗗", "E": "𝗘", "F": "𝗙", "G": "𝗚", "H": "𝗛", "I": "𝗜", "J": "𝗝", "K": "𝗞", "L": "𝗟", "M": "𝗠", "N": "𝗡", "O": "𝗢", "P": "𝗣", "Q": "𝗤", "R": "𝗥", "S": "𝗦", "T": "𝗧", "U": "𝗨", "V": "𝗩", "W": "𝗪", "X": "𝗫", "Y": "𝗬", "Z": "𝗭",
        "0": "𝟬", "1": "𝟭", "2": "𝟮", "3": "𝟯", "4": "𝟰", "5": "𝟱", "6": "𝟲", "7": "𝟳", "8": "𝟴", "9": "𝟵"
    },
    "Sans Serif": {
        "a": "𝖺", "b": "𝖻", "c": "𝖼", "d": "𝖽", "e": "𝖾", "f": "𝖿", "g": "𝗀", "h": "𝗁", "i": "𝗂", "j": "𝗃", "k": "𝗄", "l": "𝗅", "m": "𝗆", "n": "𝗇", "o": "𝗈", "p": "𝗉", "q": "𝗊", "r": "𝗋", "s": "𝗌", "t": "𝗍", "u": "𝗎", "v": "𝗏", "w": "𝗐", "x": "𝗑", "y": "𝗒", "z": "𝗓",
        "A": "𝖠", "B": "𝖡", "C": "𝖢", "D": "𝖣", "E": "𝖤", "F": "𝖥", "G": "𝖦", "H": "𝖧", "I": "𝖨", "J": "𝖩", "K": "𝖪", "L": "𝖫", "M": "𝖬", "N": "𝖭", "O": "𝖮", "P": "𝖯", "Q": "𝖰", "R": "𝖱", "S": "𝖲", "T": "𝖳", "U": "𝖴", "V": "𝖵", "W": "𝖶", "X": "𝖷", "Y": "𝖸", "Z": "𝖹",
        "0": "𝟢", "1": "𝟣", "2": "𝟤", "3": "𝟥", "4": "𝟦", "5": "𝟧", "6": "𝟨", "7": "𝟩", "8": "𝟪", "9": "𝟫"
    },
    "Script": {
        "a": "𝒶", "b": "𝒷", "c": "𝒸", "d": "𝒹", "e": "ℯ", "f": "𝒻", "g": "ℊ", "h": "𝒽", "i": "𝒾", "j": "𝒿", "k": "𝓀", "l": "𝓁", "m": "𝓂", "n": "𝓃", "o": "ℴ", "p": "𝓅", "q": "𝓆", "r": "𝓇", "s": "𝓈", "t": "𝓉", "u": "𝓊", "v": "𝓋", "w": "𝓌", "x": "𝓍", "y": "𝓎", "z": "𝓏",
        "A": "𝒜", "B": "ℬ", "C": "𝒞", "D": "𝒟", "E": "ℰ", "F": "ℱ", "G": "𝒢", "H": "ℋ", "I": "ℐ", "J": "𝒥", "K": "𝒦", "L": "ℒ", "M": "ℳ", "N": "𝒩", "O": "𝒪", "P": "𝒫", "Q": "𝒬", "R": "ℛ", "S": "𝒮", "T": "𝒯", "U": "𝒰", "V": "𝒱", "W": "𝒲", "X": "𝒳", "Y": "𝒴", "Z": "𝒵"
    },
    "Double Struck": {
        "a": "𝕒", "b": "𝕓", "c": "𝕔", "d": "𝕕", "e": "𝕖", "f": "𝕗", "g": "𝕘", "h": "𝕙", "i": "𝕚", "j": "𝕛", "k": "𝕜", "l": "𝕝", "m": "𝕞", "n": "𝕟", "o": "𝕠", "p": "𝕡", "q": "𝕢", "r": "𝕣", "s": "𝕤", "t": "𝕥", "u": "𝕦", "v": "𝕧", "w": "𝕨", "x": "𝕩", "y": "𝕪", "z": "𝕫",
        "A": "𝔸", "B": "𝔹", "C": "ℂ", "D": "𝔻", "E": "𝔼", "F": "𝔽", "G": "𝔾", "H": "ℍ", "I": "𝕀", "J": "𝕁", "K": "𝕂", "L": "𝕃", "M": "𝕄", "N": "ℕ", "O": "𝕆", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "S": "𝕊", "T": "𝕋", "U": "𝕌", "V": "𝕍", "W": "𝕎", "X": "𝕏", "Y": "𝕐", "Z": "ℤ",
        "0": "𝟘", "1": "𝟙", "2": "𝟚", "3": "𝟛", "4": "𝟜", "5": "𝟝", "6": "𝟞", "7": "𝟟", "8": "𝟠", "9": "𝟡"
    }
}

def transform_font(text: str, font_map: dict) -> str:
    return "".join(font_map.get(ch, ch) for ch in text)


async def font_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate stylish font variations: /font <text> or reply."""
    message = update.effective_message
    if not message:
        return

    text = " ".join(context.args or []).strip()
    if not text and message.reply_to_message:
        text = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()

    if not text:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/font &lt;text&gt;</code> or reply to a message with <code>/font</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = ["✨ <b>Stylish Font Variations:</b>\n"]
    for font_name, fmap in FONTS.items():
        styled = transform_font(text, fmap)
        lines.append(f"• <b>{html.escape(font_name)}:</b>\n<code>{html.escape(styled)}</code>\n")

    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# =============================================================================
# 3. /share
# =============================================================================

async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a shareable Telegram link with pre-filled text: /share <text>."""
    message = update.effective_message
    if not message:
        return

    text = " ".join(context.args or []).strip()
    if not text and message.reply_to_message:
        text = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()

    if not text:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/share &lt;text&gt;</code> or reply to a message with <code>/share</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    share_url = f"https://t.me/share/url?url={quote(text)}"
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Share Text", url=share_url)]])

    await message.reply_text(
        f"🔗 <b>Your Shareable Link is Ready:</b>\n\n<code>{html.escape(share_url)}</code>",
        reply_markup=btn,
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 4. /password & /genpass
# =============================================================================

async def password_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a secure random password: /password [length]."""
    message = update.effective_message
    if not message:
        return

    length = 12
    if context.args and context.args[0].isdigit():
        length = max(6, min(64, int(context.args[0])))

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+=-"
    pw = "".join(secrets.choice(alphabet) for _ in range(length))

    await message.reply_text(
        f"🔐 <b>Secure Password Generated:</b>\n\n"
        f"• <b>Length:</b> <code>{length}</code>\n"
        f"• <b>Password:</b> <code>{html.escape(pw)}</code>\n\n"
        f"<i>(Tap on password to copy)</i>",
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 5. /written
# =============================================================================

async def written_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Write replied text to a downloadable file: /written <filename>."""
    message = update.effective_message
    if not message:
        return

    replied = message.reply_to_message
    content = (replied.text or replied.caption) if replied else None
    if not content:
        await message.reply_text(
            "📌 Reply to any text message with <code>/written &lt;filename.txt&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    filename = context.args[0].strip() if context.args else "output.txt"
    # Basic sanitize
    filename = os.path.basename(filename)
    if not filename.endswith((".txt", ".py", ".html", ".json", ".md", ".css", ".js")):
        filename += ".txt"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        with open(filename, "rb") as doc_file:
            await message.reply_document(
                document=doc_file,
                caption=f"📄 Created <code>{html.escape(filename)}</code> from replied text.",
                parse_mode=ParseMode.HTML,
            )
    finally:
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass


# =============================================================================
# 6. /restart
# =============================================================================

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restart bot process (Admin only): /restart."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        if message:
            await message.reply_text("⛔ Only bot administrators can use <code>/restart</code>.", parse_mode=ParseMode.HTML)
        return

    await message.reply_text("🔄 <b>Restarting bot server...</b>\nPlease wait 5–10 seconds.", parse_mode=ParseMode.HTML)
    logger.info("Restart requested by user %s. Relaunching Python process...", user.id)

    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        logger.error("Failed to execv restart: %s", e)
        await message.reply_text(f"❌ Restart failed: <code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


# =============================================================================
# 7. /set_template & /get_template
# =============================================================================

async def set_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set custom IMDb / Auto-Filter template for group: /set_template <template>."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    db: Database = context.bot_data["db"]
    target_chat_id = chat.id

    if chat.type == ChatType.PRIVATE:
        active_id = await db.get_active_connection(user.id)
        if not active_id:
            await message.reply_text(
                "❌ You have no active group connection in PM. Use <code>/connect &lt;group_id&gt;</code> first.",
                parse_mode=ParseMode.HTML,
            )
            return
        target_chat_id = active_id
    else:
        if not await is_caller_admin(update):
            await message.reply_text("⛔ Only group administrators can configure templates.", parse_mode=ParseMode.HTML)
            return

    template_text = " ".join(context.args or []).strip()
    if not template_text:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/set_template &lt;template text&gt;</code>\n"
            "Example: <code>/set_template 🎬 {title} ({year}) | Rating: {rating}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await db.save_group_settings(target_chat_id, "template", template_text)
    await message.reply_text(
        f"✅ <b>Template updated for chat <code>{target_chat_id}</code>:</b>\n\n<pre>{html.escape(template_text)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def get_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get currently active template for group: /get_template."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    db: Database = context.bot_data["db"]
    target_chat_id = chat.id

    if chat.type == ChatType.PRIVATE:
        active_id = await db.get_active_connection(user.id)
        if active_id:
            target_chat_id = active_id

    settings = await db.get_group_settings(target_chat_id)
    tmpl = settings.get("template") or "Default Template"

    await message.reply_text(
        f"📋 <b>Current Template for Chat <code>{target_chat_id}</code>:</b>\n\n<pre>{html.escape(tmpl)}</pre>",
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# 8. /dkick, /instatus, /inkick (Group Moderation Helpers)
# =============================================================================

async def dkick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kick all deleted accounts from group: /dkick."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/dkick</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can run <code>/dkick</code>.", parse_mode=ParseMode.HTML)
        return

    status_msg = await message.reply_text("🧹 <b>Scanning chat for Deleted Accounts...</b>", parse_mode=ParseMode.HTML)

    try:
        admins = await chat.get_administrators()
        kicked = 0
        for admin in admins:
            if admin.user.is_deleted:
                try:
                    await chat.ban_member(user_id=admin.user.id)
                    kicked += 1
                except Exception:
                    pass
        await status_msg.edit_text(
            f"✅ <b>Deleted Accounts Cleanup Complete!</b>\n• Removed: <code>{kicked}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await status_msg.edit_text(
            f"❌ Failed to scan deleted accounts: <code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )


async def instatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inspect chat status and administrators: /instatus."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return

    target_chat = chat
    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        db: Database = context.bot_data.get("db")
        active_id = await db.get_active_connection(user.id) if db else None
        if not active_id:
            await message.reply_text(
                "ℹ️ Use <code>/instatus</code> inside a group chat, or connect a group first with <code>/connect &lt;group_id&gt;</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        try:
            target_chat = await context.bot.get_chat(active_id)
        except Exception as e:
            await message.reply_text(
                f"❌ Could not inspect connected group <code>{active_id}</code>: <code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
    else:
        if not await is_caller_admin(update):
            await message.reply_text("⛔ Only group administrators can use <code>/instatus</code>.", parse_mode=ParseMode.HTML)
            return

    try:
        member_count = await target_chat.get_member_count()
        admins = await target_chat.get_administrators()
        bots = sum(1 for a in admins if a.user.is_bot)

        text = (
            f"📊 <b>Chat Status for {html.escape(target_chat.title or str(target_chat.id))}</b>\n\n"
            f"• <b>Chat ID:</b> <code>{target_chat.id}</code>\n"
            f"• <b>Total Members:</b> <code>{member_count}</code>\n"
            f"• <b>Administrators:</b> <code>{len(admins)}</code>\n"
            f"• <b>Admin Bots:</b> <code>{bots}</code>"
        )
        await message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply_text(
            f"❌ Failed to fetch group status: <code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )


async def inkick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Informative inactive member sweep notice: /inkick."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text("ℹ️ <code>/inkick</code> can only be used inside a group chat.", parse_mode=ParseMode.HTML)
        return

    if not await is_caller_admin(update):
        await message.reply_text("⛔ Only group administrators can use <code>/inkick</code>.", parse_mode=ParseMode.HTML)
        return

    await message.reply_text(
        "ℹ️ Inactive member kick sweeps require Telegram native purge or client sessions. "
        "Use <code>/purge</code> for message cleanup or Telegram group settings.",
        parse_mode=ParseMode.HTML,
    )
