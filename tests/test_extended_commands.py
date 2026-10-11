"""Unit tests for newly added extended commands: ping, ban_user, disable_chat, connect, delete, imdb, and clear_junk."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from database import Database
from handlers.extended_commands import format_uptime, ping_command, imdb_command


def test_format_uptime():
    """Test format_uptime converts seconds to readable duration."""
    assert "10s" in format_uptime(10)
    assert "1m" in format_uptime(65)
    assert "1h" in format_uptime(3665)
    assert "1d" in format_uptime(90000)


@pytest.mark.asyncio
async def test_database_ban_and_unban_user(tmp_path):
    """Test bot-level user banning and unbanning in database."""
    db_file = tmp_path / "test_banned.sqlite3"
    db = Database(db_file)
    await db.init()

    # User initially not banned
    is_banned, reason = await db.is_user_banned(12345)
    assert is_banned is False
    assert reason is None

    # Ban user
    await db.ban_user(12345, "Spamming")
    is_banned, reason = await db.is_user_banned(12345)
    assert is_banned is True
    assert reason == "Spamming"

    # Unban user
    assert await db.unban_user(12345) is True
    is_banned, _ = await db.is_user_banned(12345)
    assert is_banned is False


@pytest.mark.asyncio
async def test_database_disable_and_enable_chat(tmp_path):
    """Test chat disabling and re-enabling in database."""
    db_file = tmp_path / "test_disabled.sqlite3"
    db = Database(db_file)
    await db.init()

    chat_id = -100123987

    # Initially not disabled
    is_dis, reason = await db.is_chat_disabled(chat_id)
    assert is_dis is False

    # Disable chat
    await db.disable_chat(chat_id, "Inactivity")
    is_dis, reason = await db.is_chat_disabled(chat_id)
    assert is_dis is True
    assert reason == "Inactivity"

    # Re-enable chat
    assert await db.enable_chat(chat_id) is True
    is_dis, _ = await db.is_chat_disabled(chat_id)
    assert is_dis is False


@pytest.mark.asyncio
async def test_database_connections(tmp_path):
    """Test PM connections between user and groups."""
    db_file = tmp_path / "test_conn.sqlite3"
    db = Database(db_file)
    await db.init()

    user_id = 999
    group1 = -100111
    group2 = -100222

    assert await db.get_user_connections(user_id) == []

    await db.add_connection(user_id, group1)
    await db.add_connection(user_id, group2)

    conns = await db.get_user_connections(user_id)
    assert group1 in conns
    assert group2 in conns

    # Disconnect group1
    assert await db.delete_connection(user_id, group1) is True
    conns_after = await db.get_user_connections(user_id)
    assert group1 not in conns_after
    assert group2 in conns_after


@pytest.mark.asyncio
async def test_database_deleteall_and_delete_by_source(tmp_path):
    """Test deleting all files and deleting by source message."""
    db_file = tmp_path / "test_purge.sqlite3"
    db = Database(db_file)
    await db.init()

    # Register 3 files
    for i in range(1, 4):
        await db.register_file(
            file_id=f"fid_{i}",
            file_unique_id=f"fuid_{i}",
            file_type="document",
            file_name=f"file_{i}.pdf",
            file_size=100,
            source_chat_id=-100888,
            source_message_id=i * 10,
            uploaded_by=1,
        )

    # Delete 1 by source message
    assert await db.delete_file_by_source_message(-100888, 10) is True
    assert await db.get_file_by_source_message(-100888, 10) is None

    # Delete all remaining
    deleted_count = await db.delete_all_files()
    assert deleted_count == 2
    assert (await db.get_stats())["total_files"] == 0


@pytest.mark.asyncio
async def test_imdb_command_lookup():
    """Test /imdb command fetching movie details and sending message."""
    mock_update = MagicMock()
    mock_message = AsyncMock()
    mock_update.effective_message = mock_message

    mock_status_msg = AsyncMock()
    mock_message.reply_text.return_value = mock_status_msg

    mock_context = MagicMock()
    mock_context.args = ["Interstellar"]

    sample_imdb_resp = {
        "d": [
            {
                "l": "Interstellar",
                "y": 2014,
                "s": "Matthew McConaughey, Anne Hathaway",
                "qid": "movie",
                "id": "tt0816692",
                "i": {"imageUrl": "https://m.media-amazon.com/images/interstellar.jpg"},
            }
        ]
    }

    class MockResponse:
        def read(self):
            return json.dumps(sample_imdb_resp).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("urllib.request.urlopen", return_value=MockResponse()):
        await imdb_command(mock_update, mock_context)

    # Status message should be deleted and photo reply attempted
    mock_status_msg.delete.assert_awaited_once()
    mock_message.reply_photo.assert_awaited_once()
    _, kwargs = mock_message.reply_photo.call_args
    assert "Interstellar" in kwargs["caption"]
    assert "Matthew McConaughey" in kwargs["caption"]


@pytest.mark.asyncio
async def test_users_command_with_underscore_usernames(tmp_path):
    """Test /users command properly formats usernames containing underscores using HTML."""
    from handlers.extended_commands import users_command
    from telegram.constants import ParseMode

    db_file = tmp_path / "test_users_cmd.sqlite3"
    db = Database(db_file)
    await db.init()

    await db.add_or_update_user(1001, "Ankush_Test [Admin]", "ankush_user_123")
    await db.add_or_update_user(1002, "User <Two>", None)

    mock_update = MagicMock()
    mock_message = AsyncMock()
    mock_update.effective_message = mock_message
    mock_update.effective_user.id = 6267580864  # developer

    mock_context = MagicMock()
    mock_context.bot_data = {"db": db}

    with patch("handlers.extended_commands.is_admin", return_value=True):
        await users_command(mock_update, mock_context)

    mock_message.reply_text.assert_awaited_once()
    args, kwargs = mock_message.reply_text.call_args
    out_text = args[0]
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert "@ankush_user_123" in out_text
    assert "User &lt;Two&gt;" in out_text


@pytest.mark.asyncio
async def test_info_command_with_underscore_username():
    """Test /info command properly formats usernames containing underscores using HTML."""
    from handlers.moderation_handlers import info_command
    from telegram.constants import ParseMode

    mock_update = MagicMock()
    mock_message = AsyncMock()
    mock_Message_reply = None
    mock_message.reply_to_message = mock_Message_reply
    mock_update.effective_message = mock_message

    mock_user = MagicMock()
    mock_user.id = 6267580864
    mock_user.first_name = "Ankush_Dev"
    mock_user.last_name = "<Admin>"
    mock_user.username = "ankush_dev_bot"
    mock_user.is_bot = False
    mock_update.effective_user = mock_user

    mock_context = MagicMock()
    await info_command(mock_update, mock_context)

    mock_message.reply_text.assert_awaited_once()
    args, kwargs = mock_message.reply_text.call_args
    out_text = args[0]
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert "@ankush_dev_bot" in out_text
    assert "Ankush_Dev &lt;Admin&gt;" in out_text


@pytest.mark.asyncio
async def test_backup_command_large_db_does_not_raise_name_error(tmp_path):
    """Test /backup command when DB > 48 MB does not raise NameError and handles fallback cleanly."""
    from handlers.admin_handlers import backup_command
    from telegram.constants import ParseMode

    db_file = tmp_path / "large_db.sqlite3"
    db_file.write_bytes(b"0" * 16)
    db = Database(db_file)

    mock_update = MagicMock()
    mock_message = AsyncMock()
    mock_status = AsyncMock()
    mock_message.reply_text.return_value = mock_status
    mock_update.effective_message = mock_message
    mock_update.effective_user.id = 6267580864

    mock_context = MagicMock()
    mock_context.bot_data = {"db": db}

    with patch("handlers.admin_handlers.is_admin", return_value=True), \
         patch.object(db, "get_db_size", return_value=60 * 1024 * 1024), \
         patch("handlers.admin_handlers.os.getenv", return_value=""):
        await backup_command(mock_update, mock_context)

    mock_status.edit_text.assert_awaited_once()
    args, kwargs = mock_status.edit_text.call_args
    assert "Database Backup Notice" in args[0]
    assert kwargs["parse_mode"] == ParseMode.HTML


@pytest.mark.asyncio
async def test_group_moderation_in_pm_replies_with_helpful_notice():
    """Test /ban, /mute, /pin, /purge, /dkick, /inkick in PM reply with guidance instead of silently returning."""
    from handlers.moderation_handlers import ban_command, mute_command, pin_command, purge_command
    from handlers.extra_features import dkick_command, inkick_command
    from telegram.constants import ChatType, ParseMode

    for cmd in (ban_command, mute_command, pin_command, purge_command, dkick_command, inkick_command):
        mock_update = MagicMock()
        mock_message = AsyncMock()
        mock_chat = MagicMock()
        mock_chat.type = ChatType.PRIVATE
        mock_update.effective_message = mock_message
        mock_update.effective_chat = mock_chat
        mock_update.effective_user.id = 6267580864

        mock_context = MagicMock()
        await cmd(mock_update, mock_context)

        mock_message.reply_text.assert_awaited_once()
        _, kwargs = mock_message.reply_text.call_args
        assert kwargs["parse_mode"] == ParseMode.HTML

