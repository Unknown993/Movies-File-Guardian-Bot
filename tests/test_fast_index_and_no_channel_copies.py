import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from handlers.fast_index_handlers import get_db_gap_info, fast_index_command
from handlers.file_handlers import handle_media_upload


@pytest.mark.asyncio
async def test_get_db_gap_info_empty(tmp_path):
    db_file = tmp_path / "test.db"
    import aiosqlite
    async with aiosqlite.connect(str(db_file)) as db:
        await db.execute("""
            CREATE TABLE files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_code TEXT UNIQUE,
                source_chat_id INTEGER,
                source_message_id INTEGER
            );
        """)
        await db.commit()

    total, resume_id, max_id, gap_size = await get_db_gap_info(db_file, -100123)
    assert total == 0
    assert resume_id == 0
    assert max_id == 0
    assert gap_size == 0


@pytest.mark.asyncio
async def test_get_db_gap_info_with_gap(tmp_path):
    db_file = tmp_path / "test.db"
    import aiosqlite
    async with aiosqlite.connect(str(db_file)) as db:
        await db.execute("""
            CREATE TABLE files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_code TEXT UNIQUE,
                source_chat_id INTEGER,
                source_message_id INTEGER
            );
        """)
        # Insert contiguous 1 to 500, then jump to 5000
        for i in range(1, 501):
            await db.execute("INSERT INTO files (file_code, source_chat_id, source_message_id) VALUES (?, ?, ?);", (f"c{i}", -100123, i))
        await db.execute("INSERT INTO files (file_code, source_chat_id, source_message_id) VALUES (?, ?, ?);", ("c5000", -100123, 5000))
        await db.commit()

    total, resume_id, max_id, gap_size = await get_db_gap_info(db_file, -100123)
    assert total == 501
    assert resume_id == 500  # Identified resume point at the gap
    assert max_id == 5000
    assert gap_size == 4500


@pytest.mark.asyncio
async def test_handle_media_upload_does_not_copy_if_already_in_channel():
    update = MagicMock()
    context = MagicMock()

    user = MagicMock(id=999)
    chat = MagicMock(id=-1001878553187) # Matches STORAGE_CHANNEL_ID
    message = MagicMock(message_id=42, caption="Sample video", video=MagicMock(file_id="vid1", file_unique_id="u1", file_name="video.mp4", file_size=1024), document=None, audio=None, photo=None, voice=None, animation=None, video_note=None)
    message.reply_text = AsyncMock()
    message.forward_from_chat = None

    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message

    db_mock = AsyncMock()
    context.bot_data = {"db": db_mock}
    context.bot = AsyncMock()

    with patch("handlers.file_handlers.is_admin", return_value=True), \
         patch("handlers.file_handlers.STORAGE_CHANNEL_ID", -1001878553187):
        await handle_media_upload(update, context)

    # Assert that context.bot.copy_message was NEVER called to repost the file to the channel
    context.bot.copy_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_media_upload_with_ptb_v21_forward_origin():
    """Verify forwarding a message from a channel in PTB v21+ (where forward_from_chat does not exist) works cleanly."""
    from handlers.file_handlers import extract_forward_channel_info

    class DummyOriginChat:
        id = -1001878553187
        title = "Storage Channel"

    class DummyForwardOrigin:
        chat = DummyOriginChat()
        message_id = 555

    class StrictPTBv21Message:
        """Simulates PTB v21+ Message which raises AttributeError on forward_from_chat."""
        message_id = 99
        caption = "Movie.2026.1080p.mkv"
        document = MagicMock(file_id="doc1", file_unique_id="u_doc1", file_name="Movie.2026.1080p.mkv", file_size=2048)
        video = None
        audio = None
        photo = None
        voice = None
        animation = None
        video_note = None
        forward_origin = DummyForwardOrigin()
        reply_text = AsyncMock()

    msg = StrictPTBv21Message()
    ch_id, msg_id, ch_title = extract_forward_channel_info(msg)
    assert ch_id == -1001878553187
    assert msg_id == 555
    assert ch_title == "Storage Channel"

    update = MagicMock()
    update.effective_user = MagicMock(id=8371005605)
    update.effective_chat = MagicMock(id=8371005605)  # Private DM
    update.effective_message = msg

    db_mock = AsyncMock()
    db_mock.get_file_by_source_message.return_value = None
    db_mock.register_file.return_value = "abc123xyz"
    context = MagicMock()
    context.bot_data = {"db": db_mock}
    context.bot = AsyncMock()

    with patch("handlers.file_handlers.is_admin", return_value=True), \
         patch("handlers.file_handlers.STORAGE_CHANNEL_ID", -1001878553187):
        await handle_media_upload(update, context)

    # Should NOT copy back to channel since it was forwarded from a channel
    context.bot.copy_message.assert_not_called()
    msg.reply_text.assert_awaited_once()
    args, kwargs = msg.reply_text.call_args
    assert "Source Channel:" in args[0]
    assert "#555" in args[0]

