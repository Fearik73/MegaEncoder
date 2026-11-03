import asyncio

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin, safe_edit
from Encoder.utils.ocr import ui
from Encoder.utils.tasks.cancel import is_admin
from Encoder.utils.tasks.queue import (
    enqueue, group_queue_size, group_queue_worker, is_group_active, is_worker_running,
)


_VIDEO_WAIT_TIMEOUT = 60

# uid -> {"step": "video" | "start" | "end", "msg", "prompt", "start", "timer"}
_sessions: dict[int, dict] = {}

SKIP_KB = InlineKeyboardMarkup([[InlineKeyboardButton("ꜱᴋɪᴘ", callback_data="ocr_skip")]])


def _drop(uid: int):
    s = _sessions.pop(uid, None)
    if s and s.get("timer"):
        s["timer"].cancel()


async def _expire(uid: int, session: dict):
    await asyncio.sleep(_VIDEO_WAIT_TIMEOUT)
    if _sessions.get(uid) is session and session["step"] == "video":
        _sessions.pop(uid, None)
        await safe_edit(session["prompt"], ui.expired())


@Client.on_message(filters.command("ocr") & allowed)
async def cmd_ocr(client, msg: Message):
    if not msg.from_user:
        return
    uid = msg.from_user.id
    if not is_admin(uid):
        return await not_admin(msg)
    _drop(uid)
    prompt  = await msg.reply(ui.wait_video())
    session = {"step": "video", "msg": None, "prompt": prompt, "start": None, "timer": None}
    session["timer"] = asyncio.create_task(_expire(uid, session))
    _sessions[uid] = session


def _in_step(*steps):
    def check(_, __, m):
        s = _sessions.get(m.from_user.id) if m.from_user else None
        return bool(s and s["step"] in steps)
    return filters.create(check)


# --- step 1: video ----------------------------------------------------
@Client.on_message(_in_step("video") & (filters.video | filters.document) & allowed, group=-1)
async def on_ocr_video(client, msg: Message):
    uid = msg.from_user.id
    s   = _sessions[uid]
    if msg.document and not (msg.document.mime_type or "").startswith("video/"):
        await msg.reply(f"<b>❌ That is not a video</b>")
        raise StopPropagation
    if s["timer"]:
        s["timer"].cancel()
        s["timer"] = None
    s["msg"]  = msg
    s["step"] = "start"
    await safe_edit(s["prompt"], ui.ask_time("start", None), reply_markup=SKIP_KB)
    raise StopPropagation


# --- step 2/3: start and end time -------------------------------------
@Client.on_message(
    _in_step("start", "end") & filters.text & ~filters.command(["ocr"]) & allowed, group=-1,
)
async def on_ocr_time(client, msg: Message):
    uid = msg.from_user.id
    if (msg.text or "").startswith("/"):
        return
    s = _sessions[uid]
    t = ui.parse_time(msg.text)
    if t is None:
        await safe_edit(
            s["prompt"],
            ui.ask_time(s["step"], s["start"], "❌ wrong format, use HH:MM:SS, for example 00:02:35"),
            reply_markup=SKIP_KB,
        )
    else:
        await _advance(client, uid, t)
    raise StopPropagation


@Client.on_callback_query(filters.regex(r"^ocr_skip$"))
async def on_ocr_skip(client, cq: CallbackQuery):
    uid = cq.from_user.id
    s   = _sessions.get(uid)
    if not s or s["step"] not in ("start", "end") or s["prompt"].id != cq.message.id:
        return await cq.answer("Expired. Send /ocr again.", show_alert=True)
    await cq.answer()
    await _advance(client, uid, None)


async def _advance(client, uid: int, value):
    s = _sessions[uid]
    if s["step"] == "start":
        s["start"] = value
        s["step"]  = "end"
        return await safe_edit(s["prompt"], ui.ask_time("end", s["start"]), reply_markup=SKIP_KB)

    if value is not None and s["start"] and value <= s["start"]:
        return await safe_edit(
            s["prompt"],
            ui.ask_time("end", s["start"], "❌ end time must be after the start time"),
            reply_markup=SKIP_KB,
        )

    _sessions.pop(uid, None)
    msg      = s["msg"]
    group_id = msg.chat.id
    was_queued = is_group_active(group_id) or group_queue_size(group_id) > 0
    queue_pos  = group_queue_size(group_id) + (1 if is_group_active(group_id) else 0) + 1

    await safe_edit(
        s["prompt"],
        ui.queued(s["start"], value, queue_pos) if was_queued else f"<b>ꜱᴛᴀʀᴛɪɴɢ...</b>",
    )
    job = {
        "kind": "ocr", "msg": msg, "src_msg": msg, "uid": uid,
        "status_msg": s["prompt"], "was_queued": was_queued,
        "t_start": s["start"] or 0.0, "t_end": value,
    }
    await enqueue(group_id, job)

    if not is_worker_running(group_id):
        asyncio.ensure_future(group_queue_worker(client, group_id))
