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


@pytest.mark.asyncio
async def test_database_duplicate_file_prevention(tmp_path):
    db_file = tmp_path / "test_dedup.sqlite3"
    db = Database(db_file)
    await db.init()

    # 1. Initial registration
    code1 = await db.register_file(
        file_id="tg_file_1",
        file_unique_id="real_uid_abc",
        file_type="video",
        file_name="Inception.2010.1080p.mkv",
        file_size=1500000000,
        caption="Inception 2010",
        source_chat_id=-100111222333,
        source_message_id=100,
        uploaded_by=999,
    )

    # 2. Same file_unique_id at a different message ID -> returns existing code
    code2 = await db.register_file(
        file_id="tg_file_2",
        file_unique_id="real_uid_abc",
        file_type="video",
        file_name="Different_Name.mkv",
        file_size=99999,
        caption="Duplicate UID",
        source_chat_id=-100111222333,
        source_message_id=101,
        uploaded_by=999,
    )
    assert code2 == code1

    # 3. Same (LOWER(file_name), file_size) with different UID and message ID -> returns existing code
    code3 = await db.register_file(
        file_id="tg_file_3",
        file_unique_id="real_uid_xyz",
        file_type="video",
        file_name="inception.2010.1080p.mkv",
        file_size=1500000000,
        caption="Duplicate Name+Size",
        source_chat_id=-100111222333,
        source_message_id=102,
        uploaded_by=999,
    )
    assert code3 == code1

    # Verify only 1 file exists in total and in search
    stats = await db.get_stats()
    assert stats["total_files"] == 1

    results, total = await db.search_files_paginated("Inception", limit=10, offset=0)
    assert total == 1
    assert len(results) == 1
    assert results[0]["file_code"] == code1
