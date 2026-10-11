"""
Configuration module for Telegram File Delivery & Content Protection Bot.
Loads environment variables and validates developer settings.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Set, Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file in project directory
load_dotenv(BASE_DIR / ".env")


class DeliveryMode(str, Enum):
    """
    File Delivery Modes:
    - VIEW_ONLY: Mode 1 (Default). protect_content=True.
      Prevents forwarding, copying, and saving. Streaming/viewing in Telegram player only.
    - DOWNLOADABLE: Mode 2. copy_message(..., protect_content=False).
      Source metadata stripped, auto-destruct timer attached, restricted to private DM / temp channels.
    """
    VIEW_ONLY = "view_only"
    DOWNLOADABLE = "downloadable"

    @classmethod
    def from_str(cls, value: str) -> DeliveryMode:
        val = value.strip().lower()
        if val in ("view_only", "view", "protected", "mode1", "1"):
            return cls.VIEW_ONLY
        elif val in ("downloadable", "download", "auto_delete", "mode2", "2"):
            return cls.DOWNLOADABLE
        raise ValueError(
            f"Invalid delivery mode '{value}'. Allowed values are 'view_only' or 'downloadable'."
        )


def _parse_int_set(raw_value: Optional[str]) -> Set[int]:
    """Parse comma-separated integer IDs into a set."""
    if not raw_value:
        return set()
    result = set()
    for item in raw_value.split(","):
        cleaned = item.strip()
        if cleaned:
            try:
                result.add(int(cleaned))
            except ValueError:
                continue
    return result


# Telegram Bot Token
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

# Developer ID: Only this ID can switch delivery mode & access developer controls
_dev_id_raw = os.getenv("DEVELOPER_ID", "").strip()
DEVELOPER_ID: int = int(_dev_id_raw) if _dev_id_raw.isdigit() or (_dev_id_raw.startswith("-") and _dev_id_raw[1:].isdigit()) else 0

# Additional Admin IDs (developer ID is automatically included)
ADMIN_IDS: Set[int] = _parse_int_set(os.getenv("ADMIN_IDS"))
if DEVELOPER_ID:
    ADMIN_IDS.add(DEVELOPER_ID)

# Dedicated storage/mirror channel ID (e.g. -1001234567890)
_storage_id_raw = os.getenv("STORAGE_CHANNEL_ID", "").strip()
def _normalize_channel_id(val: str) -> Optional[int]:
    if not val or not val.lstrip("-").isdigit():
        return None
    num = int(val)
    if num > 0 and str(num).startswith("100"):
        num = -num
    return num

STORAGE_CHANNEL_ID: Optional[int] = _normalize_channel_id(_storage_id_raw)

# Dedicated Operational Log Channel (ONLY work-related logs: NewUser, NewGroup, VIP/Payments, Requests, Errors; NEVER file indexing)
_log_channel_raw = os.getenv("LOG_CHANNEL", "").strip()
LOG_CHANNEL: Optional[int] = _normalize_channel_id(_log_channel_raw)

_premium_logs_raw = os.getenv("PREMIUM_LOGS", "").strip()
PREMIUM_LOGS: Optional[int] = _normalize_channel_id(_premium_logs_raw) or LOG_CHANNEL

_reqst_channel_raw = os.getenv("REQST_CHANNEL_ID", "").strip()
REQST_CHANNEL_ID: Optional[int] = _normalize_channel_id(_reqst_channel_raw) or LOG_CHANNEL

_support_chat_raw = os.getenv("SUPPORT_CHAT_ID", "").strip()
SUPPORT_CHAT_ID: Optional[int] = _normalize_channel_id(_support_chat_raw)

# Links & Payment Info (from Premium_Guardian)
GRP_LNK: str = os.getenv("GRP_LNK", "https://t.me/")
UPDATE_CHNL_LNK: str = os.getenv("UPDATE_CHNL_LNK", "https://t.me/")
OWNER_LNK: str = os.getenv("OWNER_LNK", "https://t.me/Unknown993")
OWNER_UPI_ID: str = os.getenv("OWNER_UPI_ID", "Not configured (Use Telegram Stars ⭐ for Instant Auto-Activation)")
QR_CODE: str = os.getenv("QR_CODE", "https://graph.org/file/99eebf5dbe8a134f548e0.jpg")

# Auto-Filter Qualities, Languages, and Seasons (from Premium_Guardian)
QUALITIES = ["360P", "480P", "720P", "1080P", "1440P", "2160P", "4K"]
LANGUAGES = {
    "Hɪɴᴅɪ": "hindi",
    "Eɴɢʟɪsʜ": "english",
    "Tᴀᴍɪʟ": "tamil",
    "Tᴇʟᴜɢᴜ": "telugu",
    "Mᴀʟᴀʏᴀʟᴀᴍ": "malayalam",
    "Kᴀɴɴᴀᴅᴀ": "kannada",
    "Gᴜᴊᴀʀᴀᴛɪ": "gujarati",
    "Mᴀʀᴀᴛʜɪ": "marathi",
    "Pᴜɴᴊᴀʙɪ": "punjabi",
    "Dᴜᴀʟ Aᴜᴅɪᴏ": "dual",
}
SEASONS = [f"S{str(i).zfill(2)}" for i in range(1, 13)]

# Dedicated temporary download channels allowed for Mode 2 delivery
ALLOWED_TEMP_CHANNELS: Set[int] = _parse_int_set(os.getenv("ALLOWED_TEMP_CHANNELS"))

# Default Mode: "view_only" (Mode 1) or "downloadable" (Mode 2)
DEFAULT_DELIVERY_MODE: DeliveryMode = DeliveryMode.VIEW_ONLY
_default_mode_env = os.getenv("DEFAULT_DELIVERY_MODE", "").strip()
if _default_mode_env:
    try:
        DEFAULT_DELIVERY_MODE = DeliveryMode.from_str(_default_mode_env)
    except ValueError:
        DEFAULT_DELIVERY_MODE = DeliveryMode.VIEW_ONLY

# Default auto-delete timer for Mode 2 (in seconds, e.g. 180 for 3 min, 300 for 5 min)
try:
    DEFAULT_AUTO_DELETE_SECONDS: int = int(os.getenv("DEFAULT_AUTO_DELETE_SECONDS", "180"))
    if DEFAULT_AUTO_DELETE_SECONDS <= 0:
        DEFAULT_AUTO_DELETE_SECONDS = 180
except ValueError:
    DEFAULT_AUTO_DELETE_SECONDS = 180

# Force Subscription Channel (e.g. -1001234567890 or @channelname)
_auth_channel_raw = os.getenv("AUTH_CHANNEL_ID", "").strip()
AUTH_CHANNEL_ID: Optional[int | str] = None
if _auth_channel_raw:
    if _auth_channel_raw.lstrip("-").isdigit():
        AUTH_CHANNEL_ID = _normalize_channel_id(_auth_channel_raw)
    else:
        AUTH_CHANNEL_ID = _auth_channel_raw if _auth_channel_raw.startswith("@") else f"@{_auth_channel_raw}"

# Welcome Greetings Configuration
WELCOME_TEXT: str = os.getenv(
    "WELCOME_TEXT",
    "👋 Hey {user}!\n\nWelcome to **{chat}**! 🎉\nEnjoy your stay and search or request any files you need."
)
WELCOME_PIC: Optional[str] = os.getenv("WELCOME_PIC", "").strip() or None

# Force Subscription Text
FORCE_SUB_TEXT: str = os.getenv(
    "FORCE_SUB_TEXT",
    "⚠️ **Channel Membership Required**\n\n"
    "To access files and use this bot, you must join our official channel.\n"
    "Please join using the link below, then tap **Try Again**."
)

# Button Lock Alert
BUTTON_LOCK_TEXT: str = os.getenv(
    "BUTTON_LOCK_TEXT",
    "⚠️ Hey {name}, this search result is not for you! Please search for yourself."
)

# SQLite Database Path
DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "bot_database.sqlite3")


def is_developer(user_id: int) -> bool:
    """Check if the given Telegram user ID is the authorized Developer."""
    return DEVELOPER_ID > 0 and user_id == DEVELOPER_ID


def is_admin(user_id: int) -> bool:
    """Check if the given Telegram user ID is an admin or the developer."""
    return user_id in ADMIN_IDS


# Paywall / Paid-Only Access Control Configuration
_paywall_env = os.getenv("PAYWALL_ENABLED", "0").strip().lower()
DEFAULT_PAYWALL_ENABLED: bool = _paywall_env in ("1", "true", "yes", "on")

PAYWALL_ALERT_TEXT: str = os.getenv(
    "PAYWALL_ALERT_TEXT",
    "🔒 <b><u>ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ ʀᴇǫᴜɪʀᴇᴅ</u></b>\n\n"
    "👋 ʜᴇʏ {name}, ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ᴄᴜʀʀᴇɴᴛʟʏ ɪɴ <b><u>ᴘᴀɪᴅ ᴍᴇᴍʙᴇʀꜱ ᴏɴʟʏ</u></b> ᴍᴏᴅᴇ.\n\n"
    "✨ <b><u>ᴘʀᴇᴍɪᴜᴍ ʙᴇɴᴇꜰɪᴛꜱ:</u></b>\n"
    "• ⚡ ɪɴꜱᴛᴀɴᴛ ᴅɪʀᴇᴄᴛ ꜰɪʟᴇꜱ (ɴᴏ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʟɪɴᴋꜱ)\n"
    "• 📂 ᴜɴʟɪᴍɪᴛᴇᴅ ᴍᴏᴠɪᴇꜱ & ꜱᴇʀɪᴇꜱ ᴅᴏᴡɴʟᴏᴀᴅꜱ\n"
    "• 🖥️ ʜɪɢʜ-ꜱᴘᴇᴇᴅ ᴏɴʟɪɴᴇ ꜱᴛʀᴇᴀᴍɪɴɢ\n"
    "• 🚫 100% ᴀᴅ-ꜰʀᴇᴇ ᴇxᴘᴇʀɪᴇɴᴄᴇ\n\n"
    "💳 ꜱᴇʟᴇᴄᴛ ᴀ ᴘʟᴀɴ ʙᴇʟᴏᴡ ꜰᴏʀ <b><u>ɪɴꜱᴛᴀɴᴛ ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴀᴄᴛɪᴠᴀᴛɪᴏɴ</u></b> ᴠɪᴀ ᴛᴇʟᴇɢʀᴀᴍ ꜱᴛᴀʀꜱ ⭐!"
)


def get_ist_greeting() -> str:
    """Return time-of-day greeting in Asia/Kolkata (IST) matching Premium_Guardian."""
    from datetime import datetime, timezone, timedelta
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    hour = ist_now.hour
    if 5 <= hour < 12:
        return "Gᴏᴏᴅ Mᴏʀɴɪɴɢ 🌞"
    elif 12 <= hour < 17:
        return "Gᴏᴏᴅ Aғᴛᴇʀɴᴏᴏɴ ☀️"
    elif 17 <= hour < 21:
        return "Gᴏᴏᴅ Eᴠᴇɴɪɴɢ 🌇"
    else:
        return "Gᴏᴏᴅ Nɪɢʜᴛ 🌙"


async def send_work_log(
    bot,
    db,
    text: str,
    reply_markup=None,
    channel_override: Optional[int] = None,
) -> None:
    """
    Send strictly work-related operational logs to LOG_CHANNEL (or dynamic DB log_channel).
    Never sends file indexing or file registration logs.
    """
    if not bot or not text:
        return

    # Guard: never send file indexing or file registration events to log channel
    lowered = text.lower()
    if "auto-registered" in lowered or "file indexed" in lowered or "indexed file" in lowered:
        return

    target_channel = channel_override
    if not target_channel and db is not None and hasattr(db, "get_log_channel"):
        try:
            target_channel = await db.get_log_channel()
        except Exception:
            target_channel = LOG_CHANNEL
    if not target_channel:
        target_channel = LOG_CHANNEL

    if not target_channel:
        return

    try:
        from telegram.constants import ParseMode
        await bot.send_message(
            chat_id=target_channel,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


