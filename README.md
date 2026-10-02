# 🛡️ Telegram Content Protection & File Delivery Bot

A production-ready Telegram bot built with Python 3.12 and `python-telegram-bot` (v22+), implementing a configurable content protection and file delivery strategy.

---

## 🌟 Content Protection & File Delivery Strategy

The bot implements two distinct delivery modes with strict developer access control:

### 🔒 Option 1 (Default - View Only)
* **Telegram Content Protection:** Applies `protect_content=True` on all messages and files.
* **Anti-Leakage:** Prevents forwarding, copying, and saving media outside Telegram.
* **In-App Streaming:** Users can stream video/audio and read documents exclusively within Telegram's native player/viewer.
* **Persistent Access:** Media remains in the chat without self-destructing, protected by Telegram's DRM-like restriction.

### ⏱️ Option 2 (Download Allowed with Auto-Expiry & No Source Attribution)
* **Metadata Stripping:** Delivered via `copy_message(..., protect_content=False)`. Because Telegram's `copy_message` creates a clean copy instead of a forward, all source channel metadata, usernames, and forward attribution headers are stripped. Recipients cannot trace where the file originated.
* **Automatic Self-Destruct Timer:** The bot schedules automatic deletion of the file message after a configured time (default: **3 minutes / 180 seconds**). Both the file message and the warning notice are removed.
* **Dual-Layer Auto-Delete Engine:** 
  1. High-precision in-memory scheduling via `JobQueue` (APScheduler).
  2. Persistent SQLite queue with a 30-second background sweeper that cleans overdue messages even across bot restarts.
* **Chat Restriction:** Delivery in Mode 2 is strictly limited to **private DMs** and designated temporary download channels. If requested inside a public/group chat, the bot declines delivery and gives the user a direct private DM link.

### 👑 Developer Controls
* **Exclusive Access:** Only the developer (`DEVELOPER_ID`) can toggle delivery modes and modify timer intervals. Unauthorized users receive an access-denied alert.
* **Slash Command:** `/set_mode <view_only|downloadable>`
* **Interactive UI:** Developer can also use inline buttons to switch modes instantly.
* **Custom Timer:** `/set_timer <seconds>` (e.g. `/set_timer 180` for 3 minutes, `/set_timer 300` for 5 minutes).

---

## 🏗️ Project Architecture

```
e:\tele_bot\
├── .env.example              # Environment variables template
├── .env                      # Active configuration (tokens, IDs)
├── requirements.txt          # Python dependencies
├── run.py                    # Main bot runner & background sweepers
├── config.py                 # Configuration loader & permission checks
├── database.py               # Asynchronous SQLite storage & deletion queue
├── delivery.py               # Core delivery engine (Mode 1 & Mode 2 logic)
├── handlers/
│   ├── __init__.py
│   ├── admin_handlers.py     # /set_mode, /set_timer, /get_mode, /stats
│   ├── user_handlers.py      # /start, deep-link file delivery, /help
│   └── file_handlers.py      # Media upload, mirroring, and link generation
└── tests/
    ├── __init__.py
    ├── test_config.py        # Config & permission tests
    ├── test_database.py      # SQLite operations & persistence tests
    ├── test_delivery_logic.py# Mode 1, Mode 2, and auto-delete tests
    └── test_admin_handlers.py# Developer security & command tests
```

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.10+ (Python 3.12 recommended)
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Your Telegram User ID from [@userinfobot](https://t.me/userinfobot)

### 2. Virtual Environment & Dependencies
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install required packages
pip install -r requirements.txt
```

### 3. Configure `.env`
Copy `.env.example` to `.env` and fill in your values:

```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
DEVELOPER_ID=987654321
DEFAULT_DELIVERY_MODE=view_only
DEFAULT_AUTO_DELETE_SECONDS=180
DATABASE_PATH=bot_database.sqlite3
```

| Variable | Description |
| :--- | :--- |
| `BOT_TOKEN` | Token provided by @BotFather. |
| `DEVELOPER_ID` | Numeric Telegram ID of the developer authorized to toggle modes. |
| `ADMIN_IDS` | *(Optional)* Comma-separated list of additional admin IDs who can upload files. |
| `STORAGE_CHANNEL_ID` | *(Optional)* Dedicated Telegram channel (e.g., `-1001234567890`) where files are mirrored. |
| `ALLOWED_TEMP_CHANNELS` | *(Optional)* Comma-separated chat IDs allowed for Mode 2 downloads besides private DMs. |
| `DEFAULT_DELIVERY_MODE` | Initial delivery mode: `view_only` or `downloadable`. |
| `DEFAULT_AUTO_DELETE_SECONDS` | Mode 2 auto-deletion countdown in seconds (default `180` = 3 min). |

### 4. Run the Bot
```powershell
.\.venv\Scripts\python.exe run.py
```

---

## 🕹️ Command Reference

### Developer Commands (Exclusive to `DEVELOPER_ID`)
* `/set_mode <view_only|downloadable>` - Switch file delivery strategy:
  * `/set_mode view_only` activates Option 1 (`protect_content=True`).
  * `/set_mode downloadable` activates Option 2 (`protect_content=False` + auto-destruct timer).
  * Running `/set_mode` without arguments opens the interactive inline buttons.
* `/set_timer <seconds>` - Set the self-destruct timer for downloadable mode (e.g., `/set_timer 180` for 3 mins, `/set_timer 300` for 5 mins).

### Admin Commands (Admins & Developer)
* `/get_mode` or `/mode` - Display active delivery strategy, timer, and current settings.
* `/stats` - View database statistics (registered files, total access events, pending deletions).
* `/index_range <start_id> <end_id>` - Bulk scan and register a range of messages in your storage channel (e.g. `/index_range 1 100`).
* **Auto-Index Channel Posts:** Any new file or media message posted to your configured `STORAGE_CHANNEL_ID` is automatically registered and the developer is sent the share link in their DM.
* **Upload Media:** Send or forward any file (Document, Video, Audio, Photo, Voice, GIF) directly to the bot to generate a secure shareable deep-link (`t.me/<bot_username>?start=file_<code>`).

### User Commands
* `/start` - Bot greeting and status.
* `/start file_<code\>` (or `/start <code\>`) - Retrieve a shared file via unique code.
* `/search <keyword>` or `/find <keyword>` - Search indexed files by name.
* `/files` or `/list` - Browse the 10 most recently indexed files with instant download buttons.
* **Direct Text Search:** Send any keyword or title directly in a private DM with the bot to find matching files.
* `/help` - View command guidance.

---

## 🧪 Automated Testing

The project includes an automated test suite covering configuration parsing, permissions, database persistence, delivery strategies, group restrictions, auto-destruct scheduling, and developer authentication.

To run the tests:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

All 13 tests verify:
- ✅ Strict developer authorization on mode changes and timer configuration.
- ✅ Correct application of `protect_content=True` in View-Only mode.
- ✅ Source header stripping via `copy_message(..., protect_content=False)` in Downloadable mode.
- ✅ Auto-deletion warning notice generation and timer scheduling.
- ✅ Rejection and DM redirection for downloadable requests originating from group chats.
- ✅ Database persistence and restart survivability of pending deletions.
