"""Unit tests for newly added bot features: Users, Chats, Filters, Batching, and Moderation."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.constants import ChatMemberStatus

from database import Database
from handlers.fsub_helper import is_user_subscribed
from handlers.moderation_handlers import parse_duration_seconds


@pytest.mark.asyncio
async def test_user_tracking_and_counts(tmp_path):
    """Test user registration and retrieval for broadcasting."""
    db_file = tmp_path / "test_users.sqlite3"
    db = Database(db_file)
    await db.init()

    assert await db.get_user_count() == 0
    assert await db.get_all_users() == []

    await db.add_or_update_user(1001, "Alice", "alice_tg")
    await db.add_or_update_user(1002, "Bob", None)

    assert await db.get_user_count() == 2
    users = await db.get_all_users()
    assert 1001 in users
    assert 1002 in users

    # Update Alice's name
    await db.add_or_update_user(1001, "Alice Updated", "alice_new")
    assert await db.get_user_count() == 2


@pytest.mark.asyncio
async def test_chat_tracking_and_welcome_toggle(tmp_path):
    """Test group registration and welcome message settings."""
    db_file = tmp_path / "test_chats.sqlite3"
    db = Database(db_file)
    await db.init()

    assert await db.get_chat_count() == 0
    await db.add_or_update_chat(-100555444, "Movies Discussion", "supergroup")

    assert await db.get_chat_count() == 1
    # Welcome should default to True
    assert await db.get_chat_welcome(-100555444) is True

    # Disable welcome
    await db.set_chat_welcome(-100555444, False)
    assert await db.get_chat_welcome(-100555444) is False

    # Re-enable welcome
    await db.set_chat_welcome(-100555444, True)
    assert await db.get_chat_welcome(-100555444) is True


@pytest.mark.asyncio
async def test_manual_and_global_filters(tmp_path):
    """Test group-specific and global keyword filters."""
    db_file = tmp_path / "test_filters.sqlite3"
    db = Database(db_file)
    await db.init()

    chat_id = -100999

    # Add chat-specific filter
    await db.add_filter(chat_id, "rules", "Be respectful to all members!")
    filt = await db.get_filter(chat_id, "rules")
    assert filt is not None
    assert filt["reply_text"] == "Be respectful to all members!"

    # Add global filter (chat_id = 0)
    await db.add_filter(0, "support", "Contact @AdminSupport for help.")
    
    # Check that chat inherits global filter
    global_match = await db.get_filter(chat_id, "support")
    assert global_match is not None
    assert global_match["reply_text"] == "Contact @AdminSupport for help."

    # Chat filter should override global filter
    await db.add_filter(chat_id, "support", "Local support: ping group owner.")
    override_match = await db.get_filter(chat_id, "support")
    assert override_match["reply_text"] == "Local support: ping group owner."

    # Deleting chat filter
    assert await db.delete_filter(chat_id, "rules") is True
    assert await db.get_filter(chat_id, "rules") is None

    # Clear all chat filters
    count = await db.delete_all_filters(chat_id)
    assert count >= 1


@pytest.mark.asyncio
async def test_batch_links_storage_and_retrieval(tmp_path):
    """Test saving and getting batch links."""
    db_file = tmp_path / "test_batch.sqlite3"
    db = Database(db_file)
    await db.init()

    batch_id = "test_batch_123"
    codes = ["code_a", "code_b", "code_c"]
    await db.save_batch_link(batch_id, codes, created_by=999)

    retrieved = await db.get_batch_link(batch_id)
    assert retrieved == codes

    # Non-existent batch
    assert await db.get_batch_link("invalid_batch") is None


@pytest.mark.asyncio
async def test_paginated_search(tmp_path):
    """Test search_files_paginated with pagination offsets."""
    db_file = tmp_path / "test_search.sqlite3"
    db = Database(db_file)
    await db.init()

    # Register 5 test files
    for i in range(1, 6):
        await db.register_file(
            file_id=f"fid_{i}",
            file_unique_id=f"fuid_{i}",
            file_type="video",
            file_name=f"Inception.2010.Part{i}.mp4",
            file_size=1024 * i,
            caption="Christopher Nolan Movie",
            uploaded_by=1,
        )

    # Page 1 (limit 2)
    items, total = await db.search_files_paginated("Inception", offset=0, limit=2)
    assert total == 5
    assert len(items) == 2

    # Page 2 (offset 2, limit 2)
    items_p2, total2 = await db.search_files_paginated("Inception", offset=2, limit=2)
    assert total2 == 5
    assert len(items_p2) == 2
    assert items[0]["id"] != items_p2[0]["id"]


@pytest.mark.asyncio
async def test_force_subscription_check(monkeypatch):
    """Test is_user_subscribed helper with mocked Telegram bot."""
    bot_mock = AsyncMock()

    # 1. No channel configured -> should return True
    monkeypatch.setattr("handlers.fsub_helper.AUTH_CHANNEL_ID", None)
    assert await is_user_subscribed(bot_mock, 12345) is True

    # 2. Channel configured and user is member
    monkeypatch.setattr("handlers.fsub_helper.AUTH_CHANNEL_ID", -1001234567890)
    member_mock = MagicMock()
    member_mock.status = ChatMemberStatus.MEMBER
    bot_mock.get_chat_member.return_value = member_mock

    assert await is_user_subscribed(bot_mock, 12345) is True

    # 3. Channel configured and user has left
    member_mock.status = ChatMemberStatus.LEFT
    assert await is_user_subscribed(bot_mock, 12345) is False


def test_parse_duration_seconds():
    """Test parsing of moderation time durations."""
    assert parse_duration_seconds("30m") == 1800
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds("1d") == 86400
    assert parse_duration_seconds("invalid") is None
