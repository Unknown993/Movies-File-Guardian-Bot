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

# Load environment variables from .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


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

# SQLite Database Path
DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "bot_database.sqlite3")


def is_developer(user_id: int) -> bool:
    """Check if the given Telegram user ID is the authorized Developer."""
    return DEVELOPER_ID > 0 and user_id == DEVELOPER_ID


def is_admin(user_id: int) -> bool:
    """Check if the given Telegram user ID is an admin or the developer."""
    return user_id in ADMIN_IDS
