import pytest
from unittest.mock import AsyncMock, patch
from handlers.admin_handlers import backup_command


@pytest.mark.asyncio
async def test_backup_command_unauthorized():
    update = AsyncMock()
    update.effective_user.id = 999999999  # unauthorized user
    context = AsyncMock()
    context.bot_data = {"db": AsyncMock()}

    await backup_command(update, context)

    # Should deny access
    update.effective_message.reply_text.assert_called_once()
    assert "restricted to administrators" in update.effective_message.reply_text.call_args[0][0]
