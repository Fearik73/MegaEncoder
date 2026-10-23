import asyncio
import os
import sys
import time

import psutil
from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder import botStartTime
from Encoder.config import DOWNLOAD_DIR, OUTPUT_DIR
from Encoder.utils.display_progress import human_size, uptime_time
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin
from Encoder.utils.tasks.cancel import is_admin
from Encoder.utils.tasks.queue import (
    get_active_uid, get_all_active_groups, group_queue_size,
)


@Client.on_message(filters.command("ping") & allowed)
async def cmd_ping(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    t = time.time()
    m = await msg.reply(f"<b>Pinging...</b>")
    await m.edit(f"**Pong!** `{int((time.time() - t) * 1000)}ms`")


@Client.on_message(filters.command("restart") & allowed)
async def cmd_restart(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    await msg.reply(f"Restarting...")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable, "-m", "Encoder"])


@Client.on_message(filters.command("status") & allowed)
async def cmd_status(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    uptime_str = uptime_time(time.time() - botStartTime)
    active_uid = get_active_uid(msg.chat.id)

    def _disk(path):
        try:
            stat  = os.statvfs(path)
            free  = stat.f_bavail * stat.f_frsize
            total = stat.f_blocks * stat.f_frsize
            return f"{human_size(free)} free / {human_size(total)}"
        except Exception:
            return "N/A"

    disk_str      = _disk("/tmp")
    download_disk = _disk(DOWNLOAD_DIR)
    output_disk   = _disk(OUTPUT_DIR)

    try:
        mem     = psutil.virtual_memory()
        ram_str = f"{human_size(mem.used)} / {human_size(mem.total)} ({mem.percent}%)"
    except Exception:
        ram_str = "N/A"

    try:
        cpu_str = f"{psutil.cpu_percent(interval=0.5)}%"
    except Exception:
        cpu_str = "N/A"

    active_line = f"  —  {active_uid}" if active_uid is not None else ""
    await msg.reply(
        f"<b>➲ ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ</b>\n"
        f"<blockquote><b>ᴜᴘᴛɪᴍᴇ:</b> {uptime_str}</blockquote>\n"
        f"<blockquote><b>ᴛʜɪꜱ ɢʀᴏᴜᴘ ᴀᴄᴛɪᴠᴇ ᴛᴀꜱᴋ:</b> {'1' if active_uid else '0'}{active_line}\n"
        f"<b>ᴛʜɪꜱ ɢʀᴏᴜᴘ Qᴜᴇᴜᴇᴅ ᴊᴏʙꜱ:</b> {group_queue_size(msg.chat.id)}\n"
        f"<b>ɢʀᴏᴜᴘꜱ ᴄᴜʀʀᴇɴᴛʟʏ ᴇɴᴄᴏᴅɪɴɢ:</b> {len(get_all_active_groups())}</blockquote>\n"
        f"<blockquote><b>ʀᴀᴍ:</b> {ram_str}\n"
        f"<b>ᴄᴘᴜ:</b> {cpu_str}</blockquote>\n"
        f"<blockquote><b>ᴛᴍᴘ ᴅɪꜱᴋ:</b> {disk_str}\n"
        f"<b>ᴅᴏᴡɴʟᴏᴀᴅ ᴅɪʀ ᴅɪꜱᴋ:</b> {download_disk}\n"
        f"<b>ᴏᴜᴛᴘᴜᴛ ᴅɪʀ ᴅɪꜱᴋ:</b> {output_disk}</blockquote>"
    )


@Client.on_message(filters.command("logs") & allowed)
async def cmd_log(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    from Encoder import LOG_FILE
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        return await msg.reply(f"<b>❌ No logs recorded yet</b>")
    await client.send_document(
        msg.chat.id,
        LOG_FILE,
        caption=f"<b>Bot Logs</b>",
        reply_to_message_id=msg.id,
               )
