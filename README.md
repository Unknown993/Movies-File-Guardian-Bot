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

## 💎 Automated Telegram Stars Payments & Paywall System

The bot features a fully automated in-app payment and subscription paywall engine:

### 🌟 Automated In-App Payments (Telegram Stars ⭐)
* **Zero External Gateways:** Transactions are processed natively through Telegram Stars (`currency="XTR"`). Users never need to upload payment screenshots or wait for manual verification.
* **One-Tap Checkout:** Users run `/plan` (or `/buy`), select a plan, and pay directly via Telegram.
* **Instant Activation & Auto-Extension:** The bot automatically approves pre-checkout, activates the subscription, and extends existing subscriptions if renewed before expiry.
* **Default Star Plans:**
  * ⭐ **10 Stars** — 7 Days Pass
  * ⭐ **25 Stars** — 15 Days Pass
  * ⭐ **45 Stars** — 1 Month VIP
  * ⭐ **80 Stars** — 2 Months VIP
  * ⭐ **120 Stars** — 3 Months VIP

### 🔒 On/Off Paywall (Paid-Members Only Access Control)
* **Turn ON/OFF Anytime:** Toggle the paywall on or off instantly with `/paywall on` or `/paywall off`, or via the interactive `/settings` button.
* **When ON (Paid Only):** Only active VIP subscribers (and Admins/Developer) can access files, perform searches, or download from deep links. Unpaid users are presented with a subscription prompt.
* **When OFF (Free Public Access):** Anyone can search and receive files freely.
* **Auto Expiry Sweeper:** Background job checks expired subscriptions every 60 seconds and notifies users when their plan has ended.

### 🕹️ Payment & Paywall Commands
* `/plan` / `/plans` / `/buy` — Display VIP plans and buy instantly with Stars.
* `/myplan` — Check your active subscription, expiry date (IST & UTC), and time remaining.
* `/paywall <on|off|status>` — Toggle or check paywall status (Admin only).
* `/add_premium <user_id> <time>` — Manually grant VIP access (e.g. `/add_premium 123456789 30 days`).
* `/remove_premium <user_id>` — Revoke a user's subscription (Admin only).
* `/get_premium <user_id>` — Inspect subscription details of a user (Admin only).
* `/premium_users` — List all active VIP subscribers (Admin only).

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

### 4. Run Locally (Windows / Linux / Mac)

**Windows (1-Click Launchers):**
* Double-click `start.bat` to run the Telegram Bot.
* Double-click `run_telethon.bat` to run full channel history indexing.
* Double-click `push_to_github.bat` to sync changes to GitHub.

**Command Line:**
```powershell
.\.venv\Scripts\python.exe run.py
```

---

## ☁️ Deploying to Heroku from GitHub

The bot is fully optimized for 1-click or Git-connected Heroku deployment.

### 1. Heroku Architecture Compatibility
* **`Procfile`:** Pre-configured with both `worker: python run.py` (recommended) and `web: python run.py`.
* **Automatic Port Binding:** If deployed on a Heroku `web` dyno, the bot automatically starts an internal lightweight HTTP health server to bind `$PORT` within 60s, preventing `Error R10 (Boot timeout)`.
* **StringSession Authentication:** Avoids pushing sensitive `.session` files to GitHub by using `TELEGRAM_SESSION_STRING`.
* **Database Backup & Recovery:** Because Heroku dynos have ephemeral filesystems, use `/backup` to download your SQLite database, and configure `DATABASE_DOWNLOAD_URL` to auto-restore on boot.

### 2. Steps to Deploy
1. **Push Repository to GitHub:**
   Run `push_to_github.bat` or `git push origin main`.
2. **Generate Telethon String Session (Optional, for channel indexing):**
   Run locally:
   ```powershell
   python generate_session_string.py
   ```
   Copy the generated string to your clipboard.
3. **Deploy on Heroku:**
   - Create a new app on [Heroku Dashboard](https://dashboard.heroku.com).
   - Under **Deploy**, connect your GitHub repository and branch `main`.
   - Under **Settings** -> **Config Vars**, add the following:
     - `BOT_TOKEN`: Your Telegram Bot Token.
     - `DEVELOPER_ID`: Your numeric Telegram ID.
     - `TELEGRAM_API_ID`: Your Telegram API ID.
     - `TELEGRAM_API_HASH`: Your Telegram API Hash.
     - `TELEGRAM_SESSION_STRING`: The string generated in Step 2.
     - `DEFAULT_DELIVERY_MODE`: `view_only` (or `downloadable`).
     - `DEFAULT_AUTO_DELETE_SECONDS`: `180`.
     - `DATABASE_DOWNLOAD_URL`: *(Optional)* Direct link to your backup SQLite DB to auto-restore on restarts.
4. **Enable Dyno:**
   - Go to **Resources** tab.
   - Enable the `worker` dyno (or `web` dyno).

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
* `/index_range <start_id> <end_id>` - Fast concurrent scan and register up to 1,000 messages (e.g. `/index_range 1 500`).
* **CLI Fast Indexer (`fast_index.py`):** Index files directly from CMD without Telegram chat limits: `.venv\Scripts\python.exe fast_index.py 1 1000`.
* **Full-Channel History Exporter (`telethon_indexer.py`):** Index thousands of channel files automatically via Telegram MTProto in seconds.
* **Auto-Index Channel Posts:** Any new file or media message posted to your configured `STORAGE_CHANNEL_ID` is automatically registered and the developer is sent the share link in their DM.
* **Upload Media:** Send or forward any file (Document, Video, Audio, Photo, Voice, GIF) directly to the bot to generate a secure shareable deep-link (`t.me/<bot_username>?start=file_<code>`).

### General User & Interactive Menu Commands
* `/start` - Interactive navigation menu with buttons:
  * `➕️ Add Me To Your Chat ➕` - Deep link to add bot to groups.
  * `Search 🔎` - Instant inline search via Telegram switch query.
  * `Help 🕸️` - Category menu hub (Admin, Filters, Connections, File Store, Extra Modes, Group Manager, Status).
  * `About ✨` & `Source Code 📜` - Bot specifications and repository credits.
* `/help` - Open the interactive Help category menu.
* **Inline Search (`@bot_username <query>`):** Search catalog from any chat with instant thumbnail and size previews.
* `/ping` - Check bot response latency (ms) and server uptime.
* `/imdb <title>` (or `/imbd`) - Look up movie or TV series details, release year, cast, and poster on IMDb.
* `/search <name>` - Search for files in the database.
* `/files` or `/list` - Browse the 10 most recently indexed files.
* **Auto-Filter Search:** Send any movie or file title in groups or PM to get interactive result buttons with pagination (`Next ➡️`, `⬅️ Back`) and caller button-lock.
* **Spelling Suggestions:** Fuzzy spelling matcher (`Did you mean: ... ?`) suggests close titles when no exact matches are found.

### Group Management & Custom Filters
* `/connect [chat_id]` - Link a group to your private DM to manage filters privately.
* `/disconnect [chat_id]` - Disconnect a linked group.
* `/connections` - Interactive menu with one-tap buttons to manage, disconnect, or delete active group connections.
* `/welcome <on|off>` - Enable or disable auto-cleaning group welcome greetings.
* `/filter <keyword> <reply>` - Set custom keyword response for the group (supports media reply).
* `/filters` - List all custom filters in the group.
* `/del <keyword>` - Delete a specific group filter.
* `/delall` - Clear all filters in the group.
* `/set_template <template>` & `/get_template` - Configure custom caption and IMDb result templates.

### File Store & Batching
* `/link` - Reply to any media in chat/channel to get an instant shareable deep link.
* `/batch <start_url> <end_url>` - Bundle an entire range of channel messages into a single batch link (`t.me/<bot>?start=batch_<id>`).
* `/delete` - Delete a specific file from the catalog (reply or `/delete <file_code>`).
* `/deleteall` - Purge entire file catalog from database (Developer only).

### Group Moderation & Extra Utilities
* `/ban <user_id|reply>` / `/unban <user_id|reply>` - Ban or unban members.
* `/tban <time> <reply>` - Temporarily ban user (e.g. `/tban 2h`, `/tban 1d`).
* `/mute <reply>` / `/unmute <reply>` / `/tmute <time> <reply>` - Mute management.
* `/pin` / `/unpin` - Pin and unpin messages.
* `/purge` - Delete all messages between the replied message and current command.
* `/dkick` - Group cleanup for deleted accounts.
* `/instatus` - Group member and administrator status inspector.
* `/inkick` - Inactive member sweep guide for administrators.
* `/id`, `/info` - User and chat ID inspector.
* `/json` - Inspect raw JSON structure of any replied message.
* `/font <text>` - Convert text into stylish/fancy Unicode fonts (Typewriter, Bold, Monospace, Script, Double Struck).
* `/share <text>` - Generate a shareable Telegram link with pre-filled text.
* `/password [length]` or `/genpass` - Generate secure random passwords.
* `/written <filename>` - Convert replied text into a downloadable file.
* `/restart` - Restart the bot process (Admin only).

### Admin, Control & Channel Management
* `/settings` - Open interactive control panel for modes, timers, and welcome greetings.
* `/logs` - Inspect recent runtime logs and errors.
* `/index` - Bulk index messages from a channel into the database.
* `/channel` - List all connected and indexed storage channels.
* `/leave [chat_id]` - Instruct bot to leave a chat.
* `/disable <chat_id> [reason]` - Disable a chat and make the bot leave.
* `/enable <chat_id>` - Re-enable a disabled chat.
* `/ban_user <user_id|reply> [reason]` - Ban a user across the entire bot.
* `/unban_user <user_id|reply>` - Unban a user across the bot.
* `/users` - View list of all registered users and their Telegram IDs.
* `/clear_junk` - Clean up blocked and deleted user accounts from database.
* `/clear_junk_group` - Clean up unreachable or removed groups from database.
* `/broadcast <text|media reply>` - Send announcement to all registered bot users with live delivery stats.
* `/group_broadcast <text|media reply>` - Send announcement to all connected groups.
* `/gfilter <keyword> <reply>` / `/gfilters` / `/delg` / `/delallg` - Network-wide global filters.
* **Force Subscription (FSUB):** Restrict file delivery until the user joins your `AUTH_CHANNEL_ID`.

---

## 🧪 Automated Testing

The project includes an automated test suite covering configuration parsing, permissions, database persistence, delivery strategies, group restrictions, auto-destruct scheduling, and developer authentication.

To run the tests:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

All 20 tests verify:
- ✅ Strict developer authorization on mode changes and timer configuration.
- ✅ Correct application of `protect_content=True` in View-Only mode.
- ✅ Source header stripping via `copy_message(..., protect_content=False)` in Downloadable mode.
- ✅ Auto-deletion warning notice generation and timer scheduling.
- ✅ Rejection and DM redirection for downloadable requests originating from group chats.
- ✅ Database persistence and restart survivability of pending deletions.
- ✅ User and Group/Chat tracking for broadcasting and welcome settings.
- ✅ Manual group filters, global filters, and priority overrides.
- ✅ Batch link generation, persistence, and sequential retrieval.
- ✅ Paginated Auto-Filter search with offset counting.
- ✅ Force Subscription membership validation.
- ✅ Group moderation duration parsing.
