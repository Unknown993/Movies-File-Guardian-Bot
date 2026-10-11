"""
Automated Telegram Stars Payment & Premium Subscription Gatekeeper.
Enables:
1. Automated in-app payments with Telegram Stars (currency: XTR).
2. Paywall switch: Toggle between Open Free Access and Paid-Only Access.
3. Subscription tracking with automatic extension, expiration calculation, and reminders.
4. Administrative commands to view, grant, revoke, and inspect subscriptions.
"""

from __future__ import annotations

import re
import html
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple

from telegram import (
    Update,
    LabeledPrice,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    PreCheckoutQuery,
)
from telegram.constants import ParseMode, ChatType
from telegram.ext import ContextTypes

from config import (
    is_developer,
    is_admin,
    PAYWALL_ALERT_TEXT,
    STORAGE_CHANNEL_ID,
)
from database import Database

logger = logging.getLogger(__name__)

# Pattern for duration parsing: e.g. "30 days", "1 month", "7d", "1 year", "12 hours"
DURATION_RE = re.compile(r"^(\d+)\s*(s|sec|seconds?|m|min|minutes?|h|hours?|d|days?|w|weeks?|mo|months?|y|years?)$", re.IGNORECASE)


def parse_duration_string(text: str) -> Optional[int]:
    """Parse human duration text into total seconds."""
    text = text.strip().lower()
    # Normalize space between number and unit (e.g. "30days" -> "30 days")
    match = re.match(r"^(\d+)\s*([a-zA-Z]+)$", text)
    if not match:
        return None
    val = int(match.group(1))
    unit = match.group(2)

    if unit in ("s", "sec", "second", "seconds"):
        return val
    elif unit in ("m", "min", "minute", "minutes"):
        return val * 60
    elif unit in ("h", "hr", "hour", "hours"):
        return val * 3600
    elif unit in ("d", "day", "days"):
        return val * 86400
    elif unit in ("w", "wk", "week", "weeks"):
        return val * 7 * 86400
    elif unit in ("mo", "month", "months"):
        return val * 30 * 86400
    elif unit in ("y", "yr", "year", "years"):
        return val * 365 * 86400
    return None


def format_remaining_time(seconds: float) -> str:
    """Format remaining seconds into readable days, hours, minutes."""
    if seconds <= 0:
        return "Expired"
    total_secs = int(seconds)
    days = total_secs // 86400
    hours = (total_secs % 86400) // 3600
    minutes = (total_secs % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{total_secs}s")
    return " ".join(parts)


def format_timestamp_ist(ts: float) -> str:
    """Format Unix timestamp to IST and UTC human representation."""
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    # IST is UTC+5:30
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    dt_ist = dt_utc.astimezone(ist_tz)
    return f"{dt_ist.strftime('%d-%m-%Y %I:%M %p')} IST"


async def check_user_access(db: Database, user_id: int) -> bool:
    """
    Check if a user has access under current paywall policies.
    - If paywall is disabled: Everyone has access.
    - If user is Developer or Admin: Full access granted.
    - If user has active paid subscription: Access granted.
    - Otherwise: Access denied.
    """
    is_paywall_on = await db.is_paywall_enabled()
    if not is_paywall_on:
        return True
    if is_developer(user_id) or is_admin(user_id):
        return True
    return await db.is_user_premium(user_id)


async def send_paywall_alert(bot, chat_id: int, user_first_name: str) -> None:
    """Send paywall requirement message to locked user."""
    safe_name = html.escape(user_first_name or "User")
    caption = PAYWALL_ALERT_TEXT.format(name=safe_name)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 View Premium Plans", callback_data="show_plans")],
        [InlineKeyboardButton("👤 My Subscription", callback_data="show_myplan")],
    ])
    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
# User Payment & Plan Interface
# =============================================================================

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display available subscription tiers with one-tap Telegram Stars purchase."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    plans = await db.get_star_plans()
    paywall_status = await db.is_paywall_enabled()

    text = (
        f"🌟 <b>VIP Subscription Plans</b>\n\n"
        f"Get full, unrestricted access to all bot features, lightning-fast file delivery, "
        f"and unlimited search results.\n\n"
        f"💳 <b>Automated Payment:</b> Powered directly via <b>Telegram Stars</b> ⭐.\n"
        f"🛡️ <b>Access Mode:</b> {'🔒 Paid Members Only' if paywall_status else '🟢 Free (VIP Perks Active)'}\n\n"
        f"<b>Select a plan below to subscribe instantly:</b>"
    )

    buttons = []
    # Build plan buttons sorted by price
    for stars in sorted(plans.keys()):
        p = plans[stars]
        btn_label = f"⭐ {p['name']} — {stars} Stars"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"buy_star_{stars}")])

    buttons.append([
        InlineKeyboardButton("👤 My Subscription", callback_data="show_myplan"),
        InlineKeyboardButton("❌ Close", callback_data="close_plan"),
    ])

    await message.reply_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def myplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display current user's subscription status."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    sub = await db.get_user_subscription(user.id)
    now = time.time()

    is_privileged = is_developer(user.id) or is_admin(user.id)
    safe_name = html.escape(user.first_name)

    if is_privileged:
        text = (
            f"👑 <b>Admin / Developer Access</b>\n\n"
            f"👤 <b>User:</b> {safe_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"✨ <b>Status:</b> Permanent Unrestricted Access\n"
        )
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    if sub and sub["expires_at"] > now:
        remaining = sub["expires_at"] - now
        expiry_str = format_timestamp_ist(sub["expires_at"])
        time_left_str = format_remaining_time(remaining)

        text = (
            f"⚜️ <b>Your VIP Subscription</b>\n\n"
            f"👤 <b>User:</b> {safe_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"📦 <b>Current Plan:</b> <code>{html.escape(sub.get('plan_name', 'VIP'))}</code>\n"
            f"⭐ <b>Total Stars Paid:</b> <code>{sub.get('stars_paid', 0)}</code>\n"
            f"⏳ <b>Time Remaining:</b> <code>{time_left_str}</code>\n"
            f"⌛ <b>Expires On:</b> <code>{expiry_str}</code>\n\n"
            f"🎉 <i>Thank you for supporting our service!</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Extend Subscription", callback_data="show_plans")],
            [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
        ])
    else:
        paywall_on = await db.is_paywall_enabled()
        text = (
            f"👤 <b>Subscription Status</b>\n\n"
            f"Hey {safe_name}, you currently do not have an active VIP subscription.\n\n"
            f"🔒 <b>Members-Only Paywall:</b> {'Active (Subscription Required)' if paywall_on else 'Inactive (Public Access)'}\n\n"
            f"Subscribe now with Telegram Stars to enjoy unlimited downloads and search!"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 View Subscription Plans", callback_data="show_plans")],
            [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
        ])

    await message.reply_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def send_star_invoice(
    bot,
    chat_id: int,
    user_id: int,
    stars_amount: int,
    db: Database,
) -> bool:
    """
    Generate and send Telegram Star Invoice for a specified tier to a private chat.
    Complies with Telegram Bot API requirement:
    - Currency is 'XTR'
    - Provider token is empty string
    - First button in reply_markup must have pay=True
    """
    plans = await db.get_star_plans()
    plan = plans.get(stars_amount)
    if not plan:
        return False

    plan_name = plan["name"]
    plan_days = plan["days"]
    payload = f"stars_sub_{stars_amount}_{user_id}_{int(time.time())}"
    title = f"⭐ VIP Access ({plan_name})"
    description = (
        f"Unlock {plan_days} days of unrestricted VIP access to all files and searches."
    )

    # In Telegram Bot API, if custom reply_markup is provided, the first button must be pay=True
    invoice_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ Pay {stars_amount} Stars", pay=True)],
        [InlineKeyboardButton("❌ Cancel Order", callback_data="close_plan")],
    ])

    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Required empty string for Telegram Stars (XTR)
            currency="XTR",
            prices=[LabeledPrice(label=plan_name, amount=stars_amount)],
            reply_markup=invoice_markup,
        )
        return True
    except Exception as e:
        logger.error("Failed to dispatch Stars invoice to chat %s: %s", chat_id, e)
        return False


async def buy_star_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send Telegram Star Invoice for selected tier."""
    query = update.callback_query
    if not query or not query.data:
        return

    try:
        stars_amount = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.answer("Invalid plan selected.", show_alert=True)
        return

    db: Database = context.bot_data["db"]
    user = query.from_user
    chat_type = query.message.chat.type if query.message else ChatType.PRIVATE

    # Invoices can only be sent to private chats. If triggered in group, direct to PM.
    if chat_type != ChatType.PRIVATE:
        sent = await send_star_invoice(
            bot=context.bot,
            chat_id=user.id,
            user_id=user.id,
            stars_amount=stars_amount,
            db=db,
        )
        if sent:
            await query.answer("📩 Invoice sent to your Private Messages (PM)!", show_alert=True)
        else:
            bot_info = await context.bot.get_me()
            bot_username = bot_info.username or "Bot"
            pm_link = f"https://t.me/{bot_username}?start=buy_{stars_amount}"
            redirect_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Open Bot PM to Pay", url=pm_link)]
            ])
            await query.answer()
            await query.message.reply_text(
                f"⚠️ **Invoices must be completed in private messages.**\n\n"
                f"Tap the button below to complete your payment:",
                reply_markup=redirect_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # User is in Private Chat
    target_chat_id = query.message.chat_id if query.message else user.id
    sent = await send_star_invoice(
        bot=context.bot,
        chat_id=target_chat_id,
        user_id=user.id,
        stars_amount=stars_amount,
        db=db,
    )
    if sent:
        await query.answer()
    else:
        await query.answer("Failed to generate invoice. Please try again.", show_alert=True)


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to Telegram PreCheckoutQuery to authorize transaction."""
    query: PreCheckoutQuery = update.pre_checkout_query
    if not query:
        return

    if query.invoice_payload.startswith("stars_sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="⚠️ Unrecognized payment order.")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmed payment receipt and activate subscription."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.successful_payment:
        return

    payment = message.successful_payment
    amount = payment.total_amount
    currency = payment.currency
    charge_id = payment.telegram_payment_charge_id

    db: Database = context.bot_data["db"]
    plans = await db.get_star_plans()
    plan = plans.get(amount)

    if plan:
        plan_name = plan["name"]
        duration_seconds = plan["days"] * 86400
    else:
        # Fallback calculation if custom amount
        days = max(1, amount // 2)
        plan_name = f"{days} Days Custom Pass"
        duration_seconds = days * 86400

    sub = await db.add_or_extend_subscription(
        user_id=user.id,
        plan_name=plan_name,
        stars=amount,
        duration_seconds=duration_seconds,
    )

    expiry_str = format_timestamp_ist(sub["expires_at"])
    time_left_str = format_remaining_time(sub["expires_at"] - time.time())
    safe_name = html.escape(user.first_name)

    success_text = (
        f"🎉 <b>Payment Successful! Subscription Activated</b> ✅\n\n"
        f"Thank you <b>{safe_name}</b>, your automatic payment has been verified!\n\n"
        f"📦 <b>Plan:</b> <code>{html.escape(plan_name)}</code>\n"
        f"⭐ <b>Amount Paid:</b> <code>{amount} Stars</code>\n"
        f"⏳ <b>Time Left:</b> <code>{time_left_str}</code>\n"
        f"⌛ <b>New Expiry Date:</b> <code>{expiry_str}</code>\n"
        f"🔖 <b>Transaction ID:</b> <code>{charge_id}</code>\n\n"
        f"Enjoy your unlimited high-speed access! 🚀"
    )

    await message.reply_text(
        text=success_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 View My Plan", callback_data="show_myplan")],
        ]),
    )

    # Optional audit logging to storage channel
    if STORAGE_CHANNEL_ID:
        try:
            log_text = (
                f"💰 <b>#Star_Payment_Received</b>\n\n"
                f"👤 <b>User:</b> {safe_name} (<code>{user.id}</code>)\n"
                f"📦 <b>Plan:</b> {plan_name}\n"
                f"⭐ <b>Stars:</b> {amount}\n"
                f"⌛ <b>Expiry:</b> {expiry_str}\n"
                f"🔖 <b>Charge ID:</b> <code>{charge_id}</code>"
            )
            await context.bot.send_message(
                chat_id=STORAGE_CHANNEL_ID,
                text=log_text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning("Could not log payment to storage channel: %s", e)


async def payment_navigation_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle navigation buttons for plans and subscriptions."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    db: Database = context.bot_data["db"]
    user = query.from_user

    if data == "show_plans":
        plans = await db.get_star_plans()
        buttons = []
        for stars in sorted(plans.keys()):
            p = plans[stars]
            btn_label = f"⭐ {p['name']} — {stars} Stars"
            buttons.append([InlineKeyboardButton(btn_label, callback_data=f"buy_star_{stars}")])
        buttons.append([
            InlineKeyboardButton("👤 My Subscription", callback_data="show_myplan"),
            InlineKeyboardButton("❌ Close", callback_data="close_plan"),
        ])
        text = (
            f"🌟 <b>VIP Subscription Plans</b>\n\n"
            f"Select a plan below to pay instantly with <b>Telegram Stars</b> ⭐:"
        )
        try:
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        await query.answer()

    elif data == "show_myplan":
        sub = await db.get_user_subscription(user.id)
        now = time.time()
        safe_name = html.escape(user.first_name)
        is_privileged = is_developer(user.id) or is_admin(user.id)

        if is_privileged:
            text = (
                f"👑 <b>Admin / Developer Access</b>\n\n"
                f"👤 <b>User:</b> {safe_name}\n"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                f"✨ <b>Status:</b> Permanent Unrestricted Access\n"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 View Plans", callback_data="show_plans")],
                [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
            ])
        elif sub and sub["expires_at"] > now:
            time_left_str = format_remaining_time(sub["expires_at"] - now)
            expiry_str = format_timestamp_ist(sub["expires_at"])
            text = (
                f"⚜️ <b>Your VIP Subscription</b>\n\n"
                f"👤 <b>User:</b> {safe_name}\n"
                f"📦 <b>Plan:</b> <code>{html.escape(sub.get('plan_name', 'VIP'))}</code>\n"
                f"⏳ <b>Time Left:</b> <code>{time_left_str}</code>\n"
                f"⌛ <b>Expires:</b> <code>{expiry_str}</code>"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Extend Subscription", callback_data="show_plans")],
                [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
            ])
        else:
            text = (
                f"👤 <b>Subscription Status</b>\n\n"
                f"Hey {safe_name}, you do not have an active VIP subscription."
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 View Plans", callback_data="show_plans")],
                [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
            ])
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer()

    elif data == "close_plan":
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer()


# =============================================================================
# Admin Management Commands
# =============================================================================

async def paywall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to toggle or check the Paywall (Paid-Users Only) feature:
    Usage:
    /paywall on      - Enable paywall (only paid users can access files/search)
    /paywall off     - Disable paywall (free access for all)
    /paywall status  - View current state
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    args = context.args or []

    if not args:
        # Show interactive toggle
        current = await db.is_paywall_enabled()
        status_text = "🔒 **ON (Paid Members Only)**" if current else "🟢 **OFF (Free Access for All)**"
        buttons = [
            [
                InlineKeyboardButton("Turn ON 🔒", callback_data="st_paywall_on"),
                InlineKeyboardButton("Turn OFF 🟢", callback_data="st_paywall_off"),
            ],
            [InlineKeyboardButton("📊 View Premium Users", callback_data="st_view_premiums")],
        ]
        await message.reply_text(
            f"🛡️ **Paywall Access Control**\n\n"
            f"**Current State:** {status_text}\n\n"
            f"When **ON**, users without an active paid subscription cannot search or receive files.\n"
            f"When **OFF**, anyone can freely search and receive files.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    subcmd = args[0].lower()
    if subcmd in ("on", "enable", "1", "true"):
        await db.set_paywall_enabled(True)
        await message.reply_text(
            "🔒 **Paywall Enabled!**\n\nThe bot is now in **Paid Members Only** mode. "
            "Only users with an active VIP subscription (or Admins) can access files.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif subcmd in ("off", "disable", "0", "false"):
        await db.set_paywall_enabled(False)
        await message.reply_text(
            "🟢 **Paywall Disabled!**\n\nThe bot is now open for **Free Public Access**.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif subcmd in ("status", "info"):
        current = await db.is_paywall_enabled()
        status_text = "🔒 ON (Paid Only)" if current else "🟢 OFF (Public)"
        active_subs = len(await db.get_all_active_subscriptions())
        await message.reply_text(
            f"📊 **Paywall Status:** `{status_text}`\n"
            f"👥 **Active Subscribers:** `{active_subs}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await message.reply_text(
            "📌 **Usage:** `/paywall <on|off|status>`\n\n"
            "• `/paywall on` — Restrict bot to paid subscribers only\n"
            "• `/paywall off` — Allow all users to access the bot\n"
            "• `/paywall status` — View current status",
            parse_mode=ParseMode.MARKDOWN,
        )


async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to manually grant premium subscription:
    Usage: /add_premium <user_id> <duration>
    Example: /add_premium 123456789 30 days
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if len(args) < 2:
        await message.reply_text(
            "📌 **Usage:** `/add_premium <user_id> <time>`\n\n"
            "**Examples:**\n"
            "• `/add_premium 123456789 7 days`\n"
            "• `/add_premium 123456789 1 month`\n"
            "• `/add_premium 123456789 1 year`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await message.reply_text("❌ Invalid User ID.", parse_mode=ParseMode.MARKDOWN)
        return

    duration_str = " ".join(args[1:])
    seconds = parse_duration_string(duration_str)
    if not seconds or seconds <= 0:
        await message.reply_text(
            "❌ **Invalid Duration Format!**\n"
            "Accepted formats: `7 days`, `1 month`, `1 year`, `12 hours`, `30m`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    db: Database = context.bot_data["db"]
    sub = await db.add_or_extend_subscription(
        user_id=target_user_id,
        plan_name=f"Manual Grant ({duration_str})",
        stars=0,
        duration_seconds=seconds,
    )

    expiry_str = format_timestamp_ist(sub["expires_at"])
    await message.reply_text(
        f"✅ **Premium Added Successfully!**\n\n"
        f"👤 **User ID:** `{target_user_id}`\n"
        f"⏱️ **Duration Added:** `{duration_str}`\n"
        f"⌛ **New Expiry Date:** `{expiry_str}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Attempt to notify target user
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                f"🎉 <b>VIP Premium Granted!</b>\n\n"
                f"An administrator has activated your VIP subscription for <b>{html.escape(duration_str)}</b>!\n"
                f"⌛ <b>Expiry Date:</b> <code>{expiry_str}</code>\n\n"
                f"Enjoy unlimited access!"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to revoke a user's subscription: /remove_premium <user_id>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if not args:
        await message.reply_text("📌 **Usage:** `/remove_premium <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await message.reply_text("❌ Invalid User ID.", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    removed = await db.remove_subscription(target_user_id)
    if removed:
        await message.reply_text(f"✅ Subscription for user `{target_user_id}` has been revoked.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="⚠️ Your VIP subscription access has been revoked by an administrator.",
            )
        except Exception:
            pass
    else:
        await message.reply_text(f"⚠️ No active subscription found for user `{target_user_id}`.", parse_mode=ParseMode.MARKDOWN)


async def get_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to inspect a user's subscription: /get_premium <user_id>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if not args:
        await message.reply_text("📌 **Usage:** `/get_premium <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await message.reply_text("❌ Invalid User ID.", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    sub = await db.get_user_subscription(target_user_id)
    if not sub:
        await message.reply_text(f"ℹ️ User `{target_user_id}` has no subscription records.", parse_mode=ParseMode.MARKDOWN)
        return

    now = time.time()
    is_active = sub["expires_at"] > now
    expiry_str = format_timestamp_ist(sub["expires_at"])
    time_left = format_remaining_time(sub["expires_at"] - now) if is_active else "Expired"

    await message.reply_text(
        f"📊 **User Subscription Record:**\n\n"
        f"👤 **User ID:** `{target_user_id}`\n"
        f"📦 **Plan:** `{sub.get('plan_name')}`\n"
        f"⭐ **Stars Paid:** `{sub.get('stars_paid', 0)}`\n"
        f"⚡ **Status:** {'🟢 Active' if is_active else '🔴 Expired'}\n"
        f"⏳ **Remaining:** `{time_left}`\n"
        f"⌛ **Expires:** `{expiry_str}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def premium_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list all active subscribers: /premium_users."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    subs = await db.get_all_active_subscriptions()
    if not subs:
        await message.reply_text("📭 No active subscribers found.", parse_mode=ParseMode.MARKDOWN)
        return

    lines = [f"👥 **Active VIP Subscribers ({len(subs)}):**\n"]
    now = time.time()
    for idx, s in enumerate(subs, 1):
        rem = format_remaining_time(s["expires_at"] - now)
        lines.append(f"{idx}. User ID: `{s['user_id']}` | Plan: `{s.get('plan_name', 'VIP')}` | Left: `{rem}`")

    text = "\n".join(lines[:50])
    if len(lines) > 50:
        text += f"\n\n*... and {len(lines) - 50} more subscribers.*"

    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
