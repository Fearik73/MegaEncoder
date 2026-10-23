import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.filters import allowed
from Encoder.utils.helpers import safe_reply
from Encoder.utils.tasks.queue import (
    enqueue, group_queue_size, group_queue_worker, is_group_active, is_worker_running,
)


_batch_sessions: dict[int, list] = {}


@Client.on_message(filters.command("compress") & allowed)
async def cmd_compress(client, msg: Message):
    target = msg.reply_to_message
    if not target:
        return
    file = target.video or target.document
    if not file:
        return
    if target.document:
        mime = target.document.mime_type or ""
        if not mime.startswith("video/"):
            return

    uid        = msg.from_user.id
    source_uid = target.from_user.id if target.from_user else uid
    group_id   = msg.chat.id
    was_queued = is_group_active(group_id) or group_queue_size(group_id) > 0
    queue_pos  = group_queue_size(group_id) + (1 if is_group_active(group_id) else 0) + 1

    status_msg = await safe_reply(
        msg,
        f"<b>ᴀᴅᴅᴇᴅ ᴛᴏ Qᴜᴇᴜᴇ #{queue_pos}</b>\n"
        f"<b>ʏᴏᴜʀ ᴇɴᴄᴏᴅᴇ ᴡɪʟʟ ꜱᴛᴀʀᴛ ᴡʜᴇɴ ɪᴛꜱ ᴛᴜʀɴ ᴄᴏᴍᴇꜱ</b>"
    )
    job = {
        "msg": target, "file": file, "compress_uid": source_uid,
        "status_msg": status_msg, "was_queued": was_queued,
    }
    await enqueue(group_id, job)

    if not is_worker_running(group_id):
        asyncio.ensure_future(group_queue_worker(client, group_id))


@Client.on_message(filters.command("batch") & allowed)
async def cmd_batch(client, msg: Message):
    uid = msg.from_user.id
    _batch_sessions[uid] = []
    await msg.reply(
        f"<b>➲ <u>ʙᴀᴛᴄʜ ᴍᴏᴅᴇ ᴏɴ</u></b>\n\n"
        f"<i>ɴᴏᴡ ꜱᴇɴᴅ ᴀʟʟ ʏᴏᴜʀ ᴠɪᴅᴇᴏꜱ ᴏɴᴇ ʙʏ ᴏɴᴇ\n"
        f"ᴡʜᴇɴ ᴅᴏɴᴇ, ᴛʏᴘᴇ /done ᴛᴏ Qᴜᴇᴜᴇ ᴛʜᴇᴍ ᴀʟʟ</i>"
    )


@Client.on_message(filters.command("done") & allowed)
async def cmd_done(client, msg: Message):
    uid      = msg.from_user.id
    group_id = msg.chat.id
    batch = _batch_sessions.pop(uid, None)
    if batch is None:
        return await msg.reply(f"<b>➲ ᴜꜱᴇ /batch ꜰɪʀꜱᴛ")
    if not batch:
        return await msg.reply(f"<b>➲ ꜰɪʀꜱᴛ ᴀᴅᴅ ꜱᴏᴍᴇ ᴠɪᴅᴇᴏꜱ ɪɴ ʙᴀᴛᴄʜ")
    count = 0
    for job in batch:
        await enqueue(group_id, job)
        count += 1
    if not is_worker_running(group_id):
        asyncio.ensure_future(group_queue_worker(client, group_id))
    await msg.reply(
        f"<b>➲ ʙᴀᴛᴄʜ Qᴜᴇᴜᴇᴅ!</b>\n"
        f"<b>{count}</b> ᴠɪᴅᴇᴏꜱ ᴀᴅᴅᴇᴅ ᴛᴏ Qᴜᴇᴜᴇ"
    )


# Incoming video/document — batch collect or auto-queue
@Client.on_message(filters.video & allowed)
async def on_video(client, msg: Message):
    uid  = msg.from_user.id
    file = msg.video or msg.document
    if not file:
        return

    if uid in _batch_sessions:
        _batch_sessions[uid].append({"msg": msg, "file": file})
        n = len(_batch_sessions[uid])
        await msg.reply(f"✅ ᴠɪᴅᴇᴏ #{n} ᴀᴅᴅᴇᴅ ᴛᴏ ʙᴀᴛᴄʜ")


@Client.on_message(filters.document & allowed)
async def on_document_batch(client, msg: Message):
    uid  = msg.from_user.id
    file = msg.document
    if not file:
        return
    mime = file.mime_type or ""
    if not mime.startswith("video/"):
        return

    if uid in _batch_sessions:
        _batch_sessions[uid].append({"msg": msg, "file": file})
        n = len(_batch_sessions[uid])
        await msg.reply(f"✅ ᴠɪᴅᴇᴏ #{n} ᴀᴅᴅᴇᴅ ᴛᴏ ʙᴀᴛᴄʜ")
