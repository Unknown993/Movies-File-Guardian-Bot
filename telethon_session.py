import os
import sys
import asyncio

# Fix Windows unicode output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

# Try loading .env
for p in [".env", r"E:\tele_bot\.env", r"E:\Forwarding_bot\.env"]:
    if os.path.exists(p):
        load_dotenv(p)

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH") or ""

async def main():
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("❌ Telethon is not installed. Run: pip install telethon")
        return

    print("=" * 65)
    print("🔑 Telethon String Session Generator")
    print(f"API_ID:   {API_ID}")
    print("=" * 65)

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()

    session_str = client.session.save()
    me = await client.get_me()

    print("\n" + "=" * 65)
    print(f"✅ Successfully logged in as: {me.first_name} (ID: {me.id})")
    print("=" * 65)
    print("\n🔑 YOUR TELETHON STRING SESSION:\n")
    print("-" * 65)
    print(session_str)
    print("-" * 65)

    try:
        await client.send_message("me", f"**🔑 Your Telethon String Session:**\n\n`{session_str}`")
        print("\n📬 A copy has been sent to your Telegram 'Saved Messages'!")
    except Exception:
        pass

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
