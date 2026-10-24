from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.config import ADMIN_IDS
from Encoder.utils.filters import allowed


@Client.on_message(filters.command("start") & allowed)
async def cmd_start(client, msg: Message):
    await msg.reply(f"**Hello** 👋\n")


@Client.on_message(filters.command("help") & allowed)
async def cmd_help(client, msg: Message):
    uid = msg.from_user.id
    user_cmds = (
        f"<b>➲ ᴜꜱᴇʀ ᴄᴏᴍᴍᴀɴᴅꜱ</b>\n"
        f"<blockquote expandable><b>/compress</b> — ᴄᴏᴍᴘʀᴇꜱꜱ ᴀ ᴠɪᴅᴇᴏ (ʀᴇᴘʟʏ ᴛᴏ ᴠɪᴅᴇᴏ)\n"
        f"<b>/l <link> —</b> ʟᴇᴇᴄʜ (ᴛᴏʀʀᴇɴᴛ/ᴍᴀɢɴᴇᴛ/ᴅɪʀᴇᴄᴛ/ɢᴅʀɪᴠᴇ/ᴍᴇɢᴀ, ʙᴀᴛᴄʜ ᴛᴏᴏ)\n"
        f"<b>/l -n newname <link> —</b> ʟᴇᴇᴄʜ ᴡɪᴛʜ ᴄᴜꜱᴛᴏᴍ ꜰɪʟᴇɴᴀᴍᴇ (<code>{{episode}} {{season}} {{quality}}</code> ᴡᴏʀᴋ)\n"
        f"<b>/batch</b> — ꜱᴛᴀʀᴛ ʙᴀᴛᴄʜ ᴍᴏᴅᴇ\n"
        f"<b>/done</b> — Qᴜᴇᴜᴇ ᴀʟʟ ʙᴀᴛᴄʜ ᴠɪᴅᴇᴏꜱ\n"
        f"<b>/settings</b> — ᴠɪᴇᴡ ʏᴏᴜʀ ᴇɴᴄᴏᴅᴇ ꜱᴇᴛᴛɪɴɢꜱ\n"
        f"<b>/queue</b> — Qᴜᴇᴜᴇ ꜱᴛᴀᴛᴜꜱ</blockquote>\n\n"
        f"<b>➲ ꜱᴜʙᴛɪᴛʟᴇ ᴍᴏᴅᴇ ꜱᴇᴛᴛɪɴɢꜱ</b>\n"
        f"<blockquote><b>/addsub</b> — ᴀᴅᴅ ꜱᴏꜰᴛ ꜱᴜʙᴛɪᴛʟᴇꜱ ᴛᴏ ᴀ ᴠɪᴅᴇᴏ\n"
        f"<b>/merge</b> — ᴍᴇʀɢᴇ ᴀᴅᴅᴇᴅ ꜱᴜʙᴛɪᴛʟᴇꜱ ɪɴᴛᴏ ᴛʜᴇ ᴠɪᴅᴇᴏ\n"
        f"<b>/extractsub</b> — ᴇxᴛʀᴀᴄᴛ ᴀʟʟ ꜱᴜʙᴛɪᴛʟᴇꜱ ꜰʀᴏᴍ ᴀ ᴠɪᴅᴇᴏ</blockquote>\n\n"
        f"<b>➲ ʏᴏᴜʀ ᴇɴᴄᴏᴅᴇ ꜱᴇᴛᴛɪɴɢꜱ</b>\n"
        f"<blockquote expandable><b>/video x264|x265</b> — ᴠɪᴅᴇᴏ ᴄᴏᴅᴇᴄ\n"
        f"<b>/crf 28</b> — ᴄʀꜰ ᴠᴀʟᴜᴇ (0–51)\n"
        f"<b>/preset medium</b> — ᴇɴᴄᴏᴅɪɴɢ ᴘʀᴇꜱᴇᴛ\n"
        f"<b>/resolution 854x480</b> — ᴏᴜᴛᴘᴜᴛ ʀᴇꜱᴏʟᴜᴛɪᴏɴ\n"
        f"<b>/audiobit 128k</b> — ᴀᴜᴅɪᴏ ʙɪᴛʀᴀᴛᴇ\n"
        f"<b>/audio aac|mp3|opus|ac3|flac|wav|copy</b> — ᴀᴜᴅɪᴏ ᴄᴏᴅᴇᴄ\n<b>/fps 24|copy</b> — ꜰʀᴀᴍᴇ ʀᴀᴛᴇ\n<b>/bitdepth 8|10</b> — ʙɪᴛ ᴅᴇᴘᴛʜ\n<b>/source</b> — ʀᴇɴᴀᴍᴇ ꜰʀᴏᴍ ꜰɪʟᴇ ɴᴀᴍᴇ / ᴄᴀᴘᴛɪᴏɴ / ʙᴏᴛʜ\n"
        f"<b>/tune animation</b> — ᴇɴᴄᴏᴅɪɴɢ ᴛᴜɴᴇ</blockquote>\n\n"
        f"<b>➲ ᴍᴇᴛᴀᴅᴀᴛᴀ</b>\n"
        f"<blockquote><b>/metadata Your_Text</b> — ꜱᴇᴛ ᴍᴇᴛᴀᴅᴀᴛᴀ</blockquote>\n\n<b>➲ ꜱᴇᴛᴛɪɴɢꜱ ᴍᴇɴᴜ</b>\n<blockquote><b>/us</b> — ᴀʟʟ ꜱᴇᴛᴛɪɴɢꜱ ᴡɪᴛʜ ʙᴜᴛᴛᴏɴꜱ (ᴀʟꜱᴏ /usersettings)</blockquote>\n\n"
        f"<b>➲ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
        f"<blockquote><b>/t</b> — ꜱᴇᴛ ᴛʜᴜᴍʙɴᴀɪʟ (ʀᴇᴘʟʏ ᴛᴏ ᴘʜᴏᴛᴏ)\n"
        f"<b>/vt</b> — ᴠɪᴇᴡ ꜱᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ\n"
        f"<b>/dt</b> — ᴅᴇʟᴇᴛᴇ ꜱᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ</blockquote>\n\n"
    )
    admin_cmds = (
        f"<b>➲ ᴏᴡɴᴇʀ ᴄᴏᴍᴍᴀɴᴅꜱ</b>\n"
        f"<blockquote expandable><b>/Authorize</b> — ᴀʟʟᴏᴡ ʙᴏᴛ ᴛᴏ ᴡᴏʀᴋ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ\n"
        f"<b>/unauthorize</b> — ʀᴇᴍᴏᴠᴇ ᴛʜɪꜱ ɢʀᴏᴜᴘ\n"
        f"<b>/authorizedlist</b> — ʟɪꜱᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ɢʀᴏᴜᴘꜱ\n"
        f"<b>/clear</b> — ᴄʟᴇᴀʀ ᴘᴇɴᴅɪɴɢ Qᴜᴇᴜᴇ\n"
        f"<b>/cancel <user_id> —</b> ᴄᴀɴᴄᴇʟ ᴀɴʏ ᴜꜱᴇʀ ᴛᴀꜱᴋ\n"
        f"<b>/list</b> — ᴠɪᴇᴡ ꜰᴜʟʟ Qᴜᴇᴜᴇ ʟɪꜱᴛ\n"
        f"<b>/status</b> — ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ & ɪɴꜰᴏ\n"
        f"<b>/ping</b> — ʟᴀᴛᴇɴᴄʏ ᴄʜᴇᴄᴋ\n"
        f"<b>/restart</b> — ʀᴇꜱᴛᴀʀᴛ ʙᴏᴛ</blockquote>\n"
    )
    await msg.reply(user_cmds + (admin_cmds if uid in ADMIN_IDS else ""))
    
