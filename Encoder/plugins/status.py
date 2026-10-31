import asyncio
import os
import platform
import shutil
import sys
import time

import psutil
from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.raw.functions import Ping
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from Encoder import botStartTime
from Encoder.config import DOWNLOAD_DIR
from Encoder.utils import bandwidth
from Encoder.utils.database.access_db import db
from Encoder.utils.display_progress import human_size, uptime_time
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin
from Encoder.utils.tasks.cancel import is_admin
from Encoder.utils.tasks.queue import (
    get_active_kind, get_active_uid, group_queue_size, list_waiting,
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


_KIND = {"encode": "ᴇɴᴄᴏᴅᴇ", "addsub": "ᴀᴅᴅꜱᴜʙ", "extractsub": "ᴇxᴛʀᴀᴄᴛꜱᴜʙ"}

psutil.cpu_percent(None)


def _disk(path):
    try:
        u = shutil.disk_usage(path)
    except Exception:
        u = shutil.disk_usage("/")
    return f"{human_size(u.free)} free / {human_size(u.total)}"


def _os_name():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return platform.system()


def _status_kb(uid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⟳ ʀᴇꜰʀᴇꜱʜ", callback_data=f"st|{uid}|home"),
        InlineKeyboardButton("📋 ǫᴜᴇᴜᴇ", callback_data=f"st|{uid}|queue"),
    ]])


def _queue_kb(uid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◂ ʙᴀᴄᴋ", callback_data=f"st|{uid}|home"),
        InlineKeyboardButton("⟲ ʀᴇꜰʀᴇꜱʜ", callback_data=f"st|{uid}|queue"),
    ]])


async def _ping(client):
    try:
        t = time.time()
        await client.invoke(Ping(ping_id=0))
        return f"{int((time.time() - t) * 1000)}ms"
    except Exception:
        return "N/A"


async def build_status(client, chat_id: int) -> str:
    psutil.cpu_percent(None)
    ping = await _ping(client)
    srx, stx = await bandwidth.speed()

    cpu = psutil.cpu_percent(None)
    cores = psutil.cpu_count() or 0
    try:
        load = " / ".join(f"{x:.1f}" for x in os.getloadavg())
    except Exception:
        load = "N/A"
    mem  = psutil.virtual_memory()
    swap = psutil.swap_memory()
    proc = psutil.Process()
    try:
        bot_ram = human_size(proc.memory_info().rss)
        ff = sum(1 for c in proc.children(recursive=True) if "ffmpeg" in (c.name() or ""))
    except Exception:
        bot_ram, ff = "N/A", 0

    sess_rx, sess_tx = bandwidth.session_totals()
    srv_rx, srv_tx   = bandwidth.read()
    m_rx, m_tx       = await db.get_bandwidth(bandwidth.month_key())

    kind   = get_active_kind(chat_id)
    active = f"1 — {_KIND.get(kind, str(kind).upper())}" if get_active_uid(chat_id) is not None else "0"

    return (
        f"<b>➲ ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ</b>\n\n"
        f"┌ <b>ꜱᴇʀᴠᴇʀ</b>\n"
        f"│ ᴜᴘᴛɪᴍᴇ: {uptime_time(time.time() - psutil.boot_time())}\n"
        f"│ ʙᴏᴛ ᴜᴘᴛɪᴍᴇ: {uptime_time(time.time() - botStartTime)}\n"
        f"│ ᴏꜱ: {_os_name()}\n"
        f"└ ᴘɪɴɢ: {ping}\n\n"
        f"┌ <b>ʀᴇꜱᴏᴜʀᴄᴇꜱ</b>\n"
        f"│ ᴄᴘᴜ: {cpu}% ({cores} cores)\n"
        f"│ ʟᴏᴀᴅ: {load}\n"
        f"│ ʀᴀᴍ: {human_size(mem.used)} / {human_size(mem.total)} ({mem.percent}%)\n"
        f"│ ꜱᴡᴀᴘ: {human_size(swap.used)} / {human_size(swap.total)}\n"
        f"│ ʙᴏᴛ ʀᴀᴍ: {bot_ram}\n"
        f"└ ᴅɪꜱᴋ: {_disk(DOWNLOAD_DIR)}\n\n"
        f"┌ <b>ʙᴀɴᴅᴡɪᴅᴛʜ</b>\n"
        f"│ ꜱᴘᴇᴇᴅ: ↓ {human_size(srx)}/s  ↑ {human_size(stx)}/s\n"
        f"│ ʙᴏᴛ ꜱᴇꜱꜱɪᴏɴ: ↓ {human_size(sess_rx)}  ↑ {human_size(sess_tx)}\n"
        f"│ ᴛʜɪꜱ ᴍᴏɴᴛʜ: ↓ {human_size(m_rx)}  ↑ {human_size(m_tx)}\n"
        f"└ ꜱᴇʀᴠᴇʀ ᴛᴏᴛᴀʟ: ↓ {human_size(srv_rx)}  ↑ {human_size(srv_tx)}\n\n"
        f"┌ <b>ᴛᴀꜱᴋꜱ</b>\n"
        f"│ ᴀᴄᴛɪᴠᴇ: {active}\n"
        f"│ ǫᴜᴇᴜᴇ: {group_queue_size(chat_id)}\n"
        f"└ ꜰꜰᴍᴘᴇɢ ᴘʀᴏᴄᴇꜱꜱ: {ff}"
    )


def build_queue(chat_id: int) -> str:
    def _u(uid):
        return f'<a href="tg://user?id={uid}">{uid}</a>'

    lines = ["<b>➲ ǫᴜᴇᴜᴇ</b>", ""]
    auid = get_active_uid(chat_id)
    lines.append("┌ <b>ɴᴏᴡ ʀᴜɴɴɪɴɢ</b>")
    if auid is None:
        lines.append("└ ɴᴏᴛʜɪɴɢ")
    else:
        k = get_active_kind(chat_id)
        lines.append(f"└ {_KIND.get(k, str(k).upper())} — {_u(auid)}")
    lines.append("")
    waiting = list_waiting(chat_id)
    lines.append(f"┌ <b>ᴡᴀɪᴛɪɴɢ ({len(waiting)})</b>")
    if not waiting:
        lines.append("└ ǫᴜᴇᴜᴇ ɪꜱ ᴇᴍᴘᴛʏ")
    else:
        for i, (k, uid) in enumerate(waiting, 1):
            lead = "└" if i == len(waiting) else "│"
            lines.append(f"{lead} {i}. {_KIND.get(k, str(k).upper())} — {_u(uid)}")
    return "\n".join(lines)


@Client.on_message(filters.command("status") & allowed)
async def cmd_status(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    await msg.reply(await build_status(client, msg.chat.id), reply_markup=_status_kb(msg.from_user.id))


@Client.on_callback_query(filters.regex(r"^st\|"))
async def status_callback(client, cq):
    if not is_admin(cq.from_user.id):
        return await cq.answer("Admins only", show_alert=True)
    try:
        _, owner, page = cq.data.split("|", 2)
        owner = int(owner)
    except ValueError:
        return await cq.answer()
    chat_id = cq.message.chat.id
    if page == "queue":
        text, kb = build_queue(chat_id), _queue_kb(owner)
    else:
        text, kb = await build_status(client, chat_id), _status_kb(owner)
    try:
        await cq.message.edit(text, reply_markup=kb, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except Exception as e:
        print(f"[status] edit failed: {e!r}")
    await cq.answer()


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
    
