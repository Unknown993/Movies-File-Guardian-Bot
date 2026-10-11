"""
Force Subscription (FSUB) validation helper.
Ensures users join the required update/log channel before receiving files.
"""

from __future__ import annotations

import logging
from typing import Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import TelegramError, BadRequest

from config import AUTH_CHANNEL_ID, FORCE_SUB_TEXT

logger = logging.getLogger(__name__)


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """
    Check if a user is subscribed to the mandatory channel (AUTH_CHANNEL_ID).
    Returns True if subscribed or if no channel is configured.
    """
    if not AUTH_CHANNEL_ID:
        return True

    try:
        member = await bot.get_chat_member(chat_id=AUTH_CHANNEL_ID, user_id=user_id)
        if member.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,
        ]:
            return True
        return False
    except BadRequest as e:
        if "User not found" in e.message or "user not found" in e.message.lower():
            return False
        logger.warning("BadRequest during subscription check for user %s: %s", user_id, e.message)
        # If bot lacks admin rights to view chat members, fail-open
        return True
    except TelegramError as e:
        logger.error("TelegramError during subscription check: %s", e)
        return True


async def send_fsub_alert(
    bot: Bot,
    chat_id: int,
    retry_payload: str,
    bot_username: str,
) -> Optional[Message]:
    """
    Send the Force Subscription join notice with interactive buttons.
    """
    if not AUTH_CHANNEL_ID:
        return None

    # Determine channel link
    channel_link = ""
    if isinstance(AUTH_CHANNEL_ID, str) and AUTH_CHANNEL_ID.startswith("@"):
        channel_link = f"https://t.me/{AUTH_CHANNEL_ID.lstrip('@')}"
    else:
        try:
            invite = await bot.create_chat_invite_link(chat_id=AUTH_CHANNEL_ID)
            channel_link = invite.invite_link
        except Exception as e:
            logger.error("Could not create channel invite link for %s: %s", AUTH_CHANNEL_ID, e)
            channel_link = f"https://t.me/{str(AUTH_CHANNEL_ID).replace('-100', '')}"

    retry_link = f"https://t.me/{bot_username}?start={retry_payload}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Update Channel", url=channel_link)],
        [InlineKeyboardButton("🔄 Try Again", url=retry_link)],
    ])

    return await bot.send_message(
        chat_id=chat_id,
        text=FORCE_SUB_TEXT,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
