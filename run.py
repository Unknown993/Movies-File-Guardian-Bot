"""
Main entry point for Telegram Content Protection & File Delivery Bot.
Orchestrates handlers, persistent SQLite database, and auto-destruct JobQueue.
"""

from __future__ import annotations

import sys
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    DEVELOPER_ID,
    DATABASE_PATH,
    DeliveryMode,
)
from database import Database
from delivery import execute_auto_deletion
from handlers.admin_handlers import (
    set_mode_command,
    get_mode_command,
    set_timer_command,
    stats_command,
    mode_callback_query,
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
)
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


async def post_init(application: Application) -> None:
    """Post-initialization hook: initialize DB and setup background jobs."""
    db: Database = application.bot_data["db"]
    await db.init()

    # Log initial status
    bot_info = await application.bot.get_me()
    curr_mode = await db.get_delivery_mode()
    timer = await db.get_auto_delete_seconds()

    logger.info("=" * 60)
    logger.info("🤖 Bot Started: @%s (ID: %s)", bot_info.username, bot_info.id)
    logger.info("👑 Developer ID: %s", DEVELOPER_ID if DEVELOPER_ID else "NOT SET (Please set in .env)")
    logger.info("📦 Delivery Mode: %s", curr_mode.value.upper())
    logger.info("⏱️ Auto-Destruct Timer: %ds", timer)
    logger.info("🗄️ Database: %s", DATABASE_PATH)
    logger.info("=" * 60)

    # Schedule periodic deletion sweeper in JobQueue (runs every 30s)
    if application.job_queue:
        application.job_queue.run_repeating(
            periodic_expiry_sweeper,
            interval=30,
            first=5,
            name="periodic_expiry_sweeper",
        )
        logger.info("Started periodic self-destruct sweeper task (interval: 30s).")


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

    # Register Developer Controls & Admin Commands
    app.add_handler(CommandHandler("set_mode", set_mode_command))
    app.add_handler(CommandHandler(["get_mode", "mode"], get_mode_command))
    app.add_handler(CommandHandler("set_timer", set_timer_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("index_range", index_range_command))

    # Register Inline Buttons (for mode switching and file retrieval)
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
    # Channel posts listener (auto-indexes files posted in storage channel)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & media_filter, handle_channel_post))
    # User / Admin direct uploads in DM or group
    app.add_handler(MessageHandler(~filters.ChatType.CHANNEL & media_filter, handle_media_upload))

    # User plain text search (e.g. typing a file name or keyword in DM)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_search))

    return app


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

    db = Database(DATABASE_PATH)
    application = build_application(BOT_TOKEN, db)

    logger.info("Starting bot polling loop...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
