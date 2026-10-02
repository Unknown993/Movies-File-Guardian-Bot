"""
Smart filename and caption cleaner.
Filters out URLs, Telegram handles, channel tags, dates, timestamps, 
quality tags (1080p, WEB-DL), and truncates excessively long names.
"""

from __future__ import annotations

import re
from typing import Optional


def smart_clean_filename(raw_name: Optional[str], max_length: int = 60) -> str:
    """
    Clean and format file names or captions:
    - Removes URLs and Telegram @usernames
    - Removes channel advertising brackets [t.me/...]
    - Removes camera and WhatsApp prefixes (VID_..., IMG_..., WA000...)
    - Removes full dates and timestamps (e.g. 2026-10-02, 20261002_143022)
    - Removes media rip tags (1080p, 720p, WEB-DL, BluRay, x264, x265, HEVC)
    - Normalizes separators (dots, underscores, hyphens) to clean spaces
    - Preserves file extension (.mp4, .pdf, etc.)
    - Truncates if longer than max_length characters
    """
    if not raw_name:
        return "File"

    text = raw_name.strip()

    # 1. Extract file extension if present (e.g. .mp4, .mkv, .pdf, .zip)
    ext = ""
    ext_match = re.search(r"(\.[a-zA-Z0-9]{2,5})$", text)
    if ext_match:
        ext = ext_match.group(1).lower()
        base = text[: ext_match.start()]
    else:
        base = text

    # 2. Remove URLs, web domains, and Telegram links
    base = re.sub(r"https?://\S+|www\.\S+|t\.me/\S+", "", base, flags=re.IGNORECASE)

    # 3. Remove Telegram channel handles (@channel_name)
    base = re.sub(r"@[\w_]+", "", base)

    # 4. Remove bracketed promotional tags like [Channel Name], [Join @...], etc.
    base = re.sub(
        r"\[[^\]]*(?:telegram|channel|join|official|link|t\.me|club|promo|hd)[^\]]*\]",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(
        r"\([^\)]*(?:telegram|channel|join|official|link|t\.me|club|promo)[^\)]*\)",
        "",
        base,
        flags=re.IGNORECASE,
    )

    # 5. Remove WhatsApp / Camera / Screenshot prefixes
    base = re.sub(
        r"\b(?:VID|IMG|AUD|DOC|PXL|Screenshot|WA)[-_]?\d{4,8}[-_]?(?:WA\d+)?\b",
        "",
        base,
        flags=re.IGNORECASE,
    )

    # 6. Detect a 4-digit release year if present (e.g. 1999, 2024), to keep it clean
    year_match = re.search(r"\b(19\d\d|20[0-3]\d)\b", base)
    year = year_match.group(1) if year_match else None

    # 7. Remove full timestamps and dates (e.g. 20261002_143022, 2026-10-02, 02.10.2026)
    base = re.sub(r"\b\d{8}[-_]\d{4,6}\b", "", base)
    base = re.sub(r"\b\d{4}[-_.]\d{2}[-_.]\d{2}\b", "", base)
    base = re.sub(r"\b\d{2}[-_.]\d{2}[-_.]\d{4}\b", "", base)

    # 8. Remove common video quality and encoding tags
    quality_patterns = (
        r"\b(480p|720p|1080p|2160p|4k|uhd|hdrip|web-?dl|webrip|bluray|brrip|"
        r"dvdrip|hdtc|camrip|x264|x265|hevc|h\.?264|h\.?265|10bit|aac|"
        r"ac3|dts|ddp5\.?1|sub(?:s)?|esub|dubbed|proper|repack)\b"
    )
    base = re.sub(quality_patterns, "", base, flags=re.IGNORECASE)

    # 9. Replace separators (dots, underscores, dashes, pluses) with spaces
    base = re.sub(r"[\._\-+]+", " ", base)

    # 10. Clean leftover brackets and special characters
    base = re.sub(r"[\[\]\(\)\{\}\|~`!#$^*=+]", " ", base)

    # 11. Normalize multiple spaces
    base = re.sub(r"\s+", " ", base).strip()

    # 12. If a clean year was stripped out and we have a valid name, attach year back nicely
    if year and year not in base and len(base) > 2:
        base = f"{base} ({year})"

    # 13. Fallback if the whole name was stripped (e.g., file was only numbers or dates)
    if not base or len(base) < 2:
        base = "File"

    # 14. Capitalize title neatly
    base = " ".join(word.capitalize() if not word.isupper() else word for word in base.split())

    # 15. Truncate if exceeds max_length
    if len(base) > max_length:
        base = base[:max_length].rstrip() + "..."

    return f"{base}{ext}" if ext else base


def get_file_type_icon(file_type: str, file_name: Optional[str] = None) -> str:
    """Return an appropriate emoji icon based on file type or extension."""
    ft = (file_type or "").lower()
    fn = (file_name or "").lower()

    if ft == "video" or fn.endswith((".mp4", ".mkv", ".avi", ".mov", ".webm")):
        return "🎬"
    elif ft == "audio" or fn.endswith((".mp3", ".flac", ".wav", ".m4a", ".ogg")):
        return "🎵"
    elif fn.endswith((".pdf", ".doc", ".docx", ".txt", ".epub")):
        return "📄"
    elif fn.endswith((".zip", ".rar", ".7z", ".tar", ".gz")):
        return "📦"
    elif ft == "photo" or fn.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "🖼️"
    elif ft == "voice":
        return "🎤"
    return "📁"
