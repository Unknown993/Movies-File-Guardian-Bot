"""Unit tests for MR.Guardian_bot / Professor-Bot features ported to TeleBot."""

import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch

from database import Database
from handlers.menu_handlers import (
    get_start_keyboard,
    get_help_keyboard,
    menu_callback_handler,
)
from handlers.inline_handlers import inline_query_handler
from handlers.extra_features import (
    json_command,
    font_command,
    share_command,
    password_command,
    written_command,
    set_template_command,
    get_template_command,
    instatus_command,
    transform_font,
    FONTS,
)
from handlers.extended_commands import connection_callback_handler


def test_start_and_help_keyboards():
    """Verify inline button keyboards match MR.Guardian_bot specifications."""
    start_kb = get_start_keyboard("TestBot")
    assert len(start_kb.inline_keyboard) == 5  # Add Me | Search+TopSearch | VIP+Trial | About+Help | Disclaimer+Donate
    # Check button texts
    all_buttons = [btn for row in start_kb.inline_keyboard for btn in row]
    btn_texts = [btn.text for btn in all_buttons]
    assert any("Aᴅᴅ Mᴇ" in t for t in btn_texts)
    assert any("Sᴇᴀʀᴄʜ 🔎" in t for t in btn_texts)
    assert any("Hᴇʟᴘ 🕸️" in t for t in btn_texts)
    assert any("Aʙᴏᴜᴛ ✨" in t for t in btn_texts)

    help_kb = get_help_keyboard()
    help_texts = [btn.text for row in help_kb.inline_keyboard for btn in row]
    assert any("Aᴅᴍɪɴ Pᴀɴᴇʟ" in t for t in help_texts)
    assert any("Fɪʟᴛᴇʀs" in t for t in help_texts)
    assert any("Cᴏɴɴᴇᴄᴛ" in t for t in help_texts)
    assert any("Fɪʟᴇ Sᴛᴏʀᴇ" in t for t in help_texts)
    assert any("Exᴛʀᴀ Mᴏᴅᴇ" in t for t in help_texts)
    assert any("Gʀᴏᴜᴘ Mᴀɴᴀɢᴇʀ" in t for t in help_texts)
    assert any("Bᴏᴛ Sᴛᴀᴛᴜs ❄️" in t for t in help_texts)
    assert any("✘ Cʟᴏsᴇ" in t for t in help_texts)


@pytest.mark.asyncio
async def test_database_group_settings_and_helpers(tmp_path):
    """Test group settings storage, active connection, and filename indexing."""
    db_file = tmp_path / "test_group_settings.sqlite3"
    db = Database(db_file)
    await db.init()

    # 1. Group settings defaults
    settings = await db.get_group_settings(-100999)
    assert settings["button"] is True
    assert settings["spell_check"] is True

    # 2. Save group setting
    await db.save_group_settings(-100999, "button", False)
    await db.save_group_settings(-100999, "template", "Custom Template 123")
    settings = await db.get_group_settings(-100999)
    assert settings["button"] is False
    assert settings["template"] == "Custom Template 123"

    # 3. Filenames indexing
    await db.register_file(
        file_id="fid_123",
        file_unique_id="fuid_123",
        file_type="document",
        file_name="Avengers Endgame 2019 1080p.mkv",
        file_size=1048576,
    )
    names = await db.get_all_filenames()
    assert "Avengers Endgame 2019 1080p.mkv" in names

    # 4. DB size
    assert db.get_db_size() > 0

    # 5. Active connection
    await db.add_connection(user_id=111, chat_id=-100999)
    active = await db.get_active_connection(111)
    assert active == -100999


@pytest.mark.asyncio
async def test_menu_callback_handler(tmp_path):
    """Test interactive menu callback navigation."""
    db_file = tmp_path / "test_menu.sqlite3"
    db = Database(db_file)
    await db.init()

    bot_mock = AsyncMock()
    bot_mock.get_me = AsyncMock(return_value=MagicMock(first_name="GuardianBot", username="GuardianBot"))

    # Test menu_help
    query_mock = AsyncMock()
    query_mock.data = "menu_help"
    query_mock.edit_message_text = AsyncMock()
    query_mock.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query_mock
    update.effective_user = MagicMock(first_name="Alice", id=123)

    context = MagicMock()
    context.bot = bot_mock
    context.bot_data = {"db": db}

    await menu_callback_handler(update, context)
    assert query_mock.edit_message_text.called
    assert query_mock.answer.called

    # Test menu_stats
    query_mock.data = "menu_stats"
    await menu_callback_handler(update, context)
    assert query_mock.edit_message_text.called

    # Test menu_about
    query_mock.data = "menu_about"
    await menu_callback_handler(update, context)
    assert query_mock.edit_message_text.called


@pytest.mark.asyncio
async def test_inline_query_handler(tmp_path):
    """Test @botusername inline search handler."""
    db_file = tmp_path / "test_inline.sqlite3"
    db = Database(db_file)
    await db.init()

    await db.register_file(
        file_id="fid_inline_1",
        file_unique_id="fuid_inline_1",
        file_type="video",
        file_name="Spider Man No Way Home.mp4",
        file_size=2097152,
    )

    inline_q = MagicMock()
    inline_q.query = "Spider Man"
    inline_q.answer = AsyncMock()

    update = MagicMock()
    update.inline_query = inline_q

    context = MagicMock()
    context.bot.get_me = AsyncMock(return_value=MagicMock(username="TeleBot"))
    context.bot_data = {"db": db}

    await inline_query_handler(update, context)
    assert inline_q.answer.called
    results = inline_q.answer.call_args[0][0]
    assert len(results) == 1
    assert "Spider Man" in results[0].title


@pytest.mark.asyncio
async def test_extra_commands_json_and_font():
    """Test /json and /font utilities."""
    # Test font transformation
    styled = transform_font("Hello", FONTS["Typewriter"])
    assert styled == "𝙷𝚎𝚕𝚕𝚘"

    # Test /json command
    msg_mock = MagicMock()
    msg_mock.to_dict.return_value = {"message_id": 42, "text": "Test"}
    msg_mock.reply_to_message = None
    msg_mock.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_message = msg_mock

    context = MagicMock()
    await json_command(update, context)
    assert msg_mock.reply_text.called


@pytest.mark.asyncio
async def test_extra_commands_password_and_share():
    """Test /password and /share commands."""
    # Test /password
    msg_mock = MagicMock()
    msg_mock.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_message = msg_mock

    context = MagicMock()
    context.args = ["16"]
    await password_command(update, context)
    assert msg_mock.reply_text.called
    reply_text = msg_mock.reply_text.call_args[0][0]
    assert "16" in reply_text

    # Test /share
    context.args = ["Join", "Our", "Channel"]
    await share_command(update, context)
    assert msg_mock.reply_text.called


@pytest.mark.asyncio
async def test_template_management(tmp_path):
    """Test /set_template and /get_template."""
    db_file = tmp_path / "test_tmpl.sqlite3"
    db = Database(db_file)
    await db.init()

    msg_mock = AsyncMock()
    msg_mock.reply_text = AsyncMock()

    chat_mock = MagicMock(id=-100555, type="supergroup")
    user_mock = MagicMock(id=999)

    update = MagicMock()
    update.effective_message = msg_mock
    update.effective_chat = chat_mock
    update.effective_user = user_mock

    context = MagicMock()
    context.args = ["🎬", "{title}", "({year})"]
    context.bot_data = {"db": db}

    # Patch is_caller_admin
    with patch("handlers.extra_features.is_caller_admin", AsyncMock(return_value=True)):
        await set_template_command(update, context)
        assert msg_mock.reply_text.called
        assert "Template updated" in msg_mock.reply_text.call_args[0][0]

        await get_template_command(update, context)
        assert "🎬 {title} ({year})" in msg_mock.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_interactive_connection_callback(tmp_path):
    """Test interactive connection callback handler."""
    db_file = tmp_path / "test_conn_cb.sqlite3"
    db = Database(db_file)
    await db.init()

    user_id = 777
    chat_id = -100888
    await db.add_connection(user_id, chat_id)

    query_mock = AsyncMock()
    query_mock.data = f"conn_view_{chat_id}"
    query_mock.edit_message_text = AsyncMock()
    query_mock.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query_mock
    update.effective_user = MagicMock(id=user_id)

    context = MagicMock()
    context.bot.get_chat = AsyncMock(return_value=MagicMock(title="My Movie Group"))
    context.bot_data = {"db": db}

    # 1. View connection
    await connection_callback_handler(update, context)
    assert query_mock.edit_message_text.called
    assert "My Movie Group" in query_mock.edit_message_text.call_args[0][0]

    # 2. Disconnect connection
    query_mock.data = f"conn_dis_{chat_id}"
    await connection_callback_handler(update, context)
    # Verify connection was removed
    conns = await db.get_user_connections(user_id)
    assert chat_id not in conns
