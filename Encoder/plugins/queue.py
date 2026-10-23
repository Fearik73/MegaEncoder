import base64

from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin
from Encoder.utils.tasks.cancel import is_admin
from Encoder.utils.tasks.queue import (
    _queues, clear_queue, get_active_uid, group_pending, group_queue_size,
    is_group_active,
)


@Client.on_message(filters.command("queue") & allowed)
async def cmd_queue(client, msg: Message):
    uid        = msg.from_user.id
    group_id   = msg.chat.id
    my_pending = group_pending(group_id)
    active_uid = get_active_uid(group_id)
    if active_uid == uid:
        status_str = "⚙️ " + "Eɴᴄᴏᴅɪɴɢ"
    elif is_group_active(group_id) or my_pending > 0:
        status_str = "⏳ " + "Wᴀɪᴛɪɴɢ ɪɴ Qᴜᴇᴜᴇ"
    else:
        status_str = "BaBa Tillu"
    await msg.reply(
        f"<b>➲ <u>Qᴜᴇᴜᴇ ꜱᴛᴀᴛᴜꜱ</u></b>\n\n"
        f"<b>ʏᴏᴜʀ ꜱᴛᴀᴛᴜꜱ:</b> {status_str}\n"
        f"<b>ᴘᴇɴᴅɪɴɢ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ:</b> {my_pending}\n"
        f"<b>ᴛᴏᴛᴀʟ ɪɴ Qᴜᴇᴜᴇ:</b> {group_queue_size(group_id)}"
    )


@Client.on_message(filters.command("list") & allowed)
async def cmd_list(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    group_id   = msg.chat.id
    active_uid = get_active_uid(group_id)
    lines      = []

    if active_uid is not None:
        try:
            chat = await client.get_users(active_uid)
            name = f"@{chat.username}" if chat.username else chat.first_name
        except Exception:
            name = str(active_uid)
        lines.append(f"⚙️ **ᴀᴄᴛɪᴠᴇ** — {name} ({active_uid})")

    q = _queues.get(group_id)
    jobs = list(q._queue) if q else []
    if not jobs and active_uid is None:
        return await msg.reply(f"<b>❗Qᴜᴇᴜᴇ ɪꜱ ᴇᴍᴘᴛʏ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>")

    for i, job in enumerate(jobs, start=1):
        job_uid  = job["msg"].from_user.id
        try:
            chat = await client.get_users(job_uid)
            mention = f"[{chat.first_name}](tg://user?id={job_uid})"
        except Exception:
            mention = str(job_uid)
        token = base64.urlsafe_b64encode(str(i).encode()).decode().rstrip("=")
        lines.append(
            f"**#{i}** — {mention}\n"
            f"/Cancel_{token}"
        )

    text = "\n\n".join(lines)
    await msg.reply(f"<b>Qᴜᴇᴜᴇ ʟɪꜱᴛ </b>➲ \n\n{text}")


@Client.on_message(filters.command("clear") & allowed)
async def cmd_cq(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    cleared = clear_queue(msg.chat.id)
    await msg.reply(f"<b>✅ Qᴜᴇᴜᴇ ᴄʟᴇᴀʀᴇᴅ — {cleared} ᴊᴏʙꜱ ʀᴇᴍᴏᴠᴇᴅ</b>")
