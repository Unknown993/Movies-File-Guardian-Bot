"""
Asynchronous SQLite Database manager for Telegram File Delivery & Content Protection Bot.
Handles persistent settings, stored file registry, and self-destruct timers.
"""

from __future__ import annotations

import time
import secrets
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Set
import aiosqlite

from config import (
    DATABASE_PATH,
    DeliveryMode,
    DEFAULT_DELIVERY_MODE,
    DEFAULT_AUTO_DELETE_SECONDS,
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
        """Register a new file in the catalog and return its unique access code."""
        code = custom_code or self.generate_file_code()
        async with aiosqlite.connect(self.db_path) as db:
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
        """Search files by matching words across name and caption."""
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
                WHERE {conditions}
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
