"""
Full-Channel MTProto History Indexer (Telethon).
High-speed indexing of Telegram storage channels into SQLite.

Usage:
    .venv\\Scripts\\python.exe telethon_indexer.py
    .venv\\Scripts\\python.exe telethon_indexer.py --resume
    .venv\\Scripts\\python.exe telethon_indexer.py --from 372401
"""

from __future__ import annotations

import os
import sys
import time
import asyncio
import secrets
import argparse
from pathlib import Path
import aiosqlite
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Configuration
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "0"))
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "bot_database.sqlite3")
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
TWO_FA_PASSWORD = os.getenv("TELEGRAM_2FA_PASSWORD")

from cleaner import smart_clean_filename


def detect_resume_point(existing_ids: set[int]) -> tuple[int, int, int]:
    """
    Analyzes indexed message IDs to find the resume point or largest unindexed gap.
    Returns: (resume_from_id, max_existing_id, gap_size)
    """
    if not existing_ids:
        return 0, 0, 0

    sorted_ids = sorted(existing_ids)
    max_id = sorted_ids[-1]

    # Look for the largest gap in the sequence
    max_gap_start = 0
    max_gap_size = 0
    for i in range(len(sorted_ids) - 1):
        diff = sorted_ids[i + 1] - sorted_ids[i]
        if diff > max_gap_size:
            max_gap_size = diff
            max_gap_start = sorted_ids[i]

    # If there is a massive gap (> 1000 messages), that's where indexing stopped
    if max_gap_size > 1000:
        return max_gap_start, max_id, max_gap_size
    else:
        return max_id, max_id, 0


async def main():
    try:
        from telethon import TelegramClient, errors
    except ImportError:
        print("\n❌ Telethon is not installed.")
        print("Run this command first to install it:")
        print("    .venv\\Scripts\\python.exe -m pip install telethon\n")
        return

    if not API_ID or not API_HASH:
        print("\n" + "=" * 65)
        print("🔑 Telegram API Credentials Required for Telethon")
        print("=" * 65)
        print("1. Go to https://my.telegram.org and log in.")
        print("2. Click 'API development tools'.")
        print("3. Add TELEGRAM_API_ID and TELEGRAM_API_HASH to your .env file.")
        print("=" * 65 + "\n")
        return

    if not STORAGE_CHANNEL_ID:
        print("❌ STORAGE_CHANNEL_ID is not configured in .env!")
        return

    session_str = os.getenv("TELEGRAM_SESSION_STRING", "").strip()
    if session_str:
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(session_str), int(API_ID), API_HASH)
    else:
        client = TelegramClient(str(BASE_DIR / "indexer_session"), int(API_ID), API_HASH)
    try:
        if TWO_FA_PASSWORD:
            await client.start(password=TWO_FA_PASSWORD)
        else:
            await client.start()
    except errors.PasswordHashInvalidError:
        print("\n❌ Incorrect 2FA Password. Check TELEGRAM_2FA_PASSWORD in .env.\n")
        return

    print(f"\n🚀 Connected to Telegram MTProto API!")
    print(f"📡 Resolving storage channel ({STORAGE_CHANNEL_ID})...", flush=True)

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
                raise RuntimeError(f"Could not locate channel {STORAGE_CHANNEL_ID}. Make sure account is an admin or member.")

    async with aiosqlite.connect(str(DATABASE_PATH)) as db:
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA synchronous = NORMAL;")

        # Fetch existing indexed message IDs & duplicate signatures
        async with db.execute("SELECT source_message_id FROM files WHERE source_chat_id = ?;", (STORAGE_CHANNEL_ID,)) as cur:
            rows = await cur.fetchall()
            existing_ids = {r[0] for r in rows if r[0] is not None}

        existing_signatures: set[tuple[str, int]] = set()
        existing_unique_ids: set[str] = set()
        async with db.execute("SELECT LOWER(file_name), file_size, file_unique_id FROM files;") as cur:
            sig_rows = await cur.fetchall()
            for fn, fsz, fuid in sig_rows:
                if fn and fn != "media file" and fsz and fsz > 0:
                    existing_signatures.add((fn, int(fsz)))
                if fuid and not str(fuid).startswith("unique_"):
                    existing_unique_ids.add(str(fuid))

        # Query channel's latest message
        latest_channel_msg_id = 0
        async for m in client.iter_messages(channel, limit=1):
            latest_channel_msg_id = m.id
            break

        resume_id, max_db_id, gap_size = detect_resume_point(existing_ids)

        print("\n" + "=" * 65)
        print("📊 Channel & Database Analysis:")
        print(f"   • Total Files in DB:       {len(existing_ids):,} files")
        print(f"   • Latest ID in Channel:    #{latest_channel_msg_id:,}")
        if gap_size > 1000:
            remaining = latest_channel_msg_id - resume_id
            print(f"   • Indexed range:           #2 to #{resume_id:,}")
            print(f"   ⚠️  UNINDEXED GAP DETECTED:  #{resume_id + 1:,} to #{latest_channel_msg_id:,}")
            print(f"   ⚡ Remaining to index:     ~{remaining:,} messages")
        else:
            remaining = max(0, latest_channel_msg_id - max_db_id)
            print(f"   • Database up to date to:  #{max_db_id:,}")
            if remaining == 0:
                print("   ✅ Database is 100% up to date with the channel!")
            else:
                print(f"   ⚡ New messages since last index: ~{remaining:,}")
        print("=" * 65)

        # Handle CLI argument or prompt
        selected_mode = "1"
        custom_from_id = None

        if len(sys.argv) > 1:
            arg = sys.argv[1].lower().strip("-")
            if arg in ["resume", "r", "1"]:
                selected_mode = "1"
            elif arg in ["recent", "2"]:
                selected_mode = "2"
            elif arg in ["full", "f", "3"]:
                selected_mode = "3"
            elif arg == "from" and len(sys.argv) > 2 and sys.argv[2].isdigit():
                selected_mode = "4"
                custom_from_id = int(sys.argv[2])
        else:
            print("\nSelect indexing mode:")
            if gap_size > 1000:
                print(f"  [1] ⚡ Resume Indexing Gap (From #{resume_id:,} to #{latest_channel_msg_id:,}) [Press Enter]")
            else:
                print(f"  [1] ⚡ Quick Sync (Scan only messages > #{max_db_id:,}) [Press Enter]")
            print(f"  [2] 🔄 Scan Recent Messages (Last 2,000 backwards)")
            print(f"  [3] 📦 Full Channel Rescan (From message #1 to latest)")
            print(f"  [4] 🎯 Custom Message ID (Start from specific ID)")

            try:
                user_choice = input("\nEnter choice [1/2/3/4] (default is 1): ").strip()
                if user_choice in ["1", "2", "3", "4"]:
                    selected_mode = user_choice
                if selected_mode == "4":
                    cid = input("Enter start message ID: ").strip()
                    if cid.isdigit():
                        custom_from_id = int(cid)
                    else:
                        selected_mode = "1"
            except (EOFError, KeyboardInterrupt):
                selected_mode = "1"

        print()

        # Set up iterator based on selection
        if selected_mode == "1":
            start_point = resume_id
            print(f"⚡ Starting indexer from message #{start_point:,} forward...", flush=True)
            msg_iter = client.iter_messages(channel, min_id=start_point, reverse=True)
        elif selected_mode == "2":
            limit_val = 2000
            print(f"🔄 Scanning the last {limit_val:,} messages backwards...", flush=True)
            msg_iter = client.iter_messages(channel, limit=limit_val, reverse=False)
        elif selected_mode == "3":
            print("📦 Starting Full Channel Scan from message #1 forward...", flush=True)
            msg_iter = client.iter_messages(channel, reverse=True)
        elif selected_mode == "4" and custom_from_id is not None:
            print(f"🎯 Starting custom scan from message #{custom_from_id:,} forward...", flush=True)
            msg_iter = client.iter_messages(channel, min_id=custom_from_id, reverse=True)
        else:
            msg_iter = client.iter_messages(channel, min_id=resume_id, reverse=True)

        new_count = 0
        total_messages = 0
        skipped_count = 0
        start_time = time.time()
        last_log_time = time.time()

        print("-----------------------------------------------------------------", flush=True)

        try:
            async for message in msg_iter:
                total_messages += 1

                # If message is already indexed, skip
                if message.id in existing_ids:
                    skipped_count += 1
                    if total_messages % 200 == 0:
                        elapsed = time.time() - start_time
                        speed = new_count / elapsed if elapsed > 0 else 0
                        print(
                            f"\r  ⚡ [Msg #{message.id:,}] Scanned: {total_messages:,} | Skipped: {skipped_count:,} | New: {new_count:,} ({speed:.1f} files/s)",
                            end="",
                            flush=True,
                        )
                    continue

                if message.file:
                    raw_name = message.file.name or message.text or ""
                    clean_name = smart_clean_filename(raw_name)
                    file_size = message.file.size or 0
                    doc_obj = getattr(getattr(message, "media", None), "document", None)
                    doc_uid = f"tgdoc_{doc_obj.id}" if doc_obj and getattr(doc_obj, "id", None) else f"unique_{STORAGE_CHANNEL_ID}_{message.id}"
                    sig = (clean_name.lower(), file_size)

                    if (
                        doc_uid in existing_unique_ids
                        or (clean_name and clean_name != "Media File" and file_size > 0 and sig in existing_signatures)
                    ):
                        skipped_count += 1
                        existing_ids.add(message.id)
                        continue

                    file_type = "video" if message.video else ("audio" if message.audio else "document")
                    file_code = secrets.token_urlsafe(10)[:10]

                    await db.execute(
                        """
                        INSERT INTO files (
                            file_code, file_id, file_unique_id, file_type, file_name,
                            file_size, caption, source_chat_id, source_message_id, uploaded_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            file_code,
                            f"mtproto_{STORAGE_CHANNEL_ID}_{message.id}",
                            doc_uid,
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
                    existing_ids.add(message.id)
                    existing_unique_ids.add(doc_uid)
                    if clean_name and clean_name != "Media File" and file_size > 0:
                        existing_signatures.add(sig)

                    elapsed = time.time() - start_time
                    speed = new_count / elapsed if elapsed > 0 else 0

                    # Print log line every 25 files
                    if new_count % 25 == 0:
                        await db.commit()
                        display_name = clean_name[:50] + "..." if len(clean_name) > 50 else clean_name
                        print(
                            f"\r  [+] (#{message.id:,}) {display_name:<53} | Total: {new_count:,} ({speed:.1f} f/s)",
                            flush=True,
                        )
                    else:
                        print(
                            f"\r  ⚡ [Msg #{message.id:,}] Scanned: {total_messages:,} | New: {new_count:,} ({speed:.1f} files/s)",
                            end="",
                            flush=True,
                        )
                else:
                    if total_messages % 200 == 0:
                        elapsed = time.time() - start_time
                        speed = new_count / elapsed if elapsed > 0 else 0
                        print(
                            f"\r  ⚡ [Msg #{message.id:,}] Scanned: {total_messages:,} | Skipped: {skipped_count:,} | New: {new_count:,} ({speed:.1f} files/s)",
                            end="",
                            flush=True,
                        )

        except (errors.FloodWaitError, Exception) as err:
            if isinstance(err, errors.FloodWaitError):
                wait_sec = getattr(err, "seconds", 30)
                print(f"\n⚠️ Telegram rate limit (FloodWait). Pausing for {wait_sec} seconds before resuming...")
                await asyncio.sleep(wait_sec + 1)
            else:
                print(f"\n⚠️ Warning: {err}")
        finally:
            await db.commit()

    total_time = time.time() - start_time
    avg_speed = new_count / total_time if total_time > 0 else 0

    print("\n" + "=" * 65)
    print("🎉 Indexing Session Finished!")
    print(f"✨ Newly Added Files:       {new_count:,}")
    print(f"🔁 Existing Files Skipped:  {skipped_count:,}")
    print(f"📬 Total Messages Checked:  {total_messages:,}")
    print(f"⏱️ Time Taken:              {total_time:.1f}s ({avg_speed:.1f} files/s)")
    print("=" * 65 + "\n", flush=True)

    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Indexing stopped by user. All progress up to this point is safely saved.")
