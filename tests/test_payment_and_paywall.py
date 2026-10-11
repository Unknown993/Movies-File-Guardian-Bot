"""
Unit tests for Automated Telegram Stars Payments and Paywall Access Control.
"""

import pytest
import time
from pathlib import Path
from database import Database
from handlers.payment_handlers import (
    parse_duration_string,
    format_remaining_time,
    check_user_access,
)


@pytest.mark.asyncio
async def test_paywall_toggle(tmp_path):
    """Test default paywall state and toggling."""
    db = Database(tmp_path / "db1.sqlite3")
    await db.init()

    # Default is False
    assert await db.is_paywall_enabled() is False

    # Turn ON
    await db.set_paywall_enabled(True)
    assert await db.is_paywall_enabled() is True

    # Turn OFF
    await db.set_paywall_enabled(False)
    assert await db.is_paywall_enabled() is False


@pytest.mark.asyncio
async def test_add_and_extend_subscription(tmp_path):
    """Test creating a subscription and extending an existing one."""
    db = Database(tmp_path / "db2.sqlite3")
    await db.init()
    user_id = 987654321

    # Initially not premium
    assert await db.is_user_premium(user_id) is False
    assert await db.get_user_subscription(user_id) is None

    # Buy 7 days plan (10 stars)
    sub = await db.add_or_extend_subscription(
        user_id=user_id,
        plan_name="7 Days Pass",
        stars=10,
        duration_seconds=7 * 86400,
    )
    assert sub["user_id"] == user_id
    assert sub["stars_paid"] == 10
    assert await db.is_user_premium(user_id) is True

    first_expiry = sub["expires_at"]

    # Extend with 15 days plan (25 stars)
    extended_sub = await db.add_or_extend_subscription(
        user_id=user_id,
        plan_name="15 Days Pass",
        stars=25,
        duration_seconds=15 * 86400,
    )
    assert extended_sub["stars_paid"] == 35
    assert extended_sub["expires_at"] == pytest.approx(first_expiry + (15 * 86400), abs=2)


@pytest.mark.asyncio
async def test_remove_subscription(tmp_path):
    """Test revoking a subscription."""
    db = Database(tmp_path / "db3.sqlite3")
    await db.init()
    user_id = 11223344
    await db.add_or_extend_subscription(
        user_id=user_id,
        plan_name="VIP",
        stars=50,
        duration_seconds=3600,
    )
    assert await db.is_user_premium(user_id) is True

    # Revoke
    revoked = await db.remove_subscription(user_id)
    assert revoked is True
    assert await db.is_user_premium(user_id) is False


@pytest.mark.asyncio
async def test_check_user_access_policy(tmp_path, monkeypatch):
    """Test access policy under Paywall ON vs OFF."""
    db = Database(tmp_path / "db4.sqlite3")
    await db.init()
    normal_user = 55555
    vip_user = 66666
    admin_user = 77777

    # Mock admin
    monkeypatch.setattr("handlers.payment_handlers.is_admin", lambda uid: uid == admin_user)
    monkeypatch.setattr("handlers.payment_handlers.is_developer", lambda uid: False)

    # Grant VIP to vip_user
    await db.add_or_extend_subscription(
        user_id=vip_user,
        plan_name="1 Month VIP",
        stars=45,
        duration_seconds=30 * 86400,
    )

    # --- Scenario A: Paywall is OFF (Free Mode) ---
    await db.set_paywall_enabled(False)
    assert await check_user_access(db, normal_user) is True
    assert await check_user_access(db, vip_user) is True
    assert await check_user_access(db, admin_user) is True

    # --- Scenario B: Paywall is ON (Paid Members Only) ---
    await db.set_paywall_enabled(True)
    assert await check_user_access(db, normal_user) is False  # Blocked!
    assert await check_user_access(db, vip_user) is True     # Allowed!
    assert await check_user_access(db, admin_user) is True   # Allowed!


@pytest.mark.asyncio
async def test_expired_subscription_sweeper(tmp_path):
    """Test expired subscription retrieval and notification marking."""
    db = Database(tmp_path / "db5.sqlite3")
    await db.init()
    expired_user = 88888
    # Add subscription that expired 10 seconds ago
    await db.add_or_extend_subscription(
        user_id=expired_user,
        plan_name="Trial",
        stars=5,
        duration_seconds=-10,
    )

    assert await db.is_user_premium(expired_user) is False

    due = await db.get_due_expired_subscriptions()
    assert any(item["user_id"] == expired_user for item in due)

    # Mark notified
    await db.mark_subscription_expired_notified(expired_user)
    due_after = await db.get_due_expired_subscriptions()
    assert not any(item["user_id"] == expired_user for item in due_after)


def test_duration_parsing():
    """Test human duration parsing."""
    assert parse_duration_string("7 days") == 7 * 86400
    assert parse_duration_string("1 month") == 30 * 86400
    assert parse_duration_string("1 year") == 365 * 86400
    assert parse_duration_string("2 hours") == 7200
    assert parse_duration_string("30m") == 1800
    assert parse_duration_string("invalid string") is None


def test_format_remaining_time():
    """Test human time formatting."""
    assert format_remaining_time(0) == "Expired"
    assert format_remaining_time(-50) == "Expired"
    assert "1d" in format_remaining_time(86400 + 3600)
    assert "2h" in format_remaining_time(7200)


@pytest.mark.asyncio
async def test_send_star_invoice_has_pay_button(tmp_path):
    """Verify that send_star_invoice configures currency=XTR and first button pay=True."""
    from unittest.mock import AsyncMock
    from handlers.payment_handlers import send_star_invoice

    db = Database(tmp_path / "db_invoice.sqlite3")
    await db.init()

    mock_bot = AsyncMock()
    success = await send_star_invoice(
        bot=mock_bot,
        chat_id=12345,
        user_id=12345,
        stars_amount=10,
        db=db,
    )
    assert success is True
    mock_bot.send_invoice.assert_called_once()
    kwargs = mock_bot.send_invoice.call_args[1]

    assert kwargs["currency"] == "XTR"
    assert kwargs["provider_token"] == ""
    assert kwargs["prices"][0].amount == 10

    # Ensure first button in reply_markup has pay=True
    keyboard = kwargs["reply_markup"].inline_keyboard
    first_btn = keyboard[0][0]
    assert first_btn.pay is True
    assert "Pay 10 Stars" in first_btn.text


@pytest.mark.asyncio
async def test_pre_checkout_handler():
    """Verify that pre_checkout_handler validates invoice payload."""
    from unittest.mock import AsyncMock
    from handlers.payment_handlers import pre_checkout_handler

    # Case A: Valid stars payload
    update_valid = AsyncMock()
    update_valid.pre_checkout_query.invoice_payload = "stars_sub_10_12345_1700000000"
    await pre_checkout_handler(update_valid, AsyncMock())
    update_valid.pre_checkout_query.answer.assert_called_once_with(ok=True)

    # Case B: Invalid payload
    update_invalid = AsyncMock()
    update_invalid.pre_checkout_query.invoice_payload = "unrecognized_order_xyz"
    await pre_checkout_handler(update_invalid, AsyncMock())
    update_invalid.pre_checkout_query.answer.assert_called_once_with(
        ok=False, error_message="⚠️ Unrecognized payment order."
    )


@pytest.mark.asyncio
async def test_successful_payment_handler_activates_vip(tmp_path):
    """Verify that successful_payment_handler records payment and activates VIP subscription."""
    from unittest.mock import AsyncMock, MagicMock
    from handlers.payment_handlers import successful_payment_handler

    db = Database(tmp_path / "db_success.sqlite3")
    await db.init()

    user_id = 778899
    update = AsyncMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = "Alex"
    
    mock_payment = MagicMock()
    mock_payment.total_amount = 25  # 15 days plan
    mock_payment.currency = "XTR"
    mock_payment.telegram_payment_charge_id = "charge_test_123"
    update.effective_message.successful_payment = mock_payment

    context = AsyncMock()
    context.bot_data = {"db": db}

    await successful_payment_handler(update, context)

    # User should now be premium in DB
    assert await db.is_user_premium(user_id) is True
    sub = await db.get_user_subscription(user_id)
    assert sub["stars_paid"] == 25
    assert sub["plan_name"] == "15 Days Pass"
    assert sub["expires_at"] > time.time()

    # Reply should have been sent to user confirming activation
    update.effective_message.reply_text.assert_called_once()
    reply_call = update.effective_message.reply_text.call_args[1]["text"]
    # Handler uses small-caps unicode text; verify key data points are present
    assert "charge_test_123" in reply_call  # transaction ID always in plain ASCII
    assert "15 Days Pass" in reply_call     # plan name always in plain ASCII


@pytest.mark.asyncio
async def test_start_command_deep_link_buy(tmp_path):
    """Verify that /start buy_10 sends invoice without triggering file-not-found."""
    from unittest.mock import AsyncMock
    from handlers.user_handlers import start_command

    db = Database(tmp_path / "db_start.sqlite3")
    await db.init()

    update = AsyncMock()
    update.effective_user.id = 554433
    update.effective_user.first_name = "Sam"
    update.effective_user.username = "sam_user"
    update.effective_chat.id = 554433
    update.effective_chat.type = "private"

    context = AsyncMock()
    context.args = ["buy_10"]
    context.bot_data = {"db": db}

    await start_command(update, context)

    # send_invoice should have been called
    context.bot.send_invoice.assert_called_once()
    kwargs = context.bot.send_invoice.call_args[1]
    assert kwargs["currency"] == "XTR"
    assert kwargs["prices"][0].amount == 10

