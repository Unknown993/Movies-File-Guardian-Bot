"""
Script templates and formatted texts for Telegram Bot.
Matches the styling, buttons, and characterstics of MR.Guardian_bot / Professor-Bot.
"""

class Script:
    START_TXT = """<b>✨ Hᴇʟʟᴏ {user}!

Mʏ Nᴀᴍᴇ Is {bot}.

I ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴀɴʏ ғɪʟᴇs ғᴏʀ ʏᴏᴜ. Jᴜsᴛ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴏʀ sᴇᴀʀᴄʜ ᴅɪʀᴇᴄᴛʟʏ ʜᴇʀᴇ!</b>"""

    HELP_TXT = """<b>Hᴇʏ {user} 👋
Hᴇʀᴇ Is Mʏ Hᴇʟᴘ Mᴇɴᴜ. Cʟɪᴄᴋ ᴏɴ ᴀɴʏ ᴄᴀᴛᴇɢᴏʀʏ ʙᴇʟᴏᴡ ᴛᴏ ᴇxᴘʟᴏʀᴇ ғᴇᴀᴛᴜʀᴇs:</b>"""

    ABOUT_TXT = """<b>✯ Mʏ Nᴀᴍᴇ: {bot}
✯ Dᴇᴠᴇʟᴏᴘᴇʀ: <a href="https://t.me/Unknown993">Mr. Guardian</a>
✯ Cᴏᴅᴇᴅ Oɴ: Python / Python-Telegram-Bot
✯ Mʏ Dᴀᴛᴀʙᴀsᴇ: SQLite3 (Async)
✯ Cᴏɴᴛᴇɴᴛ Pʀᴏᴛᴇᴄᴛɪᴏɴ: Active (Dual Mode)
✯ Vᴇʀsɪᴏɴ: TeleBot v4.6 (2026)</b>"""

    SOURCE_TXT = """<b>NOTE:</b>
- Sᴏᴜʀᴄᴇ Cᴏᴅᴇ: <a href="https://github.com/Unknown993/PROFESSOR-BOT">PROFESSOR-BOT / TeleBot</a>
- Dᴇᴠᴇʟᴏᴘᴇʀ: <a href="https://t.me/Unknown993">Mr. Guardian</a>"""

    FILE_TXT = """<b>➤ Hᴇʟᴘ Fᴏʀ Fɪʟᴇ Sᴛᴏʀᴇ</b>

<i>Bʏ ᴜsɪɴɢ ᴛʜɪs ᴍᴏᴅᴜʟᴇ ʏᴏᴜ ᴄᴀɴ sᴛᴏʀᴇ ғɪʟᴇs ɪɴ ᴍʏ ᴅᴀᴛᴀʙᴀsᴇ ᴀɴᴅ I ᴡɪʟʟ ɢɪᴠᴇ ʏᴏᴜ ᴀ ᴘᴇʀᴍᴀɴᴇɴᴛ ʟɪɴᴋ ᴛᴏ ᴀᴄᴄᴇss ᴛʜᴇ sᴀᴠᴇᴅ ғɪʟᴇs.</i>

<b>⪼ Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
➪ /link › Rᴇᴘʟʏ ᴛᴏ ᴀɴʏ ᴍᴇᴅɪᴀ ᴛᴏ ɢᴇᴛ ᴛʜᴇ ʟɪɴᴋ
➪ /batch › Tᴏ ᴄʀᴇᴀᴛᴇ ʟɪɴᴋ ғᴏʀ ᴍᴜʟᴛɪᴘʟᴇ ᴍᴇᴅɪᴀ

<b>⪼ EG:</b>
<code>/batch https://t.me/mychannel/1 https://t.me/mychannel/10</code>"""

    FILTER_TXT = "<b>Sᴇʟᴇᴄᴛ Wʜɪᴄʜ Fɪʟᴛᴇʀ Mᴏᴅᴜʟᴇ Yᴏᴜ Wᴀɴᴛ...✨</b>"

    GLOBALFILTER_TXT = """<b>Hᴇʟᴘ Fᴏʀ Gʟᴏʙᴀʟ Fɪʟᴛᴇʀs</b>

<i>Fɪʟᴛᴇʀ ɪs ᴛʜᴇ ғᴇᴀᴛᴜʀᴇ ᴡʜᴇʀᴇ ᴀᴅᴍɪɴs ᴄᴀɴ sᴇᴛ ᴀᴜᴛᴏᴍᴀᴛᴇᴅ ʀᴇᴘʟɪᴇs ᴀᴄʀᴏss ᴀʟʟ ɢʀᴏᴜᴘs ᴡʜᴇɴᴇᴠᴇʀ ᴀ ᴋᴇʏᴡᴏʀᴅ ɪs ғᴏᴜɴᴅ.</i>

<b>Nᴏᴛᴇ:</b> Tʜɪs ᴍᴏᴅᴜʟᴇ ᴏɴʟʏ ᴡᴏʀᴋs ғᴏʀ Bᴏᴛ Aᴅᴍɪɴs.

<b>Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
• /gfilter &lt;keyword&gt; &lt;reply&gt; - Aᴅᴅ ᴀ ɢʟᴏʙᴀʟ ғɪʟᴛᴇʀ
• /gfilters - Lɪsᴛ ᴀʟʟ ɢʟᴏʙᴀʟ ғɪʟᴛᴇʀs
• /delg &lt;keyword&gt; - Dᴇʟᴇᴛᴇ ᴀ sᴘᴇᴄɪғɪᴄ ɢʟᴏʙᴀʟ ғɪʟᴛᴇʀ
• /delallg - Dᴇʟᴇᴛᴇ ᴀʟʟ ɢʟᴏʙᴀʟ ғɪʟᴛᴇʀs"""

    MANUELFILTER_TXT = """<b>Hᴇʟᴘ Fᴏʀ Mᴀɴᴜᴀʟ Fɪʟᴛᴇʀs</b>

<i>Sᴇᴛ ᴀᴜᴛᴏᴍᴀᴛᴇᴅ ʀᴇᴘʟɪᴇs ғᴏʀ sᴘᴇᴄɪғɪᴄ ᴋᴇʏᴡᴏʀᴅs ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ.</i>

<b>Nᴏᴛᴇ:</b>
1. Bᴏᴛ sʜᴏᴜʟᴅ ʙᴇ ᴀɴ ᴀᴅᴍɪɴ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ.
2. Oɴʟʏ ɢʀᴏᴜᴘ ᴀᴅᴍɪɴs ᴄᴀɴ ᴍᴀɴᴀɢᴇ ғɪʟᴛᴇʀs.

<b>Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
• /filter &lt;keyword&gt; &lt;reply&gt; - Aᴅᴅ ᴀ ғɪʟᴛᴇʀ
• /filters - Vɪᴇᴡ ᴀʟʟ ғɪʟᴛᴇʀs ɪɴ ᴛʜɪs ᴄʜᴀᴛ
• /del &lt;keyword&gt; - Dᴇʟᴇᴛᴇ ᴀ sᴘᴇᴄɪғɪᴄ ғɪʟᴛᴇʀ
• /delall - Dᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴛᴇʀs ɪɴ ᴛʜɪs ᴄʜᴀᴛ"""

    BUTTON_TXT = """<b>Hᴇʟᴘ Fᴏʀ Bᴜᴛᴛᴏɴs</b>

<i>Tʜɪs ʙᴏᴛ sᴜᴘᴘᴏʀᴛs ʙᴏᴛʜ URL ᴀɴᴅ Aʟᴇʀᴛ ɪɴʟɪɴᴇ ʙᴜᴛᴛᴏɴs ɪɴ ғɪʟᴛᴇʀ ʀᴇᴘʟɪᴇs:</i>

<b>URL Bᴜᴛᴛᴏɴs:</b>
<code>[Bᴜᴛᴛᴏɴ Tᴇxᴛ](buttonurl:https://t.me/channel)</code>

<b>Aʟᴇʀᴛ Bᴜᴛᴛᴏɴs:</b>
<code>[Bᴜᴛᴛᴏɴ Tᴇxᴛ](buttonalert:Tʜɪs ɪs ᴀɴ ᴀʟᴇʀᴛ ᴍᴇssᴀɢᴇ)</code>"""

    AUTOFILTER_TXT = """<b>Hᴇʟᴘ Fᴏʀ Aᴜᴛᴏ-Fɪʟᴛᴇʀ</b>

<i>Aᴜᴛᴏ-Fɪʟᴛᴇʀ sᴇᴀʀᴄʜᴇs ʏᴏᴜʀ ᴄᴀᴛᴀʟᴏɢ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴡʜᴇɴᴇᴠᴇʀ ᴀ ᴜsᴇʀ sᴇɴᴅs ᴀ ɴᴀᴍᴇ ɪɴ ɢʀᴏᴜᴘ ᴏʀ PM.</i>

<b>Cᴏᴍᴍᴀɴᴅs:</b>
• /search &lt;keyword&gt; - Mᴀɴᴜᴀʟ sᴇᴀʀᴄʜ
• /set_template &lt;template&gt; - Sᴇᴛ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ/IMDb ᴛᴇᴍᴘʟᴀᴛᴇ
• /get_template - Vɪᴇᴡ ᴄᴜʀʀᴇɴᴛ ᴛᴇᴍᴘʟᴀᴛᴇ
• /settings - Tᴏɢɢʟᴇ ᴀᴜᴛᴏғɪʟᴛᴇʀ ʙᴜᴛᴛᴏɴ ʟᴀʏᴏᴜᴛ & sᴇᴛᴛɪɴɢs"""

    CONNECTION_TXT = """<b>Hᴇʟᴘ Fᴏʀ Cᴏɴɴᴇᴄᴛɪᴏɴs</b>

<i>Cᴏɴɴᴇᴄᴛ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴛᴏ ʏᴏᴜʀ PM ᴛᴏ ᴍᴀɴᴀɢᴇ ғɪʟᴛᴇʀs ᴀɴᴅ sᴇᴛᴛɪɴɢs ᴡɪᴛʜᴏᴜᴛ sᴘᴀᴍᴍɪɴɢ ʏᴏᴜʀ ɢʀᴏᴜᴘ.</i>

<b>Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
• /connect &lt;group_id&gt; - Cᴏɴɴᴇᴄᴛ ɢʀᴏᴜᴘ ᴛᴏ PM
• /disconnect - Dɪsᴄᴏɴɴᴇᴄᴛ ғʀᴏᴍ ɢʀᴏᴜᴘ
• /connections - Iɴᴛᴇʀᴀᴄᴛɪᴠᴇ ᴍᴇɴᴜ ᴛᴏ ᴠɪᴇᴡ & ᴍᴀɴᴀɢᴇ ᴀʟʟ ʏᴏᴜʀ ᴄᴏɴɴᴇᴄᴛɪᴏɴs"""

    ADMIN_TXT = """<b>⚙️ Hᴇʟᴘ Fᴏʀ Aᴅᴍɪɴs</b>

<i>Tʜɪs ᴍᴏᴅᴜʟᴇ ᴏɴʟʏ ᴡᴏʀᴋs ғᴏʀ Bᴏᴛ Aᴅᴍɪɴs.</i>

<b>Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
• /logs - Gᴇᴛ ʀᴇᴄᴇɴᴛ ᴇʀʀᴏʀ ᴀɴᴅ ʀᴜɴᴛɪᴍᴇ ʟᴏɢs
• /delete - Dᴇʟᴇᴛᴇ ᴀ sᴘᴇᴄɪғɪᴄ ғɪʟᴇ (ʀᴇᴘʟʏ ᴏʀ ᴄᴏᴅᴇ)
• /deleteall - Wɪᴘᴇ ᴇɴᴛɪʀᴇ ғɪʟᴇ ᴄᴀᴛᴀʟᴏɢ (Dᴇᴠᴇʟᴏᴘᴇʀ ᴏɴʟʏ)
• /users - Gᴇᴛ ʟɪsᴛ ᴏғ ᴀʟʟ ʀᴇɢɪsᴛᴇʀᴇᴅ ᴜsᴇʀs ᴀɴᴅ IDs
• /channel - Lɪsᴛ ᴄᴏɴɴᴇᴄᴛᴇᴅ sᴛᴏʀᴀɢᴇ ᴄʜᴀɴɴᴇʟs
• /broadcast - Bʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ ᴛᴏ ᴀʟʟ ᴜsᴇʀs
• /group_broadcast - Bʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ ᴛᴏ ᴀʟʟ ᴄᴏɴɴᴇᴄᴛᴇᴅ ɢʀᴏᴜᴘs
• /leave &lt;chat_id&gt; - Lᴇᴀᴠᴇ ᴀ sᴘᴇᴄɪғɪᴄ ᴄʜᴀᴛ
• /disable &lt;chat_id&gt; - Dɪsᴀʙʟᴇ ᴀ ᴄʜᴀᴛ
• /enable &lt;chat_id&gt; - Rᴇ-ᴇɴᴀʙʟᴇ ᴀ ᴅɪsᴀʙʟᴇᴅ ᴄʜᴀᴛ
• /ban_user &lt;id&gt; - Bᴀɴ ᴀ ᴜsᴇʀ ғʀᴏᴍ ᴛʜᴇ ʙᴏᴛ
• /unban_user &lt;id&gt; - Uɴʙᴀɴ ᴀ ᴜsᴇʀ
• /clear_junk - Cʟᴇᴀɴ ᴅᴇʟᴇᴛᴇᴅ ᴀɴᴅ ʙʟᴏᴄᴋᴇᴅ ᴀᴄᴄᴏᴜɴᴛs
• /clear_junk_group - Cʟᴇᴀɴ ᴅᴇᴀᴅ ɢʀᴏᴜᴘs ғʀᴏᴍ ᴅᴀᴛᴀʙᴀsᴇ
• /fast_index [start] [end] - Hɪɢʜ-sᴘᴇᴇᴅ MTProto ɪɴᴅᴇxᴇʀ (ɴᴏ ᴄʜᴀɴɴᴇʟ ᴘᴏsᴛs)
• /index_range &lt;start&gt; &lt;end&gt; - Bᴜʟᴋ ɪɴᴅᴇx ᴄʜᴀɴɴᴇʟ ᴍᴇssᴀɢᴇs
• /stop_index - Sᴛᴏᴘ ᴀɴʏ ʀᴜɴɴɪɴɢ ᴄʜᴀɴɴᴇʟ ɪɴᴅᴇxɪɴɢ
• /restart - Rᴇsᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ"""

    STATUS_TXT = """<b>❄️ Bᴏᴛ & Dᴀᴛᴀʙᴀsᴇ Sᴛᴀᴛᴜs:</b>

◉ <b>Tᴏᴛᴀʟ Fɪʟᴇs:</b> <code>{files}</code>
◉ <b>Tᴏᴛᴀʟ Usᴇʀs:</b> <code>{users}</code>
◉ <b>Tᴏᴛᴀʟ Gʀᴏᴜᴘs:</b> <code>{chats}</code>
◉ <b>Dᴀᴛᴀʙᴀsᴇ Sɪᴢᴇ:</b> <code>{db_size}</code>
◉ <b>Uᴘᴛɪᴍᴇ:</b> <code>{uptime}</code>"""

    SERVER_STATS = """<b>🖥️ Sᴇʀᴠᴇʀ Rᴇsᴏᴜʀᴄᴇ Sᴛᴀᴛs:</b>

• <b>Uᴘᴛɪᴍᴇ:</b> <code>{uptime}</code>
• <b>CPU Usᴀɢᴇ:</b> <code>{cpu}%</code>
• <b>RAM Usᴀɢᴇ:</b> <code>{ram}%</code>
• <b>Tᴏᴛᴀʟ Dɪsᴋ:</b> <code>{disk_total}</code>
• <b>Usᴇᴅ Dɪsᴋ:</b> <code>{disk_used} ({disk_percent}%)</code>
• <b>Fʀᴇᴇ Dɪsᴋ:</b> <code>{disk_free}</code>"""

    GROUPMANAGER_TXT = """<b>🛡️ Hᴇʟᴘ Fᴏʀ Gʀᴏᴜᴘ Mᴀɴᴀɢᴇʀ</b>

<i>Mᴏᴅᴇʀᴀᴛɪᴏɴ ᴛᴏᴏʟs ғᴏʀ ɢʀᴏᴜᴘ ᴀᴅᴍɪɴɪsᴛʀᴀᴛᴏʀs:</i>

<b>Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
• /ban - Bᴀɴ ᴀ ᴜsᴇʀ ғʀᴏᴍ ᴛʜᴇ ɢʀᴏᴜᴘ
• /unban - Uɴʙᴀɴ ᴀ ʙᴀɴɴᴇᴅ ᴜsᴇʀ
• /tban &lt;time&gt; - Tᴇᴍᴘᴏʀᴀʀʏ ʙᴀɴ (ᴇ.ɢ. <code>/tban 2h</code>)
• /mute - Mᴜᴛᴇ ᴀ ᴜsᴇʀ
• /unmute - Uɴᴍᴜᴛᴇ ᴀ ᴜsᴇʀ
• /tmute &lt;time&gt; - Tᴇᴍᴘᴏʀᴀʀʏ ᴍᴜᴛᴇ (ᴇ.ɢ. <code>/tmute 30m</code>)
• /pin - Pɪɴ ᴀ ᴍᴇssᴀɢᴇ
• /unpin - Uɴᴘɪɴ ᴀ ᴍᴇssᴀɢᴇ
• /purge - Dᴇʟᴇᴛᴇ ᴀʟʟ ᴍᴇssᴀɢᴇs ᴜᴘ ᴛᴏ ʀᴇᴘʟɪᴇᴅ ᴍᴇssᴀɢᴇ
• /dkick - Kɪᴄᴋ ᴀʟʟ ᴅᴇʟᴇᴛᴇᴅ ᴀᴄᴄᴏᴜɴᴛs ғʀᴏᴍ ɢʀᴏᴜᴘ
• /instatus - Cʜᴇᴄᴋ ɢʀᴏᴜᴘ ᴍᴇᴍʙᴇʀ sᴛᴀᴛᴜs"""

    EXTRAMOD_TXT = """<b>✨ Hᴇʟᴘ Fᴏʀ Exᴛʀᴀ Mᴏᴅᴜʟᴇs</b>

<i>Usᴇғᴜʟ ᴇxᴛʀᴀ ᴜᴛɪʟɪᴛɪᴇs ғᴏʀ ᴜsᴇʀs ᴀɴᴅ ɢʀᴏᴜᴘs:</i>

<b>Cᴏᴍᴍᴀɴᴅs & Usᴀɢᴇ:</b>
• /id - Gᴇᴛ Telegram IDs (Usᴇʀ, Cʜᴀᴛ, Mᴇssᴀɢᴇ)
• /info - Gᴇᴛ ᴅᴇᴛᴀɪʟᴇᴅ ᴘʀᴏғɪʟᴇ ɪɴғᴏʀᴍᴀᴛɪᴏɴ
• /imdb &lt;title&gt; - Lᴏᴏᴋ ᴜᴘ ᴍᴏᴠɪᴇ ᴏʀ sᴇʀɪᴇs ɪɴғᴏ ᴏɴ IMDb
• /ping - Cʜᴇᴄᴋ ʙᴏᴛ ʟᴀᴛᴇɴᴄʏ ᴀɴᴅ sᴇʀᴠᴇʀ ᴜᴘᴛɪᴍᴇ
• /json - Rᴇᴘʟʏ ᴛᴏ ᴀɴʏ ᴍᴇssᴀɢᴇ ᴛᴏ ɢᴇᴛ ɪᴛs ʀᴀᴡ JSON sᴛʀᴜᴄᴛᴜʀᴇ
• /font &lt;text&gt; - Cᴏɴᴠᴇʀᴛ ᴛᴇxᴛ ᴛᴏ sᴛʏʟɪsʜ / ғᴀɴᴄʏ ғᴏɴᴛs
• /share &lt;text&gt; - Gᴇɴᴇʀᴀᴛᴇ ᴀ sʜᴀʀᴇᴀʙʟᴇ Telegram ʟɪɴᴋ
• /password [length] - Gᴇɴᴇʀᴀᴛᴇ ᴀ sᴇᴄᴜʀᴇ ʀᴀɴᴅᴏᴍ ᴘᴀssᴡᴏʀᴅ
• /written &lt;file_name&gt; - Cᴏɴᴠᴇʀᴛ ʀᴇᴘʟɪᴇᴅ ᴛᴇxᴛ ɪɴᴛᴏ ᴀ ᴅᴏᴡɴʟᴏᴀᴅᴀʙʟᴇ ғɪʟᴇ"""

    IMDB_TEMPLATE = """<b>🏷️ Tɪᴛʟᴇ:</b> <a href="{url}">{title}</a>
<b>🎭 Gᴇɴʀᴇs:</b> {genres}
<b>📆 Yᴇᴀʀ:</b> {year}
<b>🌟 Rᴀᴛɪɴɢ:</b> {rating}/10
<b>👥 Cᴀsᴛ:</b> {cast}"""

    BUTTON_LOCK_TEXT = "Hᴇʏ {name}!\nTʜɪs ʀᴇsᴜʟᴛ ɪs ɴᴏᴛ ғᴏʀ ʏᴏᴜ. Pʟᴇᴀsᴇ sᴇᴀʀᴄʜ ғᴏʀ ʏᴏᴜʀsᴇʟғ! 🔎"

    HOW_TO_DOWNLOAD = """<b>Hᴏᴡ Tᴏ Gᴇᴛ Fɪʟᴇs:</b>
1. Sᴇᴀʀᴄʜ ғᴏʀ ᴀɴʏ ᴍᴏᴠɪᴇ, sᴇʀɪᴇs, ᴏʀ ғɪʟᴇ ɴᴀᴍᴇ.
2. Cʟɪᴄᴋ ᴏɴ ᴛʜᴇ ғɪʟᴇ ʙᴜᴛᴛᴏɴ.
3. Yᴏᴜʀ ғɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟɪᴠᴇʀᴇᴅ ɪɴsᴛᴀɴᴛʟʏ ᴡɪᴛʜ sᴛʀɪᴄᴛ ᴄᴏɴᴛᴇɴᴛ ᴘʀᴏᴛᴇᴄᴛɪᴏɴ!"""
