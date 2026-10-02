"""Unit tests for admin & developer command handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram.constants import ParseMode

import config
from config import DeliveryMode
from database import Database
from handlers.admin_handlers import set_mode_command, set_timer_command, get_mode_command


@pytest.mark.asyncio
async def test_set_mode_developer_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEVELOPER_ID", 777)
    db_file = tmp_path / "test_admin.sqlite3"
    db = Database(db_file)
    await db.init()

    # 1. Non-developer tries to change mode
    non_dev_update = MagicMock()
    non_dev_update.effective_user.id = 888
    non_dev_update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"db": db}
    context.args = ["downloadable"]

    await set_mode_command(non_dev_update, context)

    # Mode in DB should still be view_only
    assert await db.get_delivery_mode() == DeliveryMode.VIEW_ONLY
    non_dev_update.effective_message.reply_text.assert_awaited_once()
    assert "Access Denied" in non_dev_update.effective_message.reply_text.call_args[0][0]

    # 2. Developer changes mode to downloadable
    dev_update = MagicMock()
    dev_update.effective_user.id = 777
    dev_update.effective_message.reply_text = AsyncMock()

    await set_mode_command(dev_update, context)

    # Mode in DB must now be downloadable
    assert await db.get_delivery_mode() == DeliveryMode.DOWNLOADABLE
    dev_update.effective_message.reply_text.assert_awaited_once()
    assert "Successfully Updated" in dev_update.effective_message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_set_timer_developer_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEVELOPER_ID", 777)
    db_file = tmp_path / "test_admin_timer.sqlite3"
    db = Database(db_file)
    await db.init()

    # Non-dev attempts to set timer
    non_dev_update = MagicMock()
    non_dev_update.effective_user.id = 999
    non_dev_update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"db": db}
    context.args = ["300"]

    await set_timer_command(non_dev_update, context)
    assert await db.get_auto_delete_seconds() == 180

    # Developer sets timer to 300
    dev_update = MagicMock()
    dev_update.effective_user.id = 777
    dev_update.effective_message.reply_text = AsyncMock()

    await set_timer_command(dev_update, context)
    assert await db.get_auto_delete_seconds() == 300
