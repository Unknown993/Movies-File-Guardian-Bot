"""
High-Speed Channel Indexer CLI.
Scans and indexes files directly from the command line without opening Telegram chat.

Usage:
    .venv\\Scripts\\python.exe fast_index.py <start_id> <end_id>
Example:
    .venv\\Scripts\\python.exe fast_index.py 1 500
"""

from __future__ import annotations

import sys
import asyncio
import logging
from telegram import Bot
import telegram.error

from config import BOT_TOKEN, STORAGE_CHANNEL_ID, DEVELOPER_ID, DATABASE_PATH
from database import Database
from cleaner import smart_clean_filename
from handlers.file_handlers import extract_media_details

logging.basicConfig(level=logging.WARNING)


async def main():
    if len(sys.argv) < 3:
        print("\n" + "=" * 60)
        print("⚡ FileGuardian Fast Channel Indexer CLI")
        print("=" * 60)
        print("Usage:   fast_index.py <start_id> <end_id>")
        print("Example: fast_index.py 1 500\n")
        return

    try:
        start_id = int(sys.argv[1])
        end_id = int(sys.argv[2])
    except ValueError:
        print("❌ Error: start_id and end_id must be integers.")
        return

    if start_id <= 0 or end_id < start_id:
        print("❌ Error: Invalid range.")
        return

    if not STORAGE_CHANNEL_ID:
        print("❌ Error: STORAGE_CHANNEL_ID is not configured in .env!")
        return

    if not DEVELOPER_ID:
        print("❌ Error: DEVELOPER_ID is not configured in .env!")
        return

    print("\n" + "=" * 65)
    print(f"🚀 Starting High-Speed Indexer for Channel {STORAGE_CHANNEL_ID}")
    print(f"🎯 Target Range: #{start_id} to #{end_id} ({end_id - start_id + 1} messages)")
    print("=" * 65)

    db = Database(DATABASE_PATH)
    await db.init()

    existing_ids = await db.get_existing_message_ids_in_range(STORAGE_CHANNEL_ID, start_id, end_id)
    already_count = len(existing_ids)
    ids_to_scan = [m for m in range(start_id, end_id + 1) if m not in existing_ids]

    print(f"🔁 Already in Database: {already_count} message(s)")
    print(f"🔍 Messages to scan:   {len(ids_to_scan)} message(s)\n")

    if not ids_to_scan:
        print("✅ All messages in this range are already indexed! Done.")
        return

    bot = Bot(token=BOT_TOKEN)
    new_indexed = 0
    semaphore = asyncio.Semaphore(8)

    async def scan_one(msg_id: int) -> bool:
        nonlocal new_indexed
        async with semaphore:
            fwd = None
            try:
                fwd = await bot.forward_message(
                    chat_id=DEVELOPER_ID,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=msg_id,
                )
            except telegram.error.RetryAfter as r:
                await asyncio.sleep(r.retry_after + 1)
                try:
                    fwd = await bot.forward_message(
                        chat_id=DEVELOPER_ID,
                        from_chat_id=STORAGE_CHANNEL_ID,
                        message_id=msg_id,
                    )
                except Exception:
                    return False
            except telegram.error.TelegramError:
                return False

            if fwd:
                try:
                    media_info = extract_media_details(fwd)
                    if media_info:
                        file_id, file_unique_id, file_type, file_name, file_size = media_info
                        caption = fwd.caption or ""
                        clean_name = smart_clean_filename(file_name or caption)
                        await db.register_file(
                            file_id=file_id,
                            file_unique_id=file_unique_id,
                            file_type=file_type,
                            file_name=clean_name,
                            file_size=file_size,
                            caption=caption,
                            source_chat_id=STORAGE_CHANNEL_ID,
                            source_message_id=msg_id,
                            uploaded_by=DEVELOPER_ID,
                        )
                        new_indexed += 1
                        print(f"  [+] #{msg_id}: {clean_name}")
                        return True
                finally:
                    try:
                        await fwd.delete()
                    except Exception:
                        pass
            return False

    chunk_size = 50
    for i in range(0, len(ids_to_scan), chunk_size):
        chunk = ids_to_scan[i : i + chunk_size]
        await asyncio.gather(*(scan_one(mid) for mid in chunk))
        processed = min(i + chunk_size, len(ids_to_scan))
        pct = (processed / len(ids_to_scan)) * 100
        print(f"--- Progress: {processed}/{len(ids_to_scan)} ({pct:.0f}%) | Indexed: {new_indexed} new files ---")
        await asyncio.sleep(0.3)

    print("\n" + "=" * 65)
    print("✅ Indexing Complete!")
    print(f"✨ New Files Added:     {new_indexed}")
    print(f"🔁 Previously Indexed:   {already_count}")
    print(f"⏭️ Skipped (Non-media):  {len(ids_to_scan) - new_indexed}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
