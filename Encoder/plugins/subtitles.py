import asyncio
import os

from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.config import DOWNLOAD_DIR
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import safe_edit, safe_reply, sanitize_filename
from Encoder.utils.subtitles.subtitles_utils import (
    detect_language, is_xsub_active, mark_xsub_active, mark_xsub_done, SUB_EXTS,
)
from Encoder.utils.tasks.queue import (
    enqueue, group_queue_size, group_queue_worker, is_group_active, is_worker_running,
)


_sub_sessions: dict[int, dict] = {}


_xsub_waiting: dict[int, Message] = {}


_VIDEO_WAIT_TIMEOUT = 60


def _build_sub_status_text(subs: list) -> str:
    lines = [f"<b>➲ <u>ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ʀᴇᴄᴇɪᴠᴇᴅ ꜱᴜʙᴛɪᴛʟᴇ ꜰɪʟᴇ</u></b>\n", f"<b>ᴛᴏᴛᴀʟ ꜱᴜʙᴛɪᴛʟᴇ:</b> {len(subs)}", ""]
    for i, s in enumerate(subs, 1):
        lines.append(f"{i}. {s['name']}")
        lines.append(f"Language: {s['lang']}")
        lines.append("")
    lines.append("<i>_ꜱᴇɴᴅ ᴍᴇ ᴍᴏʀᴇ ꜱᴜʙᴛɪᴛʟᴇꜱ ɪꜰ ᴜ ᴡᴀɴɴᴀ ᴀᴅᴅ. ᴜꜱᴇ /merge ᴡʜᴇɴ ᴅᴏɴᴇ ᴛᴏ ᴍᴇʀɢᴇ ᴛʜᴇᴍ ɪɴᴛᴏ ᴛʜᴇ ᴠɪᴅᴇᴏ_</i>")
    return "\n".join(lines)


async def _sub_timeout(uid: int, session: dict, wait_msg: Message):
    await asyncio.sleep(_VIDEO_WAIT_TIMEOUT)
    if _sub_sessions.get(uid) is session and session["stage"] == "video":
        _sub_sessions.pop(uid, None)
        try:
            await safe_edit(wait_msg, f"<b>❗ꜱᴇᴀꜱᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ</b>\n\n<i>_ɴᴏ ᴠɪᴅᴇᴏ ʀᴇᴄᴇɪᴠᴇᴅ ᴡɪᴛʜɪɴ {_VIDEO_WAIT_TIMEOUT} ꜱᴇᴄᴏɴᴅꜱ</i>")
        except Exception:
            pass


async def _xsub_timeout(uid: int, wait_msg: Message):
    await asyncio.sleep(_VIDEO_WAIT_TIMEOUT)
    if _xsub_waiting.get(uid) is wait_msg:
        _xsub_waiting.pop(uid, None)
        mark_xsub_done(uid)
        try:
            await safe_edit(wait_msg, f"<b>❗ꜱᴇᴀꜱᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ</b>\n\n<i>_ɴᴏ ᴠɪᴅᴇᴏ ʀᴇᴄᴇɪᴠᴇᴅ ᴡɪᴛʜɪɴ {_VIDEO_WAIT_TIMEOUT} ꜱᴇᴄᴏɴᴅꜱ</i>")
        except Exception:
            pass


@Client.on_message(filters.command("addsub") & allowed)
async def cmd_sub(client, msg: Message):
    uid = msg.from_user.id
    if is_xsub_active(uid):
        return await msg.reply(f"⚠️ ꜰɪʀꜱᴛ ʟᴇᴛ ᴛʜᴇ ʙᴏᴛ ꜰɪɴɪꜱʜ ɪᴛ'ꜱ ᴇxᴛʀᴀᴄᴛɪᴏɴ ᴘʀᴏᴄᴇꜱꜱ")
    session = {"stage": "video", "video_msg": None, "prompt_msg": None, "subs": []}
    _sub_sessions[uid] = session
    wait_msg = await msg.reply(f"<b>➲ ꜱᴇɴᴅ ᴍᴇ ᴀ ᴠɪᴅᴇᴏ ꜰɪʟᴇ</b>")
    asyncio.create_task(_sub_timeout(uid, session, wait_msg))


@Client.on_message(filters.command("extractsub") & allowed)
async def cmd_xsub(client, msg: Message):
    uid = msg.from_user.id
    _sub_sessions.pop(uid, None)
    mark_xsub_active(uid)
    wait_msg = await msg.reply(f"<b>➲ ꜱᴇɴᴅ ᴍᴇ ᴀ ᴠɪᴅᴇᴏ ꜰɪʟᴇ</b>")
    _xsub_waiting[uid] = wait_msg
    asyncio.create_task(_xsub_timeout(uid, wait_msg))


sub_active  = filters.create(lambda _, __, m: bool(m.from_user) and m.from_user.id in _sub_sessions)


xsub_active = filters.create(lambda _, __, m: bool(m.from_user) and m.from_user.id in _xsub_waiting)


# --- /sub flow: video, then subtitle files ---------------------------
@Client.on_message(sub_active & (filters.video | filters.document) & allowed)
async def on_sub_media(client, msg: Message):
    uid     = msg.from_user.id
    session = _sub_sessions.get(uid)
    if not session:
        return

    if session["stage"] == "video":
        file = msg.video or msg.document
        if not file:
            return
        if msg.document:
            mime = msg.document.mime_type or ""
            if not mime.startswith("video/"):
                return await msg.reply(f"<b>❌ That is not a video. Send me a video<b>")

        session["video_msg"] = msg
        session["stage"]     = "subs"
        prompt = await msg.reply(
            f"<b>✅ ᴠɪᴅᴇᴏ ʀᴇᴄᴇɪᴠᴇᴅ</b>\n\n"
            f"<i>ɴᴏᴡ ꜱᴇɴᴅ ᴍᴇ ꜱᴜʙᴛɪᴛʟᴇ ꜰɪʟᴇꜱ</i>"
        )
        session["prompt_msg"] = prompt
        return

    if msg.video:
        return await msg.reply(f"<b>❌ Send subtitle files, or use /merge if done</b>")

    doc = msg.document
    if not doc:
        return
    filename = sanitize_filename(doc.file_name or f"subtitle_{len(session['subs']) + 1}.srt")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUB_EXTS:
        return await msg.reply(f"<b>❗ᴜɴꜱᴜᴘᴘᴏʀᴛᴇᴅ ꜱᴜʙᴛɪᴛʟᴇ ꜰᴏʀᴍᴀᴛ</b>")

    dest_dir = os.path.join(DOWNLOAD_DIR, f"sub_{uid}")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{len(session['subs'])}_{filename}")
    try:
        await client.download_media(msg, file_name=dest_path)
    except Exception as e:
        return await msg.reply(f"<b>❌ Failed to download subtitle</b>")

    caption_text = (msg.caption or "").strip()
    lang = detect_language(caption_text) if caption_text else "Unknown"
    if lang == "Unknown":
        lang = detect_language(filename)

    session["subs"].append({"path": dest_path, "name": filename, "lang": lang, "ext": ext.lstrip(".")})

    text = _build_sub_status_text(session["subs"])
    prompt = session.get("prompt_msg")
    if prompt:
        await safe_edit(prompt, text)
    else:
        session["prompt_msg"] = await msg.reply(text)


@Client.on_message(filters.command("merge") & allowed)
async def cmd_esub(client, msg: Message):
    uid     = msg.from_user.id
    session = _sub_sessions.get(uid)
    if not session:
        return await msg.reply(f"<b>➲ ᴜꜱᴇ /addsub ꜰɪʀꜱᴛ</b>")
    if session["stage"] != "subs" or not session.get("video_msg") or not session["subs"]:
        _sub_sessions.pop(uid, None)
        return await msg.reply(f"<b>❗ꜱᴇᴀꜱᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ</b>\n\n<i>_ᴠɪᴅᴇᴏ ᴏʀ ꜱᴜʙᴛɪᴛʟᴇꜱ ᴡᴇʀᴇ ᴍɪꜱꜱɪɴɢ. ᴜꜱᴇ /addsub ᴛᴏ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ_</i>")

    video_msg = session["video_msg"]
    subs      = session["subs"]
    _sub_sessions.pop(uid, None)

    group_id   = msg.chat.id
    was_queued = is_group_active(group_id) or group_queue_size(group_id) > 0
    queue_pos  = group_queue_size(group_id) + (1 if is_group_active(group_id) else 0) + 1

    status_msg = await safe_reply(
        msg,
        f"<b>ᴀᴅᴅᴇᴅ ᴛᴏ Qᴜᴇᴜᴇ #{queue_pos}</b>\n"
        f"ʏᴏᴜʀ ꜱᴜʙᴛɪᴛʟᴇ ᴍᴇʀɢᴇ ᴡɪʟʟ ꜱᴛᴀʀᴛ ᴡʜᴇɴ ɪᴛꜱ ᴛᴜʀɴ ᴄᴏᴍᴇꜱ"
        if was_queued else
        f"<b>ꜱᴛᴀʀᴛɪɴɢ...</b>"
    )
    job = {
        "kind": "addsub", "msg": msg, "video_msg": video_msg, "subs": subs, "uid": uid,
        "status_msg": status_msg, "was_queued": was_queued,
    }
    await enqueue(group_id, job)

    if not is_worker_running(group_id):
        asyncio.ensure_future(group_queue_worker(client, group_id))


# --- /extractsub flow--------------------
@Client.on_message(xsub_active & (filters.video | filters.document) & allowed)
async def on_xsub_video(client, msg: Message):
    uid = msg.from_user.id
    _xsub_waiting.pop(uid, None)

    file = msg.video or msg.document
    if not file:
        mark_xsub_done(uid)
        return
    if msg.document:
        mime = msg.document.mime_type or ""
        if not mime.startswith("video/"):
            mark_xsub_done(uid)
            return await msg.reply(f"<b>❌ That is not a video</b>")

    group_id   = msg.chat.id
    was_queued = is_group_active(group_id) or group_queue_size(group_id) > 0
    queue_pos  = group_queue_size(group_id) + (1 if is_group_active(group_id) else 0) + 1

    status_msg = await safe_reply(
        msg,
        f"<b>ᴀᴅᴅᴇᴅ ᴛᴏ Qᴜᴇᴜᴇ #{queue_pos}</b>\n"
        f"ʏᴏᴜʀ ꜱᴜʙᴛɪᴛʟᴇ ᴇxᴛʀᴀᴄᴛɪᴏɴ ᴡɪʟʟ ꜱᴛᴀʀᴛ ᴡʜᴇɴ ɪᴛꜱ ᴛᴜʀɴ ᴄᴏᴍᴇꜱ"
        if was_queued else
        f"<b>ꜱᴛᴀʀᴛɪɴɢ...</b>"
    )
    job = {
        "kind": "extractsub", "src_msg": msg, "uid": uid,
        "status_msg": status_msg, "was_queued": was_queued,
    }
    await enqueue(group_id, job)

    if not is_worker_running(group_id):
        asyncio.ensure_future(group_queue_worker(client, group_id))
