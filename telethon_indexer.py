"""
Full-Channel MTProto History Indexer (Telethon).
Reads the entire history of your storage channel at maximum speed (1,000+ files in seconds).

Prerequisites:
    1. pip install telethon
    2. Get API_ID and API_HASH from https://my.telegram.org (under 'API development tools')
    3. Run: .venv\\Scripts\\python.exe telethon_indexer.py
"""

from __future__ import annotations

import os
import asyncio
import secrets
from pathlib import Path
import aiosqlite
from dotenv import load_dotenv

load_dotenv()

# Configuration
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "0"))
DATABASE_PATH = Path(__file__).resolve().parent / os.getenv("DATABASE_PATH", "bot_database.sqlite3")
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
TWO_FA_PASSWORD = os.getenv("TELEGRAM_2FA_PASSWORD")

from cleaner import smart_clean_filename


async def main():
    try:
        from telethon import TelegramClient, errors
    except ImportError:
        print("\n❌ Telethon is not installed.")
        print("Run this command first to install it:")
        print("    pip install telethon\n")
        return

    if not API_ID or not API_HASH:
        print("\n" + "=" * 65)
        print("🔑 Telegram API Credentials Required for Telethon")
        print("=" * 65)
        print("1. Go to https://my.telegram.org and log in.")
        print("2. Click 'API development tools'.")
        print("3. Add TELEGRAM_API_ID and TELEGRAM_API_HASH to your .env file:")
        print("       TELEGRAM_API_ID=12345678")
        print("       TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890")
        print("4. Run this script again.\n")
        return

    if not STORAGE_CHANNEL_ID:
        print("❌ STORAGE_CHANNEL_ID is not configured in .env!")
        return

    if TWO_FA_PASSWORD:
        print("🔒 2FA Password detected in .env, using automatic login.")
    else:
        print("ℹ️ TELEGRAM_2FA_PASSWORD is not set in .env (will prompt manually).")

    client = TelegramClient("indexer_session", int(API_ID), API_HASH)
    try:
        if TWO_FA_PASSWORD:
            await client.start(password=TWO_FA_PASSWORD)
        else:
            await client.start()
    except errors.PasswordHashInvalidError:
        print("\n" + "=" * 65)
        print("❌ INCORRECT TWO-STEP VERIFICATION PASSWORD")
        print("=" * 65)
        print("The 2FA password you entered does not match your Telegram account.")
        print("Tip: You can check or reset your 2FA password in the Telegram app:")
        print("     Settings ➔ Privacy and Security ➔ Two-Step Verification.")
        print("=" * 65 + "\n")
        return

    print(f"\n🚀 Connected to Telegram MTProto API!")
    print(f"📡 Scanning entire channel: {STORAGE_CHANNEL_ID}...")

    try:
        channel = await client.get_entity(STORAGE_CHANNEL_ID)
    except Exception:
        channel_id_pos = int(str(STORAGE_CHANNEL_ID).removeprefix("-100").removeprefix("-"))
        try:
            channel = await client.get_entity(channel_id_pos)
        except Exception:
            channel = None
            async for dialog in client.iter_dialogs():
                if dialog.id in (STORAGE_CHANNEL_ID, -channel_id_pos):
                    channel = dialog.entity
                    break
            if not channel:
                raise RuntimeError(f"Could not locate channel {STORAGE_CHANNEL_ID}. Make sure your account is an admin or member of this channel.")

    async with aiosqlite.connect(str(DATABASE_PATH)) as db:
        # Get existing message IDs
        async with db.execute("SELECT source_message_id FROM files WHERE source_chat_id = ?;", (STORAGE_CHANNEL_ID,)) as cur:
            rows = await cur.fetchall()
            existing_ids = {r[0] for r in rows if r[0] is not None}

        print(f"🔁 Found {len(existing_ids)} files already in database.\n")

        new_count = 0
        total_messages = 0

        async for message in client.iter_messages(channel, reverse=True):
            total_messages += 1
            if message.id in existing_ids:
                continue

            if message.file:
                # Extract file details
                raw_name = message.file.name or message.text or ""
                clean_name = smart_clean_filename(raw_name)
                file_size = message.file.size or 0
                file_type = "video" if message.video else ("audio" if message.audio else "document")
                file_code = secrets.token_urlsafe(10)[:10]

                # Insert into bot database
                await db.execute(
                    """
                    INSERT INTO files (
                        file_code, file_id, file_unique_id, file_type, file_name,
                        file_size, caption, source_chat_id, source_message_id, uploaded_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        file_code,
                        f"mtproto_{message.id}",
                        f"unique_{message.id}",
                        file_type,
                        clean_name,
                        file_size,
                        message.text or "",
                        STORAGE_CHANNEL_ID,
                        message.id,
                        0,
                    ),
                )
                new_count += 1
                if new_count % 50 == 0:
                    await db.commit()
                    print(f"  [+] Indexed {new_count} new files (Total scanned: {total_messages})...")

        await db.commit()

    print("\n" + "=" * 65)
    print("🎉 Full Channel Index Complete!")
    print(f"✨ Newly Added Files: {new_count}")
    print(f"📬 Total Messages Checked: {total_messages}")
    print("=" * 65 + "\n")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
