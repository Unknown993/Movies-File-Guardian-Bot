"""
Automated Telegram Stars Payment & Premium Subscription Gatekeeper.
Enables:
1. Automated in-app payments with Telegram Stars (currency: XTR).
2. Paywall switch: Toggle between Open Free Access and Paid-Only Access.
3. Subscription tracking with automatic extension, IST expiration calculation, and reminders.
4. Free Trial (5-Min VIP Trial) & /trial_reset.
5. Referral System (+10 pts per referral, 100 pts = 1 Month Free VIP).
6. Gift / Redeem Codes (/add_redeem & /redeem).
7. Administrative commands to view, grant, revoke, and inspect subscriptions.
8. Work-related operational logging to LOG_CHANNEL / PREMIUM_LOGS.
"""

from __future__ import annotations

import re
import html
import time
import urllib.parse
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
    PREMIUM_LOGS,
    OWNER_UPI_ID,
    OWNER_LNK,
    QR_CODE,
    send_work_log,
)
from database import Database

logger = logging.getLogger(__name__)

# Pattern for duration parsing: e.g. "30 days", "1 month", "7d", "1 year", "12 hours"
DURATION_RE = re.compile(r"^(\d+)\s*(s|sec|seconds?|m|min|minutes?|h|hours?|d|days?|w|weeks?|mo|months?|y|years?)$", re.IGNORECASE)


def parse_duration_string(text: str) -> Optional[int]:
    """Parse human duration text into total seconds."""
    text = text.strip().lower()
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
    """Format Unix timestamp to IST human representation."""
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    dt_ist = dt_utc.astimezone(ist_tz)
    return f"{dt_ist.strftime('%d-%m-%Y %I:%M:%S %p')} IST"


def split_date_time_ist(ts: float) -> Tuple[str, str]:
    """Return (DD-MM-YYYY, HH:MM:SS AM/PM) in Asia/Kolkata IST."""
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    dt_ist = dt_utc.astimezone(ist_tz)
    return dt_ist.strftime("%d-%m-%Y"), dt_ist.strftime("%I:%M:%S %p")


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
        [InlineKeyboardButton("💎 Vɪᴇᴡ Pʀᴇᴍɪᴜᴍ Pʟᴀɴs", callback_data="show_plans")],
        [
            InlineKeyboardButton("🎁 5-Mɪɴ Fʀᴇᴇ Tʀɪᴀʟ", callback_data="give_trial"),
            InlineKeyboardButton("🔗 Rᴇғᴇʀ & Eᴀʀɴ", callback_data="refer_menu"),
        ],
        [InlineKeyboardButton("👤 Mʏ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ", callback_data="show_myplan")],
    ])
    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


def _build_plans_keyboard(plans: Dict[int, Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Build detailed inline keyboard for VIP Plans menu."""
    buttons = []
    for stars in sorted(plans.keys()):
        p = plans[stars]
        btn_label = f"⭐ {p['name']} — {stars} Stars"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"buy_star_{stars}")])

    buttons.append([
        InlineKeyboardButton("🎁 Fʀᴇᴇ Tʀɪᴀʟ", callback_data="give_trial"),
        InlineKeyboardButton("🔗 Rᴇғᴇʀ Fʀɪᴇɴᴅs", callback_data="refer_menu"),
    ])
    buttons.append([
        InlineKeyboardButton("🎟️ Rᴇᴅᴇᴇᴍ Cᴏᴅᴇ", callback_data="redeem_info"),
        InlineKeyboardButton("💳 UPI / QR Pᴀʏ", callback_data="upi_info"),
    ])
    buttons.append([
        InlineKeyboardButton("👤 Mʏ Pʟᴀɴ", callback_data="show_myplan"),
        InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan"),
    ])
    return InlineKeyboardMarkup(buttons)


# =============================================================================
# User Payment & Plan Interface
# =============================================================================

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display available subscription tiers with one-tap Telegram Stars purchase & extras."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    plans = await db.get_star_plans()
    paywall_status = await db.is_paywall_enabled()

    text = (
        f"🌟 <b><u>VIP Pʀᴇᴍɪᴜᴍ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Pʟᴀɴs</u></b>\n\n"
        f"✨ <b><u>VIP Mᴇᴍʙᴇʀsʜɪᴘ Bᴇɴᴇғɪᴛs:</u></b>\n"
        f"• ⚡ <b>Iɴsᴛᴀɴᴛ Dɪʀᴇᴄᴛ Fɪʟᴇs</b> (Nᴏ Aᴅs / Nᴏ Vᴇʀɪғɪᴄᴀᴛɪᴏɴ)\n"
        f"• 📦 <b>Sᴇɴᴅ Aʟʟ Fɪʟᴇs</b> ɪɴ Oɴᴇ Tᴀᴘ\n"
        f"• 🎬 <b>Qᴜᴀʟɪᴛʏ, Lᴀɴɢᴜᴀɢᴇ & Sᴇᴀsᴏɴ</b> Fɪʟᴛᴇʀs\n"
        f"• 🔓 <b>Uɴʟɪᴍɪᴛᴇᴅ Hɪɢʜ-Sᴘᴇᴇᴅ</b> Mᴏᴠɪᴇs & Sᴇʀɪᴇs\n\n"
        f"💳 <b>Aᴜᴛᴏᴍᴀᴛᴇᴅ Pᴀʏᴍᴇɴᴛ:</b> Pᴏᴡᴇʀᴇᴅ ᴠɪᴀ <b>Tᴇʟᴇɢʀᴀᴍ Sᴛᴀʀs ⭐</b>\n"
        f"🛡️ <b>Aᴄᴄᴇss Mᴏᴅᴇ:</b> {'🔒 Pᴀɪᴅ Mᴇᴍʙᴇʀs Oɴʟʏ' if paywall_status else '🟢 Fʀᴇᴇ (VIP Pᴇʀᴋs Aᴄᴛɪᴠᴇ)'}\n\n"
        f"👇 <b>Sᴇʟᴇᴄᴛ ᴀ ᴘʟᴀɴ ʙᴇʟᴏᴡ ᴏʀ ᴄʟᴀɪᴍ ᴀ Fʀᴇᴇ Tʀɪᴀʟ:</b>"
    )

    await message.reply_text(
        text=text,
        reply_markup=_build_plans_keyboard(plans),
        parse_mode=ParseMode.HTML,
    )


async def myplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display current user's detailed subscription status."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    sub = await db.get_user_subscription(user.id)
    refer_pts = await db.get_refer_points(user.id)
    now = time.time()

    is_privileged = is_developer(user.id) or is_admin(user.id)
    safe_name = html.escape(user.first_name or "User")

    if is_privileged:
        text = (
            f"👑 <b><u>Aᴅᴍɪɴ / Dᴇᴠᴇʟᴏᴘᴇʀ Aᴄᴄᴇss</u></b>\n\n"
            f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
            f"🆔 <b>Usᴇʀ ID:</b> <code>{user.id}</code>\n"
            f"🔗 <b>Rᴇғᴇʀʀᴀʟ Pᴏɪɴᴛs:</b> <code>{refer_pts}/100</code>\n"
            f"✨ <b>Sᴛᴀᴛᴜs:</b> Pᴇʀᴍᴀɴᴇɴᴛ Uɴʀᴇsᴛʀɪᴄᴛᴇᴅ VIP Aᴄᴄᴇss\n"
        )
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    if sub and sub["expires_at"] > now:
        remaining = sub["expires_at"] - now
        exp_date, exp_time = split_date_time_ist(sub["expires_at"])
        time_left_str = format_remaining_time(remaining)

        text = (
            f"⚜️ <b><u>Yᴏᴜʀ VIP Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Sᴛᴀᴛᴜs</u></b>\n\n"
            f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
            f"🆔 <b>Usᴇʀ ID:</b> <code>{user.id}</code>\n"
            f"📦 <b>Cᴜʀʀᴇɴᴛ Pʟᴀɴ:</b> <code>{html.escape(sub.get('plan_name', 'VIP'))}</code>\n"
            f"⭐ <b>Tᴏᴛᴀʟ Sᴛᴀʀs Pᴀɪᴅ:</b> <code>{sub.get('stars_paid', 0)}</code>\n"
            f"🔗 <b>Rᴇғᴇʀʀᴀʟ Pᴏɪɴᴛs:</b> <code>{refer_pts}/100</code>\n"
            f"📅 <b>Exᴘɪʀʏ Dᴀᴛᴇ:</b> <code>{exp_date}</code>\n"
            f"⏱️ <b>Exᴘɪʀʏ Tɪᴍᴇ:</b> <code>{exp_time} IST</code>\n"
            f"⏳ <b>Tɪᴍᴇ Rᴇᴍᴀɪɴɪɴɢ:</b> <code>{time_left_str}</code>\n\n"
            f"🎉 <i>Tʜᴀɴᴋ ʏᴏᴜ ғᴏʀ sᴜᴘᴘᴏʀᴛɪɴɢ ᴏᴜʀ sᴇʀᴠɪᴄᴇ!</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Exᴛᴇɴᴅ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ", callback_data="show_plans")],
            [InlineKeyboardButton("🔗 Rᴇғᴇʀ & Eᴀʀɴ Fʀᴇᴇ VIP", callback_data="refer_menu")],
            [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")],
        ])
    else:
        paywall_on = await db.is_paywall_enabled()
        trial_used = await db.has_claimed_trial(user.id)
        buttons = [[InlineKeyboardButton("💎 Vɪᴇᴡ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Pʟᴀɴs", callback_data="show_plans")]]
        if not trial_used:
            buttons.append([InlineKeyboardButton("🎁 Cʟᴀɪᴍ 5-Mɪɴ Fʀᴇᴇ Tʀɪᴀʟ", callback_data="give_trial")])
        buttons.append([
            InlineKeyboardButton("🔗 Rᴇғᴇʀ & Eᴀʀɴ", callback_data="refer_menu"),
            InlineKeyboardButton("🎟️ Rᴇᴅᴇᴇᴍ Cᴏᴅᴇ", callback_data="redeem_info"),
        ])
        buttons.append([InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")])

        text = (
            f"👤 <b><u>Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Sᴛᴀᴛᴜs</u></b>\n\n"
            f"Hᴇʏ {safe_name}, ʏᴏᴜ ᴄᴜʀʀᴇɴᴛʟʏ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴ ᴀᴄᴛɪᴠᴇ VIP sᴜʙsᴄʀɪᴘᴛɪᴏɴ.\n\n"
            f"🆔 <b>Usᴇʀ ID:</b> <code>{user.id}</code>\n"
            f"🔗 <b>Rᴇғᴇʀʀᴀʟ Pᴏɪɴᴛs:</b> <code>{refer_pts}/100</code>\n"
            f"🔒 <b>Mᴇᴍʙᴇʀs-Oɴʟʏ Pᴀʏᴡᴀʟʟ:</b> {'Aᴄᴛɪᴠᴇ (VIP Rᴇǫᴜɪʀᴇᴅ)' if paywall_on else 'Iɴᴀᴄᴛɪᴠᴇ (Pᴜʙʟɪᴄ Aᴄᴄᴇss)'}\n\n"
            f"Sᴜʙsᴄʀɪʙᴇ ɴᴏᴡ ᴡɪᴛʜ Tᴇʟᴇɢʀᴀᴍ Sᴛᴀʀs, ᴄʟᴀɪᴍ ᴀ Fʀᴇᴇ Tʀɪᴀʟ, ᴏʀ ʀᴇғᴇʀ ғʀɪᴇɴᴅs!"
        )
        keyboard = InlineKeyboardMarkup(buttons)

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
            provider_token="",
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
    charge_id = payment.telegram_payment_charge_id

    db: Database = context.bot_data["db"]
    plans = await db.get_star_plans()
    plan = plans.get(amount)

    if plan:
        plan_name = plan["name"]
        duration_seconds = plan["days"] * 86400
    else:
        days = max(1, amount // 2)
        plan_name = f"{days} Days Custom Pass"
        duration_seconds = days * 86400

    now = time.time()
    sub = await db.add_or_extend_subscription(
        user_id=user.id,
        plan_name=plan_name,
        stars=amount,
        duration_seconds=duration_seconds,
    )

    join_date, join_time = split_date_time_ist(now)
    exp_date, exp_time = split_date_time_ist(sub["expires_at"])
    time_left_str = format_remaining_time(sub["expires_at"] - now)
    safe_name = html.escape(user.first_name or "User")

    success_text = (
        f"🎉 <b><u>Pᴀʏᴍᴇɴᴛ Sᴜᴄᴄᴇssғᴜʟ! VIP Aᴄᴛɪᴠᴀᴛᴇᴅ</u></b> ✅\n\n"
        f"Tʜᴀɴᴋ ʏᴏᴜ <b>{safe_name}</b>, ʏᴏᴜʀ ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴠᴇʀɪғɪᴇᴅ!\n\n"
        f"📦 <b>Pʟᴀɴ:</b> <code>{html.escape(plan_name)}</code>\n"
        f"⭐ <b>Aᴍᴏᴜɴᴛ Pᴀɪᴅ:</b> <code>{amount} Stars</code>\n"
        f"📅 <b>Jᴏɪɴɪɴɢ Dᴀᴛᴇ:</b> <code>{join_date} | {join_time}</code>\n"
        f"⌛ <b>Exᴘɪʀʏ Dᴀᴛᴇ:</b> <code>{exp_date} | {exp_time}</code>\n"
        f"⏳ <b>Tɪᴍᴇ Lᴇғᴛ:</b> <code>{time_left_str}</code>\n"
        f"🔖 <b>Tʀᴀɴsᴀᴄᴛɪᴏɴ ID:</b> <code>{charge_id}</code>\n\n"
        f"Eɴᴊᴏʏ ʏᴏᴜʀ ᴜɴʟɪᴍɪᴛᴇᴅ ʜɪɢʜ-sᴘᴇᴇᴅ ᴀᴄᴄᴇss! 🚀"
    )

    await message.reply_text(
        text=success_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Vɪᴇᴡ Mʏ Pʟᴀɴ", callback_data="show_myplan")],
        ]),
    )

    # Log work-related event to LOG_CHANNEL / PREMIUM_LOGS (never STORAGE_CHANNEL_ID)
    log_text = (
        f"💰 <b>#New_Premium_Purchase</b>\n\n"
        f"👤 <b>Usᴇʀ:</b> <a href='tg://user?id={user.id}'>{safe_name}</a> (<code>{user.id}</code>)\n"
        f"📦 <b>Pʟᴀɴ:</b> <code>{html.escape(plan_name)}</code>\n"
        f"⭐ <b>Sᴛᴀʀs:</b> <code>{amount}</code>\n"
        f"📅 <b>Jᴏɪɴɪɴɢ:</b> <code>{join_date} {join_time}</code>\n"
        f"⌛ <b>Exᴘɪʀʏ:</b> <code>{exp_date} {exp_time}</code>\n"
        f"🔖 <b>Cʜᴀʀɢᴇ ID:</b> <code>{charge_id}</code>"
    )
    await send_work_log(context.bot, db, log_text, channel_override=PREMIUM_LOGS)


async def payment_navigation_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle navigation buttons for plans, subscriptions, free trial, referrals, redeem, and UPI."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    db: Database = context.bot_data["db"]
    user = query.from_user
    safe_name = html.escape(user.first_name or "User")

    if data == "show_plans":
        plans = await db.get_star_plans()
        paywall_status = await db.is_paywall_enabled()
        text = (
            f"🌟 <b><u>VIP Pʀᴇᴍɪᴜᴍ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Pʟᴀɴs</u></b>\n\n"
            f"✨ <b><u>VIP Mᴇᴍʙᴇʀsʜɪᴘ Bᴇɴᴇғɪᴛs:</u></b>\n"
            f"• ⚡ <b>Iɴsᴛᴀɴᴛ Dɪʀᴇᴄᴛ Fɪʟᴇs</b> (Nᴏ Aᴅs)\n"
            f"• 📦 <b>Sᴇɴᴅ Aʟʟ Fɪʟᴇs</b> ɪɴ Oɴᴇ Tᴀᴘ\n"
            f"• 🎬 <b>Qᴜᴀʟɪᴛʏ, Lᴀɴɢᴜᴀɢᴇ & Sᴇᴀsᴏɴ</b> Fɪʟᴛᴇʀs\n\n"
            f"🛡️ <b>Aᴄᴄᴇss Mᴏᴅᴇ:</b> {'🔒 Pᴀɪᴅ Mᴇᴍʙᴇʀs Oɴʟʏ' if paywall_status else '🟢 Fʀᴇᴇ (VIP Pᴇʀᴋs Aᴄᴛɪᴠᴇ)'}\n\n"
            f"👇 <b>Sᴇʟᴇᴄᴛ ᴀ ᴘʟᴀɴ ʙᴇʟᴏᴡ ᴛᴏ ᴘᴀʏ ɪɴsᴛᴀɴᴛʟʏ ᴡɪᴛʜ Tᴇʟᴇɢʀᴀᴍ Sᴛᴀʀs ⭐:</b>"
        )
        markup = _build_plans_keyboard(plans)
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer()

    elif data == "show_myplan":
        sub = await db.get_user_subscription(user.id)
        refer_pts = await db.get_refer_points(user.id)
        now = time.time()
        is_privileged = is_developer(user.id) or is_admin(user.id)

        if is_privileged:
            text = (
                f"👑 <b><u>Aᴅᴍɪɴ / Dᴇᴠᴇʟᴏᴘᴇʀ Aᴄᴄᴇss</u></b>\n\n"
                f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
                f"🆔 <b>Usᴇʀ ID:</b> <code>{user.id}</code>\n"
                f"🔗 <b>Rᴇғᴇʀ Pᴏɪɴᴛs:</b> <code>{refer_pts}/100</code>\n"
                f"✨ <b>Sᴛᴀᴛᴜs:</b> Pᴇʀᴍᴀɴᴇɴᴛ Uɴʀᴇsᴛʀɪᴄᴛᴇᴅ Aᴄᴄᴇss\n"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Vɪᴇᴡ Pʟᴀɴs", callback_data="show_plans")],
                [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")],
            ])
        elif sub and sub["expires_at"] > now:
            time_left_str = format_remaining_time(sub["expires_at"] - now)
            exp_date, exp_time = split_date_time_ist(sub["expires_at"])
            text = (
                f"⚜️ <b><u>Yᴏᴜʀ VIP Sᴜʙsᴄʀɪᴘᴛɪᴏɴ</u></b>\n\n"
                f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
                f"🆔 <b>Usᴇʀ ID:</b> <code>{user.id}</code>\n"
                f"📦 <b>Pʟᴀɴ:</b> <code>{html.escape(sub.get('plan_name', 'VIP'))}</code>\n"
                f"🔗 <b>Rᴇғᴇʀ Pᴏɪɴᴛs:</b> <code>{refer_pts}/100</code>\n"
                f"📅 <b>Exᴘɪʀʏ Dᴀᴛᴇ:</b> <code>{exp_date}</code>\n"
                f"⏱️ <b>Exᴘɪʀʏ Tɪᴍᴇ:</b> <code>{exp_time} IST</code>\n"
                f"⏳ <b>Tɪᴍᴇ Lᴇғᴛ:</b> <code>{time_left_str}</code>"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Exᴛᴇɴᴅ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ", callback_data="show_plans")],
                [InlineKeyboardButton("🔗 Rᴇғᴇʀ & Eᴀʀɴ", callback_data="refer_menu")],
                [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")],
            ])
        else:
            trial_used = await db.has_claimed_trial(user.id)
            rows = [[InlineKeyboardButton("💎 Vɪᴇᴡ Pʟᴀɴs", callback_data="show_plans")]]
            if not trial_used:
                rows.append([InlineKeyboardButton("🎁 Cʟᴀɪᴍ 5-Mɪɴ Fʀᴇᴇ Tʀɪᴀʟ", callback_data="give_trial")])
            rows.append([
                InlineKeyboardButton("🔗 Rᴇғᴇʀ Fʀɪᴇɴᴅs", callback_data="refer_menu"),
                InlineKeyboardButton("🎟️ Rᴇᴅᴇᴇᴍ Cᴏᴅᴇ", callback_data="redeem_info"),
            ])
            rows.append([InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")])
            text = (
                f"👤 <b><u>Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Sᴛᴀᴛᴜs</u></b>\n\n"
                f"Hᴇʏ {safe_name}, ʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴ ᴀᴄᴛɪᴠᴇ VIP sᴜʙsᴄʀɪᴘᴛɪᴏɴ.\n"
                f"🔗 <b>Rᴇғᴇʀʀᴀʟ Pᴏɪɴᴛs:</b> <code>{refer_pts}/100</code>"
            )
            markup = InlineKeyboardMarkup(rows)
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer()

    elif data == "give_trial":
        if await db.has_claimed_trial(user.id):
            await query.answer(
                "⚠️ You have already used your 1-time Free Trial! Subscribe or Refer friends for more VIP access.",
                show_alert=True,
            )
            return

        sub = await db.claim_free_trial(user.id, duration_seconds=300)
        exp_date, exp_time = split_date_time_ist(sub["expires_at"])
        await query.answer("🎁 5-Minute Free VIP Trial Activated!", show_alert=True)

        text = (
            f"🎁 <b><u>Fʀᴇᴇ VIP Tʀɪᴀʟ Aᴄᴛɪᴠᴀᴛᴇᴅ!</u></b> ✅\n\n"
            f"👤 <b>Usᴇʀ:</b> {safe_name} (<code>{user.id}</code>)\n"
            f"📦 <b>Pʟᴀɴ:</b> <code>Free Trial (5 Min)</code>\n"
            f"📅 <b>Exᴘɪʀʏ Dᴀᴛᴇ:</b> <code>{exp_date}</code>\n"
            f"⏱️ <b>Exᴘɪʀʏ Tɪᴍᴇ:</b> <code>{exp_time} IST</code>\n"
            f"⏳ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>5 Minutes</code>\n\n"
            f"🚀 <i>Tᴇsᴛ ᴏᴜᴛ ᴀʟʟ VIP Pʀᴇᴍɪᴜᴍ ғᴇᴀᴛᴜʀᴇs ɴᴏᴡ!</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Uᴘɢʀᴀᴅᴇ Tᴏ Fᴜʟʟ VIP", callback_data="show_plans")],
            [InlineKeyboardButton("👤 Mʏ Pʟᴀɴ", callback_data="show_myplan")],
        ])
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

        await send_work_log(
            context.bot,
            db,
            f"🎁 <b>#Free_Trial_Claimed</b>\n\n"
            f"👤 <b>Usᴇʀ:</b> <a href='tg://user?id={user.id}'>{safe_name}</a> (<code>{user.id}</code>)\n"
            f"⏱️ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>5 Minutes</code>\n"
            f"⌛ <b>Exᴘɪʀᴇs:</b> <code>{exp_date} {exp_time} IST</code>",
            channel_override=PREMIUM_LOGS,
        )

    elif data == "refer_menu":
        bot_me = await context.bot.get_me()
        bot_username = bot_me.username or "Bot"
        refer_link = f"https://t.me/{bot_username}?start=reff_{user.id}"
        pts = await db.get_refer_points(user.id)
        share_url = f"https://t.me/share/url?url={urllib.parse.quote(refer_link)}&text={urllib.parse.quote('🎬 Get instant Movies & Series here!')}"

        text = (
            f"🔗 <b><u>Rᴇғᴇʀ & Eᴀʀɴ Fʀᴇᴇ VIP</u></b>\n\n"
            f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
            f"🏆 <b>Yᴏᴜʀ Pᴏɪɴᴛs:</b> <code>{pts} / 100</code>\n\n"
            f"📌 <b>Hᴏᴡ Iᴛ Wᴏʀᴋs:</b>\n"
            f"• Sʜᴀʀᴇ ʏᴏᴜʀ ᴜɴɪǫᴜᴇ ʀᴇғᴇʀʀᴀʟ ʟɪɴᴋ ᴡɪᴛʜ ғʀɪᴇɴᴅs.\n"
            f"• Eᴀᴄʜ ɴᴇᴡ ᴜsᴇʀ ᴡʜᴏ sᴛᴀʀᴛs ᴛʜᴇ ʙᴏᴛ ɢɪᴠᴇs ʏᴏᴜ <b>+10 Pᴏɪɴᴛs</b>.\n"
            f"• Rᴇᴀᴄʜ <b>100 Pᴏɪɴᴛs</b> ᴛᴏ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴜɴʟᴏᴄᴋ <b>1 Mᴏɴᴛʜ Fʀᴇᴇ VIP</b>!\n\n"
            f"🔗 <b>Yᴏᴜʀ Rᴇғᴇʀʀᴀʟ Lɪɴᴋ:</b>\n<code>{refer_link}</code>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Sʜᴀʀᴇ Rᴇғᴇʀʀᴀʟ Lɪɴᴋ", url=share_url)],
            [
                InlineKeyboardButton(f"📊 Pᴏɪɴᴛs: {pts}/100", callback_data="ref_point"),
                InlineKeyboardButton("💎 VIP Pʟᴀɴs", callback_data="show_plans"),
            ],
            [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")],
        ])
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer()

    elif data == "ref_point":
        pts = await db.get_refer_points(user.id)
        needed = max(0, 100 - pts)
        await query.answer(
            f"🏆 You have {pts}/100 Referral Points!\nInvite {needed // 10} more friend(s) to unlock 1 Month Free VIP.",
            show_alert=True,
        )

    elif data == "redeem_info":
        text = (
            f"🎟️ <b><u>Rᴇᴅᴇᴇᴍ VIP Gɪғᴛ Cᴏᴅᴇ</u></b>\n\n"
            f"Hᴀᴠᴇ ᴀ VIP ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ? Aᴄᴛɪᴠᴀᴛᴇ ɪᴛ ɪɴsᴛᴀɴᴛʟʏ ᴜsɪɴɢ:\n\n"
            f"👉 <code>/redeem VIP-XXXXXXXXXX</code>\n\n"
            f"<i>Cᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ᴏʀ ᴊᴏɪɴ ᴏᴜʀ ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ ғᴏʀ ɢɪᴠᴇᴀᴡᴀʏ ᴄᴏᴅᴇs!</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Bᴀᴄᴋ Tᴏ Pʟᴀɴs", callback_data="show_plans")],
            [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close_plan")],
        ])
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer()

    elif data == "upi_info":
        text = (
            f"💳 <b><u>UPI / QR & Sᴛᴀʀs Pᴀʏᴍᴇɴᴛ</u></b>\n\n"
            f"⚡ <b>Iɴsᴛᴀɴᴛ Aᴜᴛᴏ-Aᴄᴛɪᴠᴀᴛɪᴏɴ:</b>\n"
            f"• Sᴇʟᴇᴄᴛ ᴀɴʏ <b>Tᴇʟᴇɢʀᴀᴍ Sᴛᴀʀs ⭐</b> ᴘʟᴀɴ ᴏɴ ᴛʜᴇ ᴘʀᴇᴠɪᴏᴜs ᴍᴇɴᴜ ғᴏʀ ɪɴsᴛᴀɴᴛ ᴀᴜᴛᴏᴍᴀᴛɪᴄ VIP ᴀᴄᴛɪᴠᴀᴛɪᴏɴ.\n\n"
            f"🏦 <b>Mᴀɴᴜᴀʟ UPI Pᴀʏᴍᴇɴᴛ:</b>\n"
            f"• <b>UPI ID:</b> <code>{html.escape(OWNER_UPI_ID)}</code>\n"
            f"• Aғᴛᴇʀ ᴘᴀʏᴍᴇɴᴛ, sᴇɴᴅ ᴀ sᴄʀᴇᴇɴsʜᴏᴛ ᴡɪᴛʜ ʏᴏᴜʀ ID (<code>{user.id}</code>) ᴛᴏ Admin."
        )
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👨‍💻 Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ", url=OWNER_LNK),
                InlineKeyboardButton("📷 QR Cᴏᴅᴇ", url=QR_CODE),
            ],
            [InlineKeyboardButton("« Bᴀᴄᴋ Tᴏ Pʟᴀɴs", callback_data="show_plans")],
        ])
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        await query.answer()

    elif data == "close_plan":
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer()


# =============================================================================
# Referral, Redeem & Trial Reset Commands
# =============================================================================

async def refer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user's referral link and points: /refer."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    db: Database = context.bot_data["db"]
    bot_me = await context.bot.get_me()
    bot_username = bot_me.username or "Bot"
    refer_link = f"https://t.me/{bot_username}?start=reff_{user.id}"
    pts = await db.get_refer_points(user.id)
    safe_name = html.escape(user.first_name or "User")
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(refer_link)}&text={urllib.parse.quote('🎬 Get instant Movies & Series here!')}"

    text = (
        f"🔗 <b><u>Rᴇғᴇʀ & Eᴀʀɴ Fʀᴇᴇ VIP</u></b>\n\n"
        f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
        f"🏆 <b>Yᴏᴜʀ Pᴏɪɴᴛs:</b> <code>{pts} / 100</code>\n\n"
        f"• Iɴᴠɪᴛᴇ ғʀɪᴇɴᴅs ᴜsɪɴɢ ʏᴏᴜʀ ʟɪɴᴋ (+10 Pᴏɪɴᴛs ᴘᴇʀ ʀᴇғᴇʀʀᴀʟ).\n"
        f"• Cᴏʟʟᴇᴄᴛ <b>100 Pᴏɪɴᴛs</b> ᴛᴏ ɢᴇᴛ <b>1 Mᴏɴᴛʜ Fʀᴇᴇ VIP</b> ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ!\n\n"
        f"🔗 <b>Yᴏᴜʀ Rᴇғᴇʀʀᴀʟ Lɪɴᴋ:</b>\n<code>{refer_link}</code>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Sʜᴀʀᴇ Rᴇғᴇʀʀᴀʟ Lɪɴᴋ", url=share_url)],
        [
            InlineKeyboardButton(f"📊 Pᴏɪɴᴛs: {pts}/100", callback_data="ref_point"),
            InlineKeyboardButton("💎 VIP Pʟᴀɴs", callback_data="show_plans"),
        ],
    ])
    await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


async def add_redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to generate VIP gift/redeem codes:
    Usage: /add_redeem <duration> [count]
    Example: /add_redeem 1 month 5
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "📌 <b>Usage:</b> <code>/add_redeem &lt;duration&gt; [count]</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/add_redeem 7 days 1</code>\n"
            "• <code>/add_redeem 1 month 5</code>\n"
            "• <code>/add_redeem 1 year 2</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Check if last arg is count
    count = 1
    duration_tokens = list(args)
    if len(args) >= 2 and args[-1].isdigit():
        # Could be "/add_redeem 1 month 5" or "/add_redeem 7d 5"
        test_dur = " ".join(args[:-1])
        if parse_duration_string(test_dur):
            count = max(1, min(int(args[-1]), 50))
            duration_tokens = args[:-1]

    duration_str = " ".join(duration_tokens)
    seconds = parse_duration_string(duration_str)
    if not seconds or seconds <= 0:
        await message.reply_text(
            "❌ <b>Invalid Duration Format!</b>\n"
            "Examples: <code>7 days</code>, <code>1 month</code>, <code>1 year</code>, <code>12 hours</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    db: Database = context.bot_data["db"]
    codes = await db.create_redeem_codes(
        duration_str=duration_str,
        duration_seconds=seconds,
        count=count,
        created_by=user.id,
    )

    code_lines = "\n".join(f"• <code>/redeem {c}</code>" for c in codes)
    text = (
        f"🎟️ <b><u>VIP Rᴇᴅᴇᴇᴍ Cᴏᴅᴇs Gᴇɴᴇʀᴀᴛᴇᴅ!</u></b>\n\n"
        f"⏱️ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>{html.escape(duration_str)}</code>\n"
        f"🔢 <b>Qᴜᴀɴᴛɪᴛʏ:</b> <code>{len(codes)}</code>\n\n"
        f"👇 <b>Tᴀᴘ ᴀ ᴄᴏᴅᴇ ᴛᴏ ᴄᴏᴘʏ:</b>\n{code_lines}"
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)

    await send_work_log(
        context.bot,
        db,
        f"🎟️ <b>#Redeem_Codes_Generated</b>\n\n"
        f"👑 <b>Aᴅᴍɪɴ:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'Admin')}</a> (<code>{user.id}</code>)\n"
        f"⏱️ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>{html.escape(duration_str)}</code>\n"
        f"🔢 <b>Cᴏᴜɴᴛ:</b> <code>{len(codes)}</code>",
        channel_override=PREMIUM_LOGS,
    )


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User command to redeem a VIP gift code: /redeem <code>."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    args = context.args or []
    if not args:
        await message.reply_text(
            "🎟️ <b>Usage:</b> <code>/redeem VIP-XXXXXXXXXX</code>\n\n"
            "Enter a valid gift code to activate your VIP subscription.",
            parse_mode=ParseMode.HTML,
        )
        return

    code_str = args[0].strip().upper()
    db: Database = context.bot_data["db"]
    record = await db.consume_redeem_code(code_str, user.id)
    if not record:
        await message.reply_text(
            "❌ <b>Invalid or Already Used Redeem Code!</b>\n\n"
            "Please check the code and try again.",
            parse_mode=ParseMode.HTML,
        )
        return

    duration_str = record["duration_str"]
    seconds = int(record["duration_seconds"])
    now = time.time()
    sub = await db.add_or_extend_subscription(
        user_id=user.id,
        plan_name=f"Redeemed ({duration_str})",
        stars=0,
        duration_seconds=seconds,
    )

    join_date, join_time = split_date_time_ist(now)
    exp_date, exp_time = split_date_time_ist(sub["expires_at"])
    safe_name = html.escape(user.first_name or "User")

    await message.reply_text(
        f"🎉 <b><u>Rᴇᴅᴇᴇᴍ Cᴏᴅᴇ Aᴄᴛɪᴠᴀᴛᴇᴅ!</u></b> ✅\n\n"
        f"👤 <b>Usᴇʀ:</b> {safe_name}\n"
        f"🎟️ <b>Cᴏᴅᴇ:</b> <code>{html.escape(code_str)}</code>\n"
        f"⏱️ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>{html.escape(duration_str)}</code>\n"
        f"📅 <b>Aᴄᴛɪᴠᴀᴛᴇᴅ:</b> <code>{join_date} | {join_time}</code>\n"
        f"⌛ <b>Exᴘɪʀᴇs Oɴ:</b> <code>{exp_date} | {exp_time} IST</code>\n\n"
        f"🚀 <i>Eɴᴊᴏʏ ʏᴏᴜʀ VIP Pʀᴇᴍɪᴜᴍ Aᴄᴄᴇss!</i>",
        parse_mode=ParseMode.HTML,
    )

    await send_work_log(
        context.bot,
        db,
        f"🎟️ <b>#Redeem_Premium</b>\n\n"
        f"👤 <b>Usᴇʀ:</b> <a href='tg://user?id={user.id}'>{safe_name}</a> (<code>{user.id}</code>)\n"
        f"🎟️ <b>Cᴏᴅᴇ:</b> <code>{html.escape(code_str)}</code>\n"
        f"⏱️ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>{html.escape(duration_str)}</code>\n"
        f"⌛ <b>Exᴘɪʀʏ:</b> <code>{exp_date} {exp_time} IST</code>",
        channel_override=PREMIUM_LOGS,
    )


async def trial_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to reset free trial eligibility: /trial_reset [user_id]."""
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    if not (is_developer(user.id) or is_admin(user.id)):
        await message.reply_text("⛔ **Access Denied:** Administrator command only.", parse_mode=ParseMode.MARKDOWN)
        return

    db: Database = context.bot_data["db"]
    args = context.args or []
    target_uid: Optional[int] = None
    if args and args[0].isdigit():
        target_uid = int(args[0])

    count = await db.reset_free_trial(target_uid)
    if target_uid is not None:
        await message.reply_text(
            f"✅ Free trial eligibility reset for user <code>{target_uid}</code> ({count} record cleared).",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"✅ Reset free trial records for all users (<code>{count}</code> record(s) cleared).",
            parse_mode=ParseMode.HTML,
        )


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

    now = time.time()
    db: Database = context.bot_data["db"]
    sub = await db.add_or_extend_subscription(
        user_id=target_user_id,
        plan_name=f"Manual Grant ({duration_str})",
        stars=0,
        duration_seconds=seconds,
    )

    join_date, join_time = split_date_time_ist(now)
    exp_date, exp_time = split_date_time_ist(sub["expires_at"])
    expiry_str = format_timestamp_ist(sub["expires_at"])

    await message.reply_text(
        f"✅ **Premium Added Successfully!**\n\n"
        f"👤 **User ID:** `{target_user_id}`\n"
        f"⏱️ **Duration Added:** `{duration_str}`\n"
        f"📅 **Joining Date:** `{join_date} | {join_time}`\n"
        f"⌛ **New Expiry Date:** `{expiry_str}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                f"🎉 <b><u>VIP Pʀᴇᴍɪᴜᴍ Gʀᴀɴᴛᴇᴅ!</u></b>\n\n"
                f"Aɴ ᴀᴅᴍɪɴɪsᴛʀᴀᴛᴏʀ ʜᴀs ᴀᴄᴛɪᴠᴀᴛᴇᴅ ʏᴏᴜʀ VIP sᴜʙsᴄʀɪᴘᴛɪᴏɴ ғᴏʀ <b>{html.escape(duration_str)}</b>!\n"
                f"📅 <b>Jᴏɪɴɪɴɢ Dᴀᴛᴇ:</b> <code>{join_date} | {join_time}</code>\n"
                f"⌛ <b>Exᴘɪʀʏ Dᴀᴛᴇ:</b> <code>{exp_date} | {exp_time} IST</code>\n\n"
                f"Eɴᴊᴏʏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴀᴄᴄᴇss!"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await send_work_log(
        context.bot,
        db,
        f"👑 <b>#Added_Premium</b>\n\n"
        f"👮 <b>Aᴅᴍɪɴ:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'Admin')}</a> (<code>{user.id}</code>)\n"
        f"👤 <b>Usᴇʀ ID:</b> <code>{target_user_id}</code>\n"
        f"⏱️ <b>Dᴜʀᴀᴛɪᴏɴ:</b> <code>{html.escape(duration_str)}</code>\n"
        f"⌛ <b>Exᴘɪʀʏ:</b> <code>{exp_date} {exp_time} IST</code>",
        channel_override=PREMIUM_LOGS,
    )


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
        await send_work_log(
            context.bot,
            db,
            f"🚫 <b>#Removed_Premium</b>\n\n"
            f"👮 <b>Aᴅᴍɪɴ:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'Admin')}</a> (<code>{user.id}</code>)\n"
            f"👤 <b>Usᴇʀ ID:</b> <code>{target_user_id}</code>",
            channel_override=PREMIUM_LOGS,
        )
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
    exp_date, exp_time = split_date_time_ist(sub["expires_at"])
    expiry_str = format_timestamp_ist(sub["expires_at"])
    time_left = format_remaining_time(sub["expires_at"] - now) if is_active else "Expired"

    await message.reply_text(
        f"📊 **User Subscription Record:**\n\n"
        f"👤 **User ID:** `{target_user_id}`\n"
        f"📦 **Plan:** `{sub.get('plan_name')}`\n"
        f"⭐ **Stars Paid:** `{sub.get('stars_paid', 0)}`\n"
        f"⚡ **Status:** {'🟢 Active' if is_active else '🔴 Expired'}\n"
        f"📅 **Expiry Date:** `{exp_date} | ⏱️ {exp_time}`\n"
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
        exp_date, exp_time = split_date_time_ist(s["expires_at"])
        lines.append(
            f"{idx}. User ID: `{s['user_id']}` | Plan: `{s.get('plan_name', 'VIP')}` | Exp: `{exp_date} {exp_time}` | Left: `{rem}`"
        )

    text = "\n".join(lines[:50])
    if len(lines) > 50:
        text += f"\n\n*... and {len(lines) - 50} more subscribers.*"

    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
