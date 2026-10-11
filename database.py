"""
Asynchronous SQLite Database manager for Telegram File Delivery & Content Protection Bot.
Handles persistent settings, stored file registry, and self-destruct timers.
"""

from __future__ import annotations

import os
import time
import json
import secrets
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Set, Tuple
import aiosqlite

from config import (
    DATABASE_PATH,
    DeliveryMode,
    DEFAULT_DELIVERY_MODE,
    DEFAULT_AUTO_DELETE_SECONDS,
    DEFAULT_PAYWALL_ENABLED,
)

logger = logging.getLogger(__name__)


class Database:
    """Database client for managing bot settings, files, and auto-delete queues."""

    def __init__(self, db_path: Path | str = DATABASE_PATH):
        self.db_path = str(db_path)

    async def init(self) -> None:
        """Create database tables and indexes if they do not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            
            # 1. System & Developer Settings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # 2. Stored File Registry
            await db.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_code TEXT UNIQUE NOT NULL,
                    file_id TEXT NOT NULL,
                    file_unique_id TEXT,
                    file_type TEXT NOT NULL,
                    file_name TEXT,
                    file_size INTEGER DEFAULT 0,
                    caption TEXT,
                    source_chat_id INTEGER,
                    source_message_id INTEGER,
                    uploaded_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 0
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_code ON files(file_code);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_chat_id, source_message_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_unique_id ON files(file_unique_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_name ON files(file_name);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_name_size ON files(LOWER(file_name), file_size);")

            # 3. Pending Auto-Destruct Deletions (survives bot restarts)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_deletions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    file_message_id INTEGER NOT NULL,
                    notice_message_id INTEGER,
                    delete_at REAL NOT NULL,
                    status TEXT DEFAULT 'pending'
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_time ON pending_deletions(delete_at);")

            # 4. Registered Users (for broadcasts & analytics)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 5. Connected Groups/Chats (for group broadcasts & welcome settings)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    chat_type TEXT,
                    welcome_enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 6. Manual and Global Filters (chat_id = 0 for Global Filters)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS custom_filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    reply_text TEXT,
                    file_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_keyword ON custom_filters(chat_id, keyword);")

            # 7. Batch File Links
            await db.execute("""
                CREATE TABLE IF NOT EXISTS batch_links (
                    batch_id TEXT PRIMARY KEY,
                    file_codes_json TEXT NOT NULL,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 8. Banned Users (bot-level ban)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id INTEGER PRIMARY KEY,
                    reason TEXT,
                    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 9. PM Connections (group administration via DM)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS connections (
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, chat_id)
                );
            """)

            # 10. Group Settings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_settings (
                    chat_id INTEGER PRIMARY KEY,
                    settings_json TEXT NOT NULL
                );
            """)

            # Ensure chats table has is_disabled and disabled_reason columns
            try:
                await db.execute("ALTER TABLE chats ADD COLUMN is_disabled INTEGER DEFAULT 0;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE chats ADD COLUMN disabled_reason TEXT;")
            except Exception:
                pass

            # 11. Subscriptions & Premium Access
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id INTEGER PRIMARY KEY,
                    plan_name TEXT,
                    stars_paid INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at REAL NOT NULL,
                    notified_expiry INTEGER DEFAULT 0
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sub_expires ON subscriptions(expires_at);")

            # Initialize default settings if absent
            cur = await db.execute("SELECT value FROM settings WHERE key = 'delivery_mode';")
            row = await cur.fetchone()
            if not row:
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES ('delivery_mode', ?);",
                    (DEFAULT_DELIVERY_MODE.value,),
                )

            cur = await db.execute("SELECT value FROM settings WHERE key = 'auto_delete_seconds';")
            row = await cur.fetchone()
            if not row:
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES ('auto_delete_seconds', ?);",
                    (str(DEFAULT_AUTO_DELETE_SECONDS),),
                )

            cur = await db.execute("SELECT value FROM settings WHERE key = 'paywall_enabled';")
            row = await cur.fetchone()
            if not row:
                init_pw = "1" if DEFAULT_PAYWALL_ENABLED else "0"
                await db.execute(
                    "INSERT INTO settings (key, value) VALUES ('paywall_enabled', ?);",
                    (init_pw,),
                )

            await db.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    # -------------------------------------------------------------
    # Settings Management (Mode, Timers, etc.)
    # -------------------------------------------------------------

    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Fetch a setting value by key."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        """Upsert a setting value."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (key, value),
            )
            await db.commit()

    async def get_delivery_mode(self) -> DeliveryMode:
        """Retrieve current delivery mode."""
        raw = await self.get_setting("delivery_mode", DEFAULT_DELIVERY_MODE.value)
        try:
            return DeliveryMode.from_str(raw or DEFAULT_DELIVERY_MODE.value)
        except ValueError:
            return DEFAULT_DELIVERY_MODE

    async def set_delivery_mode(self, mode: DeliveryMode) -> None:
        """Update current delivery mode."""
        await self.set_setting("delivery_mode", mode.value)
        logger.info("Delivery mode updated to: %s", mode.value)

    async def get_auto_delete_seconds(self) -> int:
        """Retrieve auto-delete duration in seconds."""
        raw = await self.get_setting("auto_delete_seconds", str(DEFAULT_AUTO_DELETE_SECONDS))
        try:
            val = int(raw)
            return val if val > 0 else DEFAULT_AUTO_DELETE_SECONDS
        except (ValueError, TypeError):
            return DEFAULT_AUTO_DELETE_SECONDS

    async def set_auto_delete_seconds(self, seconds: int) -> None:
        """Update auto-delete duration in seconds."""
        if seconds <= 0:
            raise ValueError("Auto-delete seconds must be a positive integer.")
        await self.set_setting("auto_delete_seconds", str(seconds))
        logger.info("Auto-delete duration updated to: %d seconds", seconds)

    # -------------------------------------------------------------
    # Stored File Management
    # -------------------------------------------------------------

    @staticmethod
    def generate_file_code(length: int = 10) -> str:
        """Generate a random URL-safe file code."""
        return secrets.token_urlsafe(length)[:length]

    async def register_file(
        self,
        file_id: str,
        file_unique_id: Optional[str],
        file_type: str,
        file_name: Optional[str] = None,
        file_size: int = 0,
        caption: Optional[str] = None,
        source_chat_id: Optional[int] = None,
        source_message_id: Optional[int] = None,
        uploaded_by: Optional[int] = None,
        custom_code: Optional[str] = None,
    ) -> str:
        """
        Register a file in the catalog and return its unique access code.
        Automatically prevents duplicate registrations by checking:
        1. (source_chat_id, source_message_id)
        2. file_unique_id
        3. (LOWER(file_name), file_size)
        If a match already exists, returns the existing file_code without inserting a duplicate.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Check by (source_chat_id, source_message_id)
            if source_chat_id is not None and source_message_id is not None:
                async with db.execute(
                    "SELECT file_code FROM files WHERE source_chat_id = ? AND source_message_id = ? LIMIT 1;",
                    (source_chat_id, source_message_id),
                ) as cur:
                    row = await cur.fetchone()
                    if row and row[0]:
                        return row[0]

            # 2. Check by file_unique_id
            if file_unique_id and not str(file_unique_id).startswith("unique_"):
                async with db.execute(
                    "SELECT file_code FROM files WHERE file_unique_id = ? LIMIT 1;",
                    (file_unique_id,),
                ) as cur:
                    row = await cur.fetchone()
                    if row and row[0]:
                        return row[0]

            # 3. Check by (LOWER(file_name), file_size) for real named files with non-zero size
            if file_name and file_name != "Media File" and file_size > 0:
                async with db.execute(
                    "SELECT file_code FROM files WHERE LOWER(file_name) = LOWER(?) AND file_size = ? LIMIT 1;",
                    (file_name, file_size),
                ) as cur:
                    row = await cur.fetchone()
                    if row and row[0]:
                        return row[0]

            code = custom_code or self.generate_file_code()
            # Ensure unique code
            for _ in range(5):
                try:
                    await db.execute(
                        """
                        INSERT INTO files (
                            file_code, file_id, file_unique_id, file_type, file_name,
                            file_size, caption, source_chat_id, source_message_id, uploaded_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            code,
                            file_id,
                            file_unique_id,
                            file_type,
                            file_name,
                            file_size,
                            caption,
                            source_chat_id,
                            source_message_id,
                            uploaded_by,
                        ),
                    )
                    await db.commit()
                    return code
                except aiosqlite.IntegrityError:
                    code = self.generate_file_code()
            raise RuntimeError("Failed to generate a unique file code after multiple attempts.")

    async def get_file_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored file record by its file code."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM files WHERE file_code = ?;", (code,)) as cur:
                row = await cur.fetchone()
                if row:
                    return dict(row)
                return None

    async def get_file_by_source_message(self, source_chat_id: int, source_message_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve stored file record by source chat and message ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM files WHERE source_chat_id = ? AND source_message_id = ?;",
                (source_chat_id, source_message_id),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_existing_message_ids_in_range(self, source_chat_id: int, start_id: int, end_id: int) -> Set[int]:
        """Fetch all message IDs already registered in a specific channel within a given range."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT source_message_id FROM files WHERE source_chat_id = ? AND source_message_id BETWEEN ? AND ?;",
                (source_chat_id, start_id, end_id),
            ) as cur:
                rows = await cur.fetchall()
                return {row[0] for row in rows if row[0] is not None}

    async def get_file_by_unique_id(self, file_unique_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored file record by Telegram file_unique_id."""
        if not file_unique_id:
            return None
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM files WHERE file_unique_id = ?;",
                (file_unique_id,),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def search_files(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search files by matching words across name and caption (deduplicated by filename and size)."""
        if not query:
            return []
        import re
        words = [w.strip() for w in re.split(r"[\s._\-+]+", query) if w.strip()]
        if not words:
            return []

        conditions = " AND ".join(["(file_name LIKE ? OR caption LIKE ?)"] * len(words))
        params: List[Any] = []
        for w in words:
            param = f"%{w}%"
            params.extend([param, param])
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            sql = f"""
                SELECT * FROM files
                WHERE id IN (
                    SELECT MAX(id) FROM files
                    WHERE {conditions}
                    GROUP BY LOWER(COALESCE(file_name, '')), COALESCE(file_size, 0)
                )
                ORDER BY id DESC
                LIMIT ?;
            """
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
                return [dict(row) for row in rows]

    async def get_recent_files(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the most recently registered files."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM files ORDER BY id DESC LIMIT ?;",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(row) for row in rows]

    async def increment_access_count(self, file_id_db: int) -> None:
        """Increment download/view counter for a file."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE files SET access_count = access_count + 1 WHERE id = ?;",
                (file_id_db,),
            )
            await db.commit()

    async def get_statistics(self) -> Dict[str, Any]:
        """Fetch system statistics (total files, total accesses, current mode)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*), COALESCE(SUM(access_count), 0) FROM files;") as cur:
                total_files, total_access = await cur.fetchone() or (0, 0)
            
            async with db.execute("SELECT COUNT(*) FROM pending_deletions WHERE status = 'pending';") as cur:
                pending_count = (await cur.fetchone())[0] or 0

        mode = await self.get_delivery_mode()
        timer = await self.get_auto_delete_seconds()

        return {
            "total_files": total_files,
            "total_accesses": total_access,
            "pending_deletions": pending_count,
            "delivery_mode": mode.value,
            "auto_delete_seconds": timer,
        }

    # Alias for convenience
    get_stats = get_statistics

    # -------------------------------------------------------------
    # Auto-Destruct Self-Destruct Queue (Persistence)
    # -------------------------------------------------------------

    async def schedule_message_deletion(
        self,
        chat_id: int,
        file_message_id: int,
        notice_message_id: Optional[int],
        delay_seconds: int,
    ) -> int:
        """Record a message pair scheduled for auto-deletion."""
        delete_at = time.time() + delay_seconds
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO pending_deletions (chat_id, file_message_id, notice_message_id, delete_at, status)
                VALUES (?, ?, ?, ?, 'pending');
                """,
                (chat_id, file_message_id, notice_message_id, delete_at),
            )
            await db.commit()
            return cur.lastrowid or 0

    async def get_due_deletions(self) -> List[Dict[str, Any]]:
        """Fetch all deletions that are past due."""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM pending_deletions WHERE status = 'pending' AND delete_at <= ?;",
                (now,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def mark_deletion_done(self, record_id: int, status: str = "deleted") -> None:
        """Mark a deletion record as done or failed."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE pending_deletions SET status = ? WHERE id = ?;",
                (status, record_id),
            )
            await db.commit()

    async def cleanup_finished_deletions(self) -> None:
        """Remove completed deletion records older than 1 day."""
        cutoff = time.time() - 86400
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM pending_deletions WHERE status != 'pending' AND delete_at < ?;",
                (cutoff,),
            )
            await db.commit()

    # -------------------------------------------------------------
    # User Tracking & Broadcasts
    # -------------------------------------------------------------

    async def add_or_update_user(self, user_id: int, first_name: Optional[str] = None, username: Optional[str] = None) -> None:
        """Insert or update user record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, first_name, username)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    username = excluded.username;
                """,
                (user_id, first_name, username),
            )
            await db.commit()

    async def get_all_users(self) -> List[int]:
        """Fetch all registered user IDs for broadcast."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM users;") as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def get_user_count(self) -> int:
        """Get total registered user count."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users;") as cur:
                return (await cur.fetchone())[0] or 0

    # -------------------------------------------------------------
    # Group/Chat Tracking & Settings
    # -------------------------------------------------------------

    async def add_or_update_chat(self, chat_id: int, title: Optional[str] = None, chat_type: Optional[str] = None) -> None:
        """Insert or update chat record."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO chats (chat_id, title, chat_type)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    chat_type = excluded.chat_type;
                """,
                (chat_id, title, chat_type),
            )
            await db.commit()

    async def get_all_chats(self) -> List[Dict[str, Any]]:
        """Fetch all registered group chats."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM chats;") as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def get_chat_count(self) -> int:
        """Get total registered group count."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM chats;") as cur:
                return (await cur.fetchone())[0] or 0

    async def set_chat_welcome(self, chat_id: int, enabled: bool) -> None:
        """Enable or disable welcome greetings in a group."""
        val = 1 if enabled else 0
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO chats (chat_id, welcome_enabled)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET welcome_enabled = excluded.welcome_enabled;
                """,
                (chat_id, val),
            )
            await db.commit()

    async def get_chat_welcome(self, chat_id: int) -> bool:
        """Check if welcome greetings are enabled in a group."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT welcome_enabled FROM chats WHERE chat_id = ?;", (chat_id,)) as cur:
                row = await cur.fetchone()
                if row is not None:
                    return bool(row[0])
                return True  # Default enabled

    # -------------------------------------------------------------
    # Manual and Global Filters
    # -------------------------------------------------------------

    async def add_filter(self, chat_id: int, keyword: str, reply_text: Optional[str] = None, file_id: Optional[str] = None) -> None:
        """Add or update a keyword filter for a group (or chat_id=0 for global)."""
        clean_kw = keyword.strip().lower()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO custom_filters (chat_id, keyword, reply_text, file_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, keyword) DO UPDATE SET
                    reply_text = excluded.reply_text,
                    file_id = excluded.file_id;
                """,
                (chat_id, clean_kw, reply_text, file_id),
            )
            await db.commit()

    async def get_filter(self, chat_id: int, keyword: str) -> Optional[Dict[str, Any]]:
        """
        Check for a matching filter: first in local group, then globally (chat_id=0).
        """
        clean_kw = keyword.strip().lower()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Check chat-specific filter first
            async with db.execute(
                "SELECT * FROM custom_filters WHERE chat_id = ? AND keyword = ?;",
                (chat_id, clean_kw),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return dict(row)

            # Check global filter (chat_id = 0)
            async with db.execute(
                "SELECT * FROM custom_filters WHERE chat_id = 0 AND keyword = ?;",
                (clean_kw,),
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_chat_filters(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get all custom filters registered in a chat."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM custom_filters WHERE chat_id = ? ORDER BY keyword ASC;",
                (chat_id,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def get_global_filters(self) -> List[Dict[str, Any]]:
        """Get all global filters."""
        return await self.get_chat_filters(0)

    async def delete_filter(self, chat_id: int, keyword: str) -> bool:
        """Delete a filter by keyword."""
        clean_kw = keyword.strip().lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM custom_filters WHERE chat_id = ? AND keyword = ?;",
                (chat_id, clean_kw),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def delete_all_filters(self, chat_id: int) -> int:
        """Delete all filters in a specific chat."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM custom_filters WHERE chat_id = ?;",
                (chat_id,),
            )
            await db.commit()
            return cur.rowcount or 0

    # -------------------------------------------------------------
    # Batch Links (File Store)
    # -------------------------------------------------------------

    async def save_batch_link(self, batch_id: str, file_codes: List[str], created_by: int) -> None:
        """Store a batch of file codes associated with a unique batch_id."""
        json_codes = json.dumps(file_codes)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO batch_links (batch_id, file_codes_json, created_by)
                VALUES (?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET file_codes_json = excluded.file_codes_json;
                """,
                (batch_id, json_codes, created_by),
            )
            await db.commit()

    async def get_batch_link(self, batch_id: str) -> Optional[List[str]]:
        """Retrieve list of file codes for a batch_id."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT file_codes_json FROM batch_links WHERE batch_id = ?;",
                (batch_id,),
            ) as cur:
                row = await cur.fetchone()
                if row and row[0]:
                    try:
                        return json.loads(row[0])
                    except Exception:
                        return None
                return None

    # -------------------------------------------------------------
    # File Deletion and Paginated Search
    # -------------------------------------------------------------

    async def delete_file_by_code(self, code: str) -> bool:
        """Delete a file from database by code."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM files WHERE file_code = ?;", (code,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def search_files_paginated(
        self, query: str, offset: int = 0, limit: int = 8
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Search files with pagination and return (items, total_count).
        """
        if not query:
            return [], 0
        import re
        words = [w.strip() for w in re.split(r"[\s._\-+]+", query) if w.strip()]
        if not words:
            return [], 0

        conditions = " AND ".join(["(file_name LIKE ? OR caption LIKE ?)"] * len(words))
        params: List[Any] = []
        for w in words:
            param = f"%{w}%"
            params.extend([param, param])

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # 1. Total unique matching count (deduplicated by filename + size)
            count_sql = f"""
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM files
                    WHERE {conditions}
                    GROUP BY LOWER(COALESCE(file_name, '')), COALESCE(file_size, 0)
                );
            """
            async with db.execute(count_sql, params) as count_cur:
                total_count = (await count_cur.fetchone())[0] or 0

            # 2. Paginated unique rows (keeping newest entry for each file)
            paginated_sql = f"""
                SELECT * FROM files
                WHERE id IN (
                    SELECT MAX(id) FROM files
                    WHERE {conditions}
                    GROUP BY LOWER(COALESCE(file_name, '')), COALESCE(file_size, 0)
                )
                ORDER BY id DESC
                LIMIT ? OFFSET ?;
            """
            paginated_params = list(params) + [limit, offset]
            async with db.execute(paginated_sql, paginated_params) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows], total_count

    async def delete_file_by_source_message(self, source_chat_id: int, source_message_id: int) -> bool:
        """Delete stored file by its source channel/chat and message ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM files WHERE source_chat_id = ? AND source_message_id = ?;",
                (source_chat_id, source_message_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def delete_all_files(self) -> int:
        """Delete all indexed files from database."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM files;")
            await db.commit()
            return cur.rowcount or 0

    # -------------------------------------------------------------
    # Bot-Level User Banning
    # -------------------------------------------------------------

    async def ban_user(self, user_id: int, reason: str = "No reason provided") -> None:
        """Ban a user from using the bot."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO banned_users (user_id, reason)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason;
                """,
                (user_id, reason),
            )
            await db.commit()

    async def unban_user(self, user_id: int) -> bool:
        """Unban a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM banned_users WHERE user_id = ?;", (user_id,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def is_user_banned(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """Check if user is banned. Returns (is_banned, reason)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT reason FROM banned_users WHERE user_id = ?;", (user_id,)) as cur:
                row = await cur.fetchone()
                if row:
                    return True, row[0]
                return False, None

    async def get_banned_users(self) -> List[Dict[str, Any]]:
        """Get all banned users."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM banned_users;") as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    # -------------------------------------------------------------
    # Chat Enable / Disable Controls
    # -------------------------------------------------------------

    async def disable_chat(self, chat_id: int, reason: str = "No reason provided") -> None:
        """Disable a chat so the bot leaves and rejects requests."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO chats (chat_id, is_disabled, disabled_reason)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET is_disabled = 1, disabled_reason = excluded.disabled_reason;
                """,
                (chat_id, reason),
            )
            await db.commit()

    async def enable_chat(self, chat_id: int) -> bool:
        """Re-enable a previously disabled chat."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE chats SET is_disabled = 0, disabled_reason = NULL WHERE chat_id = ?;",
                (chat_id,),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def is_chat_disabled(self, chat_id: int) -> Tuple[bool, Optional[str]]:
        """Check if a chat is disabled. Returns (is_disabled, reason)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT is_disabled, disabled_reason FROM chats WHERE chat_id = ?;", (chat_id,)) as cur:
                row = await cur.fetchone()
                if row and row[0] == 1:
                    return True, row[1]
                return False, None

    # -------------------------------------------------------------
    # Database Cleanup (Delete User / Delete Chat)
    # -------------------------------------------------------------

    async def delete_user(self, user_id: int) -> bool:
        """Remove user from database (used by clear_junk)."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM users WHERE user_id = ?;", (user_id,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def delete_chat(self, chat_id: int) -> bool:
        """Remove chat from database (used by clear_junk_group)."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM chats WHERE chat_id = ?;", (chat_id,))
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def get_all_users_details(self) -> List[Dict[str, Any]]:
        """Fetch all user details."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY created_at DESC;") as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    # -------------------------------------------------------------
    # PM Connections
    # -------------------------------------------------------------

    async def add_connection(self, user_id: int, chat_id: int) -> bool:
        """Link a group chat to a user's PM."""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO connections (user_id, chat_id) VALUES (?, ?);",
                    (user_id, chat_id),
                )
                await db.commit()
                return True
            except Exception:
                return False

    async def delete_connection(self, user_id: int, chat_id: int) -> bool:
        """Remove a link between a group chat and user's PM."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM connections WHERE user_id = ? AND chat_id = ?;",
                (user_id, chat_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0

    async def get_user_connections(self, user_id: int) -> List[int]:
        """Get all connected chat IDs for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT chat_id FROM connections WHERE user_id = ?;", (user_id,)) as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def get_indexed_channels(self) -> List[int]:
        """Get distinct source channels that have indexed files."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT DISTINCT source_chat_id FROM files WHERE source_chat_id IS NOT NULL;") as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows if r[0] != 0]

    async def get_active_connection(self, user_id: int) -> Optional[int]:
        """Return the most recently connected group chat ID for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT chat_id FROM connections WHERE user_id = ? ORDER BY connected_at DESC LIMIT 1;",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def get_all_filenames(self, limit: int = 1000) -> List[str]:
        """Fetch distinct file titles and names for fuzzy matching."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT DISTINCT file_name FROM files WHERE file_name IS NOT NULL AND file_name != '' LIMIT ?;",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows if r[0]]

    def get_db_size(self) -> int:
        """Return database file size in bytes."""
        try:
            return os.path.getsize(self.db_path)
        except Exception:
            return 0

    async def get_group_settings(self, chat_id: int) -> Dict[str, Any]:
        """Fetch settings for a specific group chat, with default fallbacks."""
        defaults = {
            "button": True,         # True = single button, False = double button
            "botpm": False,         # True = deliver files in PM
            "file_secure": True,    # True = protect content (Mode 1)
            "imdb": True,           # True = include IMDb preview
            "spell_check": True,    # True = suggest similar titles
            "welcome": True,        # True = welcome greeting
            "template": None,       # Custom IMDb / result template
        }
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT settings_json FROM group_settings WHERE chat_id = ?;", (chat_id,)) as cur:
                row = await cur.fetchone()
                if row and row[0]:
                    try:
                        saved = json.loads(row[0])
                        defaults.update(saved)
                    except Exception:
                        pass
        return defaults

    async def save_group_settings(self, chat_id: int, key: str, value: Any) -> None:
        """Update a specific setting for a group chat."""
        current = await self.get_group_settings(chat_id)
        current[key] = value
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO group_settings (chat_id, settings_json)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET settings_json = excluded.settings_json;
                """,
                (chat_id, json.dumps(current)),
            )
            await db.commit()

    async def get_total_files_count(self) -> int:
        """Return total files count."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM files;") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_total_users_count(self) -> int:
        """Return total users count."""
        return await self.get_user_count()

    # -------------------------------------------------------------
    # Subscriptions & Paywall Access Control
    # -------------------------------------------------------------

    async def is_paywall_enabled(self) -> bool:
        """Check whether the paywall (paid-users only mode) is enabled."""
        val = await self.get_setting("paywall_enabled", "0")
        return val in ("1", "true", "True", "yes", "on")

    async def set_paywall_enabled(self, enabled: bool) -> None:
        """Toggle the paywall on or off."""
        await self.set_setting("paywall_enabled", "1" if enabled else "0")

    async def get_user_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Fetch subscription details for a specific user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE user_id = ?;", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def is_user_premium(self, user_id: int) -> bool:
        """Check if user has an active, unexpired subscription."""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM subscriptions WHERE user_id = ? AND expires_at > ?;",
                (user_id, now),
            ) as cur:
                row = await cur.fetchone()
                return bool(row)

    async def add_or_extend_subscription(
        self,
        user_id: int,
        plan_name: str,
        stars: int,
        duration_seconds: int,
    ) -> Dict[str, Any]:
        """
        Add a new subscription or extend an existing active subscription.
        Returns the updated subscription dict.
        """
        now = time.time()
        current = await self.get_user_subscription(user_id)
        if current and current["expires_at"] > now:
            # Active plan: extend from previous expiry
            new_expires_at = current["expires_at"] + duration_seconds
            total_stars = current.get("stars_paid", 0) + stars
        else:
            # New or expired plan: start from current timestamp
            new_expires_at = now + duration_seconds
            total_stars = stars

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO subscriptions (user_id, plan_name, stars_paid, expires_at, notified_expiry)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    plan_name = excluded.plan_name,
                    stars_paid = ?,
                    expires_at = excluded.expires_at,
                    notified_expiry = 0;
                """,
                (user_id, plan_name, total_stars, new_expires_at, total_stars),
            )
            await db.commit()

        return await self.get_user_subscription(user_id) or {
            "user_id": user_id,
            "plan_name": plan_name,
            "stars_paid": total_stars,
            "expires_at": new_expires_at,
        }

    async def remove_subscription(self, user_id: int) -> bool:
        """Revoke a user's subscription."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM subscriptions WHERE user_id = ?;", (user_id,))
            await db.commit()
            return cur.rowcount > 0

    async def get_all_active_subscriptions(self) -> List[Dict[str, Any]]:
        """Return list of all currently active subscriptions."""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE expires_at > ? ORDER BY expires_at ASC;",
                (now,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def get_due_expired_subscriptions(self) -> List[Dict[str, Any]]:
        """Return list of subscriptions that recently expired and have not been notified."""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE expires_at <= ? AND notified_expiry = 0;",
                (now,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def mark_subscription_expired_notified(self, user_id: int) -> None:
        """Mark expired subscription as notified so user receives expiry notice once."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE subscriptions SET notified_expiry = 1 WHERE user_id = ?;",
                (user_id,),
            )
            await db.commit()

    async def get_star_plans(self) -> Dict[int, Dict[str, Any]]:
        """Return configured Telegram Stars subscription plans."""
        default_plans = {
            10: {"name": "7 Days Pass", "days": 7, "stars": 10},
            25: {"name": "15 Days Pass", "days": 15, "stars": 25},
            45: {"name": "1 Month VIP", "days": 30, "stars": 45},
            80: {"name": "2 Months VIP", "days": 60, "stars": 80},
            120: {"name": "3 Months VIP", "days": 90, "stars": 120},
        }
        val = await self.get_setting("star_plans")
        if val:
            try:
                raw = json.loads(val)
                # Convert string keys back to int
                return {int(k): v for k, v in raw.items()}
            except Exception:
                pass
        return default_plans

    async def set_star_plans(self, plans: Dict[int, Dict[str, Any]]) -> None:
        """Save customized Star plans to database."""
        serialized = {str(k): v for k, v in plans.items()}
        await self.set_setting("star_plans", json.dumps(serialized))


