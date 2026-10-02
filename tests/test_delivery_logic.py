"""Unit tests for delivery strategy and content protection enforcement."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.constants import ChatType

from config import DeliveryMode
from database import Database
from delivery import is_chat_allowed_for_download, deliver_file_to_user, execute_auto_deletion


def test_is_chat_allowed_for_download(monkeypatch):
    monkeypatch.setattr("delivery.ALLOWED_TEMP_CHANNELS", {-100999888})

    # Private DM should always be allowed
    assert is_chat_allowed_for_download(123456, ChatType.PRIVATE) is True

    # Group not in allowed list should be disallowed
    assert is_chat_allowed_for_download(-100111222, ChatType.GROUP) is False
    assert is_chat_allowed_for_download(-100111222, ChatType.SUPERGROUP) is False

    # Channel in allowed temp channels should be allowed
    assert is_chat_allowed_for_download(-100999888, ChatType.CHANNEL) is True


@pytest.mark.asyncio
async def test_deliver_file_mode_1_view_only(tmp_path):
    """Test Mode 1 applies protect_content=True."""
    db_file = tmp_path / "test_delivery_m1.sqlite3"
    db = Database(db_file)
    await db.init()
    await db.set_delivery_mode(DeliveryMode.VIEW_ONLY)

    file_rec = {
        "id": 1,
        "file_code": "code123",
        "file_id": "tg_doc_id",
        "file_type": "document",
        "caption": "View only file",
        "source_chat_id": -100555,
        "source_message_id": 88,
    }

    bot_mock = AsyncMock()
    delivered_msg_mock = MagicMock()
    delivered_msg_mock.message_id = 456
    bot_mock.copy_message.return_value = delivered_msg_mock
    bot_mock.send_message.return_value = MagicMock(message_id=457)

    job_queue_mock = MagicMock()

    res = await deliver_file_to_user(
        bot=bot_mock,
        db=db,
        job_queue=job_queue_mock,
        chat_id=12345,
        chat_type=ChatType.PRIVATE,
        file_record=file_rec,
        bot_username="TestBot",
    )

    assert res == delivered_msg_mock
    # Assert copy_message was called with protect_content=True
    bot_mock.copy_message.assert_awaited_once_with(
        chat_id=12345,
        from_chat_id=-100555,
        message_id=88,
        caption="View only file",
        protect_content=True,
    )

    # JobQueue should NOT schedule auto-destruct in Mode 1
    job_queue_mock.run_once.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_file_mode_2_downloadable_private_chat(tmp_path):
    """Test Mode 2 in private DM applies protect_content=False, strips header, and sets auto-destruct."""
    db_file = tmp_path / "test_delivery_m2.sqlite3"
    db = Database(db_file)
    await db.init()
    await db.set_delivery_mode(DeliveryMode.DOWNLOADABLE)
    await db.set_auto_delete_seconds(180)

    file_rec = {
        "id": 2,
        "file_code": "code_dl",
        "file_id": "tg_doc_id_2",
        "file_type": "video",
        "caption": "Downloadable video",
        "source_chat_id": -100777,
        "source_message_id": 99,
    }

    bot_mock = AsyncMock()
    delivered_msg_mock = MagicMock()
    delivered_msg_mock.message_id = 701
    bot_mock.copy_message.return_value = delivered_msg_mock

    notice_msg_mock = MagicMock()
    notice_msg_mock.message_id = 702
    bot_mock.send_message.return_value = notice_msg_mock

    job_queue_mock = MagicMock()

    res = await deliver_file_to_user(
        bot=bot_mock,
        db=db,
        job_queue=job_queue_mock,
        chat_id=12345,
        chat_type=ChatType.PRIVATE,
        file_record=file_rec,
        bot_username="TestBot",
    )

    assert res == delivered_msg_mock
    # Assert copy_message was called with protect_content=False
    bot_mock.copy_message.assert_awaited_once_with(
        chat_id=12345,
        from_chat_id=-100777,
        message_id=99,
        caption="Downloadable video",
        protect_content=False,
    )

    # Assert notice message was sent
    bot_mock.send_message.assert_awaited_once()

    # Assert JobQueue scheduled the deletion with 180s delay
    job_queue_mock.run_once.assert_called_once()
    _, kwargs = job_queue_mock.run_once.call_args
    assert kwargs["when"] == 180
    assert kwargs["data"]["file_message_id"] == 701
    assert kwargs["data"]["notice_message_id"] == 702


@pytest.mark.asyncio
async def test_deliver_file_mode_2_restricted_in_group(tmp_path):
    """Test Mode 2 prevents delivery in groups and redirects to DM."""
    db_file = tmp_path / "test_delivery_m2_grp.sqlite3"
    db = Database(db_file)
    await db.init()
    await db.set_delivery_mode(DeliveryMode.DOWNLOADABLE)

    file_rec = {
        "id": 3,
        "file_code": "secret_dl",
        "file_id": "doc_id",
        "file_type": "document",
        "source_chat_id": -100777,
        "source_message_id": 99,
    }

    bot_mock = AsyncMock()
    job_queue_mock = MagicMock()

    res = await deliver_file_to_user(
        bot=bot_mock,
        db=db,
        job_queue=job_queue_mock,
        chat_id=-1001234567,
        chat_type=ChatType.SUPERGROUP,
        file_record=file_rec,
        bot_username="TestBot",
    )

    # Must return None (file was blocked from group delivery)
    assert res is None
    # copy_message should NOT be called
    bot_mock.copy_message.assert_not_called()
    # bot should send warning redirect message
    bot_mock.send_message.assert_awaited_once()
    assert "File Delivery Restricted to Private DM" in bot_mock.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_execute_auto_deletion(tmp_path):
    """Test execute_auto_deletion deletes file message and notice message."""
    db_file = tmp_path / "test_deletion.sqlite3"
    db = Database(db_file)
    await db.init()

    rec_id = await db.schedule_message_deletion(123, 501, 502, 0)

    bot_mock = AsyncMock()

    await execute_auto_deletion(
        bot=bot_mock,
        db=db,
        chat_id=123,
        file_message_id=501,
        notice_message_id=502,
        record_id=rec_id,
    )

    # Both messages deleted
    assert bot_mock.delete_message.await_count == 2
    bot_mock.delete_message.assert_any_await(chat_id=123, message_id=501)
    bot_mock.delete_message.assert_any_await(chat_id=123, message_id=502)
