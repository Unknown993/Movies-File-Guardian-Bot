"""Unit tests for asynchronous database operations."""

import pytest
import time
from database import Database
from config import DeliveryMode


@pytest.mark.asyncio
async def test_database_init_and_settings(tmp_path):
    db_file = tmp_path / "test_bot.sqlite3"
    db = Database(db_file)
    await db.init()

    # Default mode check
    mode = await db.get_delivery_mode()
    assert mode == DeliveryMode.VIEW_ONLY

    # Toggle mode to downloadable
    await db.set_delivery_mode(DeliveryMode.DOWNLOADABLE)
    mode = await db.get_delivery_mode()
    assert mode == DeliveryMode.DOWNLOADABLE

    # Auto-delete timer
    timer = await db.get_auto_delete_seconds()
    assert timer == 180

    await db.set_auto_delete_seconds(300)
    timer = await db.get_auto_delete_seconds()
    assert timer == 300


@pytest.mark.asyncio
async def test_database_file_registration_and_retrieval(tmp_path):
    db_file = tmp_path / "test_bot.sqlite3"
    db = Database(db_file)
    await db.init()

    code = await db.register_file(
        file_id="tg_file_12345",
        file_unique_id="unique_123",
        file_type="document",
        file_name="secret_report.pdf",
        file_size=2048,
        caption="Confidential Document",
        source_chat_id=-100111222333,
        source_message_id=42,
        uploaded_by=999,
    )

    assert code is not None
    assert len(code) > 0

    record = await db.get_file_by_code(code)
    assert record is not None
    assert record["file_id"] == "tg_file_12345"
    assert record["file_name"] == "secret_report.pdf"
    assert record["source_chat_id"] == -100111222333
    assert record["source_message_id"] == 42
    assert record["access_count"] == 0

    # Increment access count
    await db.increment_access_count(record["id"])
    updated = await db.get_file_by_code(code)
    assert updated["access_count"] == 1


@pytest.mark.asyncio
async def test_database_pending_deletions(tmp_path):
    db_file = tmp_path / "test_bot.sqlite3"
    db = Database(db_file)
    await db.init()

    # Schedule deletion with delay of 0 seconds (immediately due)
    rec_id = await db.schedule_message_deletion(
        chat_id=123456,
        file_message_id=101,
        notice_message_id=102,
        delay_seconds=0,
    )
    assert rec_id > 0

    # Wait 0.1s so time.time() > delete_at
    time.sleep(0.1)

    due = await db.get_due_deletions()
    assert len(due) == 1
    assert due[0]["chat_id"] == 123456
    assert due[0]["file_message_id"] == 101
    assert due[0]["notice_message_id"] == 102

    # Mark done
    await db.mark_deletion_done(due[0]["id"], status="deleted")
    due_after = await db.get_due_deletions()
    assert len(due_after) == 0
