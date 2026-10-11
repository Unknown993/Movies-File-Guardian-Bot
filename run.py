"""
Main entry point for Telegram Content Protection & File Delivery Bot.
Orchestrates handlers, persistent SQLite database, and auto-destruct JobQueue.
"""

from __future__ import annotations

import os
import sys
import asyncio
import logging
import urllib.request
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from config import (
    BASE_DIR,
    BOT_TOKEN,
    DEVELOPER_ID,
    DATABASE_PATH,
    DeliveryMode,
    send_work_log,
)

# Ensure working directory is always the project root regardless of where CMD launched run.py
try:
    os.chdir(BASE_DIR)
except Exception:
    pass
from database import Database
from delivery import execute_auto_deletion
from handlers.admin_handlers import (
    set_mode_command,
    get_mode_command,
    set_timer_command,
    stats_command,
    mode_callback_query,
    backup_command,
)
from handlers.user_handlers import (
    start_command,
    help_command,
    search_command,
    list_files_command,
    handle_text_search,
    file_callback_query,
)
from handlers.file_handlers import (
    handle_media_upload,
    handle_channel_post,
    index_range_command,
    stop_index_command,
    stop_indexing_callback,
)
from handlers.fast_index_handlers import fast_index_command, fast_index_callback
from handlers.welcome_handlers import (
    handle_new_chat_members,
    welcome_command,
)
from handlers.filter_handlers import (
    handle_filter_or_search,
    filter_pagination_callback,
    filter_extra_callbacks,
    filter_file_click_callback,
    filter_spelling_click_callback,
    filter_command,
    filters_command,
    del_filter_command,
    delall_filters_command,
    gfilter_command,
    gfilters_command,
    delg_filter_command,
    delallg_filters_command,
)
from handlers.batch_handlers import (
    link_command,
    batch_command,
)
from handlers.broadcast_handlers import (
    broadcast_command,
    group_broadcast_command,
)
from handlers.moderation_handlers import (
    ban_command,
    unban_command,
    tban_command,
    mute_command,
    unmute_command,
    tmute_command,
    pin_command,
    unpin_command,
    purge_command,
    id_command,
    info_command,
)
from handlers.extended_commands import (
    ping_command,
    alive_command,
    settings_command,
    settings_callback,
    details_command,
    reset_group_command,
    resetallgroup_command,
    reload_command,
    set_caption_command,
    set_fsub_command,
    remove_fsub_command,
    set_log_channel_command,
    pm_search_command,
    movie_update_command,
    del_msg_command,
    top_search_command,
    send_user_msg_command,
    deletefiles_command,
    deletefiles_callback,
    request_command,
    request_status_callback,
    admin_cmd_command,
    group_cmd_command,
    logs_command,
    connect_command,
    disconnect_command,
    connections_command,
    connection_callback_handler,
    delete_file_command,
    deleteall_files_command,
    imdb_command,
    users_command,
    index_command,
    leave_chat_command,
    disable_chat_command,
    enable_chat_command,
    ban_user_command,
    unban_user_command,
    channel_command,
    clear_junk_command,
    clear_junk_group_command,
)
from handlers.menu_handlers import menu_callback_handler
from handlers.inline_handlers import inline_query_handler
from handlers.extra_features import (
    json_command,
    font_command,
    share_command,
    password_command,
    written_command,
    restart_command,
    set_template_command,
    get_template_command,
    dkick_command,
    instatus_command,
    inkick_command,
)
from handlers.payment_handlers import (
    plan_command,
    myplan_command,
    buy_star_callback,
    pre_checkout_handler,
    successful_payment_handler,
    payment_navigation_callbacks,
    refer_command,
    add_redeem_command,
    redeem_command,
    trial_reset_command,
    paywall_command,
    add_premium_command,
    remove_premium_command,
    get_premium_command,
    premium_users_command,
)

# Configure structured logging
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    format="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / "bot.log", encoding="utf-8", mode="a"),
    ],
)
# Silence noisy polling and scheduler logs in terminal
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger("telegram_bot")


async def periodic_expiry_sweeper(context) -> None:
    """
    Periodic background job that cleans up expired self-destruct messages.
    Ensures that even if the bot is stopped/restarted, overdue messages are swept.
    """
    db: Database = context.bot_data["db"]
    due_items = await db.get_due_deletions()
    if not due_items:
        return

    logger.info("Sweeper found %d overdue self-destruct message(s) to remove", len(due_items))
    for item in due_items:
        try:
            await execute_auto_deletion(
                bot=context.bot,
                db=db,
                chat_id=item["chat_id"],
                file_message_id=item["file_message_id"],
                notice_message_id=item.get("notice_message_id"),
                record_id=item["id"],
            )
        except Exception as e:
            logger.error("Error sweeping deletion record %s: %s", item.get("id"), e)

    await db.cleanup_finished_deletions()


async def periodic_subscription_sweeper(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic background job that notifies users whose VIP subscriptions expired.
    """
    db: Database = context.bot_data["db"]
    due_expired = await db.get_due_expired_subscriptions()
    for item in due_expired:
        user_id = item["user_id"]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "⚠️ <b>Your VIP Subscription Has Expired</b>\n\n"
                    "Thank you for being a subscriber! Your VIP access has ended.\n"
                    "To renew and continue enjoying unlimited file downloads and searches, tap /plan."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.debug("Could not send expiry notification to user %s: %s", user_id, e)
        await db.mark_subscription_expired_notified(user_id)


async def _start_heroku_health_server(port: int) -> None:
    """Lightweight HTTP server to satisfy Heroku's $PORT binding requirement for web dynos."""
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await reader.read(4096)
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: 17\r\n"
                b"Connection: close\r\n\r\n"
                b"Bot is running OK"
            )
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    try:
        server = await asyncio.start_server(handle_client, "0.0.0.0", port)
        logger.info("Started Heroku web health server on port %d", port)
        async with server:
            await server.serve_forever()
    except Exception as e:
        logger.warning("Could not start Heroku web health server on port %d: %s", port, e)


async def post_init(application: Application) -> None:
    """Post-initialization hook: initialize DB and setup background jobs."""
    db: Database = application.bot_data["db"]
    await db.init()

    # Log initial status
    bot_info = await application.bot.get_me()
    curr_mode = await db.get_delivery_mode()
    timer = await db.get_auto_delete_seconds()
    paywall_status = await db.is_paywall_enabled()

    logger.info("=" * 60)
    logger.info("🤖 Bot Started: @%s (ID: %s)", bot_info.username, bot_info.id)
    logger.info("👑 Developer ID: %s", DEVELOPER_ID if DEVELOPER_ID else "NOT SET (Please set in .env)")
    logger.info("📦 Delivery Mode: %s", curr_mode.value.upper())
    logger.info("⏱️ Auto-Destruct Timer: %ds", timer)
    logger.info("💳 Paywall Access: %s", "ON (Paid Members Only)" if paywall_status else "OFF (Free Public Access)")
    logger.info("🗄️ Database: %s", DATABASE_PATH)
    logger.info("=" * 60)

    # Schedule background jobs in JobQueue
    if application.job_queue:
        application.job_queue.run_repeating(
            periodic_expiry_sweeper,
            interval=30,
            first=5,
            name="periodic_expiry_sweeper",
        )
        application.job_queue.run_repeating(
            periodic_subscription_sweeper,
            interval=60,
            first=15,
            name="periodic_subscription_sweeper",
        )
        logger.info("Started periodic self-destruct sweeper & subscription expiry tasks.")

    # Start Heroku Web Dyno health check server if PORT is provided
    port_str = os.getenv("PORT")
    if port_str and port_str.isdigit():
        port = int(port_str)
        asyncio.create_task(_start_heroku_health_server(port))

    # Send #Bot_Started work log to LOG_CHANNEL
    await send_work_log(
        application.bot,
        db,
        f"🤖 <b>#Bot_Started</b>\n\n"
        f"• <b>Bot:</b> @{bot_info.username} (<code>{bot_info.id}</code>)\n"
        f"• <b>Delivery Mode:</b> <code>{curr_mode.value.upper()} ({timer}s)</code>\n"
        f"• <b>Paywall:</b> <code>{'ON' if paywall_status else 'OFF'}</code>",
    )


def build_application(token: str, db: Database) -> Application:
    """Build and configure the Telegram Bot Application."""
    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    # Attach shared database instance
    app.bot_data["db"] = db

    # Register User Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler(["search", "find"], search_command))
    app.add_handler(CommandHandler(["files", "list"], list_files_command))
    app.add_handler(CommandHandler(["plan", "plans", "buy", "vip"], plan_command))
    app.add_handler(CommandHandler(["myplan", "subscription"], myplan_command))
    app.add_handler(CommandHandler("refer", refer_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler(["request", "req"], request_command))
    app.add_handler(CommandHandler(["top_search", "trendlist", "trending"], top_search_command))

    # Register Automated Payments & Paywall Controls
    app.add_handler(CommandHandler("paywall", paywall_command))
    app.add_handler(CommandHandler("add_premium", add_premium_command))
    app.add_handler(CommandHandler("remove_premium", remove_premium_command))
    app.add_handler(CommandHandler("get_premium", get_premium_command))
    app.add_handler(CommandHandler("premium_users", premium_users_command))
    app.add_handler(CommandHandler("add_redeem", add_redeem_command))
    app.add_handler(CommandHandler("trial_reset", trial_reset_command))

    # Register Developer Controls & Admin Commands
    app.add_handler(CommandHandler("set_mode", set_mode_command))
    app.add_handler(CommandHandler(["get_mode", "mode"], get_mode_command))
    app.add_handler(CommandHandler("set_timer", set_timer_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler(["backup", "backup_db"], backup_command))
    app.add_handler(CommandHandler("index_range", index_range_command))
    app.add_handler(CommandHandler(["fast_index", "fastindex", "fast"], fast_index_command))
    app.add_handler(CommandHandler(["stop_index", "stopindex", "cancel_index"], stop_index_command))

    # Register Welcome & Group Management
    app.add_handler(CommandHandler("welcome", welcome_command))

    # Register Manual & Global Filters
    app.add_handler(CommandHandler("filter", filter_command))
    app.add_handler(CommandHandler("filters", filters_command))
    app.add_handler(CommandHandler("del", del_filter_command))
    app.add_handler(CommandHandler("delall", delall_filters_command))
    app.add_handler(CommandHandler("gfilter", gfilter_command))
    app.add_handler(CommandHandler("gfilters", gfilters_command))
    app.add_handler(CommandHandler("delg", delg_filter_command))
    app.add_handler(CommandHandler("delallg", delallg_filters_command))

    # Register File Store & Batch Generator
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("batch", batch_command))

    # Register Broadcasts & Direct Send
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("group_broadcast", group_broadcast_command))
    app.add_handler(CommandHandler("send", send_user_msg_command))

    # Register Group Moderation & Utilities
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("tban", tban_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("tmute", tmute_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("unpin", unpin_command))
    app.add_handler(CommandHandler("purge", purge_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("info", info_command))

    # Register Extended Commands & Group/Bot Customization
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("alive", alive_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("details", details_command))
    app.add_handler(CommandHandler("reset_group", reset_group_command))
    app.add_handler(CommandHandler("resetallgroup", resetallgroup_command))
    app.add_handler(CommandHandler("reload", reload_command))
    app.add_handler(CommandHandler("set_caption", set_caption_command))
    app.add_handler(CommandHandler("set_fsub", set_fsub_command))
    app.add_handler(CommandHandler("remove_fsub", remove_fsub_command))
    app.add_handler(CommandHandler("set_log_channel", set_log_channel_command))
    app.add_handler(CommandHandler("pm_search", pm_search_command))
    app.add_handler(CommandHandler("movie_update", movie_update_command))
    app.add_handler(CommandHandler("del_msg", del_msg_command))
    app.add_handler(CommandHandler("admin_cmd", admin_cmd_command))
    app.add_handler(CommandHandler("group_cmd", group_cmd_command))
    app.add_handler(CommandHandler(["logs", "log"], logs_command))
    app.add_handler(CommandHandler("connect", connect_command))
    app.add_handler(CommandHandler("disconnect", disconnect_command))
    app.add_handler(CommandHandler("connections", connections_command))
    app.add_handler(CommandHandler("delete", delete_file_command))
    app.add_handler(CommandHandler("deletefiles", deletefiles_command))
    app.add_handler(CommandHandler("deleteall", deleteall_files_command))
    app.add_handler(CommandHandler(["imdb", "imbd"], imdb_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("index", index_command))
    app.add_handler(CommandHandler("leave", leave_chat_command))
    app.add_handler(CommandHandler("disable", disable_chat_command))
    app.add_handler(CommandHandler("enable", enable_chat_command))
    app.add_handler(CommandHandler("ban_user", ban_user_command))
    app.add_handler(CommandHandler("unban_user", unban_user_command))
    app.add_handler(CommandHandler(["channel", "channels"], channel_command))
    app.add_handler(CommandHandler("clear_junk", clear_junk_command))
    app.add_handler(CommandHandler(["clear_junk_group", "junk_group"], clear_junk_group_command))

    # Register Extra Commands from MR.Guardian_bot
    app.add_handler(CommandHandler("json", json_command))
    app.add_handler(CommandHandler("font", font_command))
    app.add_handler(CommandHandler(["share", "share_text"], share_command))
    app.add_handler(CommandHandler(["password", "genpass", "genpw"], password_command))
    app.add_handler(CommandHandler("written", written_command))
    app.add_handler(CommandHandler("restart", restart_command))
    app.add_handler(CommandHandler("set_template", set_template_command))
    app.add_handler(CommandHandler("get_template", get_template_command))
    app.add_handler(CommandHandler("dkick", dkick_command))
    app.add_handler(CommandHandler("instatus", instatus_command))
    app.add_handler(CommandHandler("inkick", inkick_command))

    # Register Inline Buttons & Navigation Callbacks
    app.add_handler(
        CallbackQueryHandler(
            menu_callback_handler,
            pattern=r"^menu_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            connection_callback_handler,
            pattern=r"^conn_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filter_spelling_click_callback,
            pattern=r"^fsp_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            settings_callback,
            pattern=r"^st_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            mode_callback_query,
            pattern=r"^(set_mode_view_only|set_mode_downloadable|admin_refresh_status)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            file_callback_query,
            pattern=r"^getfile_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filter_pagination_callback,
            pattern=r"^fp_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filter_extra_callbacks,
            pattern=r"^(fqm|fqs|flm|fls|fsm|fss|fall)_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            filter_file_click_callback,
            pattern=r"^fl_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            deletefiles_callback,
            pattern=r"^killfiles_yes_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            request_status_callback,
            pattern=r"^reqopt_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            stop_indexing_callback,
            pattern=r"^stop_indexing$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            fast_index_callback,
            pattern=r"^fastidx_",
        )
    )

    # Register Telegram Stars Payment & VIP Callbacks
    app.add_handler(
        CallbackQueryHandler(
            buy_star_callback,
            pattern=r"^buy_star_\d+$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            payment_navigation_callbacks,
            pattern=r"^(show_plans|show_myplan|close_plan|give_trial|refer_menu|ref_point|redeem_info|upi_info)$",
        )
    )

    # Register Telegram Stars Automated Payment Handlers
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Register Inline Search Handler (@botusername <query>)
    app.add_handler(InlineQueryHandler(inline_query_handler))

    # Register Media Handlers
    media_filter = (
        filters.Document.ALL
        | filters.VIDEO
        | filters.AUDIO
        | filters.PHOTO
        | filters.VOICE
        | filters.ANIMATION
        | filters.VIDEO_NOTE
    )
    # Channel posts listener (auto-indexes files posted in storage channel silently)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & media_filter, handle_channel_post))
    # User / Admin direct uploads in DM or group
    app.add_handler(MessageHandler(~filters.ChatType.CHANNEL & media_filter, handle_media_upload))

    # Welcome greetings listener
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))

    # Auto-Filter & Custom Filters listener across groups & private DMs
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_filter_or_search))

    # Global error handler so unhandled errors are logged cleanly and reported
    app.add_error_handler(error_handler)

    return app


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled errors caused by updates and notify the user if possible."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    db = context.bot_data.get("db") if context and context.bot_data else None
    if context and context.bot and context.error:
        import html as _html
        await send_work_log(
            context.bot,
            db,
            f"⚠️ <b>#Error_Log</b>\n\n<code>{_html.escape(str(context.error)[:500])}</code>",
        )
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected error occurred while processing your command. Please try again."
            )
        except Exception:
            pass


def main() -> None:
    """Main execution function."""
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("\n" + "=" * 65)
        print("❌ ERROR: BOT_TOKEN is missing or not configured!")
        print("=" * 65)
        print("Please configure your .env file with your Telegram Bot Token:")
        print("1. Open or create the .env file in this directory.")
        print("2. Set BOT_TOKEN=<your_token_from_BotFather>")
        print("3. Set DEVELOPER_ID=<your_numeric_telegram_user_id>")
        print("4. Restart the bot.\n")
        sys.exit(1)

    if DEVELOPER_ID == 0:
        logger.warning(
            "⚠️ WARNING: DEVELOPER_ID is not set in .env! "
            "Developer commands (/set_mode, /set_timer) will be locked until configured."
        )

    # Auto-download initial database if DATABASE_DOWNLOAD_URL is configured and local database is missing
    db_url = os.getenv("DATABASE_DOWNLOAD_URL", "").strip()
    if db_url and (not os.path.exists(DATABASE_PATH) or os.path.getsize(DATABASE_PATH) == 0):
        logger.info("DATABASE_DOWNLOAD_URL detected. Restoring initial database...")
        tmp_download = DATABASE_PATH.with_suffix(".download_tmp")
        try:
            import shutil
            import zipfile
            req = urllib.request.Request(db_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_download, "wb") as out_f:
                shutil.copyfileobj(resp, out_f, length=65536)
            if zipfile.is_zipfile(tmp_download):
                with zipfile.ZipFile(tmp_download, "r") as zf:
                    members = [m for m in zf.namelist() if m.endswith(".sqlite3") or m.endswith(".db")]
                    target_member = members[0] if members else zf.namelist()[0]
                    with zf.open(target_member) as src, open(DATABASE_PATH, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=65536)
                tmp_download.unlink(missing_ok=True)
            else:
                os.replace(tmp_download, DATABASE_PATH)
            logger.info("Successfully restored database from download URL (%d bytes).", os.path.getsize(DATABASE_PATH))
        except Exception as e:
            logger.error("Failed to download database from %s: %s", db_url, e)
            tmp_download.unlink(missing_ok=True)

    db = Database(DATABASE_PATH)
    application = build_application(BOT_TOKEN, db)

    logger.info("Starting bot polling loop...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
