import asyncio
import base64

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from Encoder.config import ADMIN_IDS
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin
from Encoder.utils.tasks.cancel import cancel_task, find_task_id, is_admin
from Encoder.utils.tasks.queue import (
    _group_pending, _queues, get_active_uid, get_all_active_groups,
)


# Cancel confirmation flow
@Client.on_callback_query(filters.regex(r"^cancel_ask_(\d+)_(\d+)$"))
async def on_cancel_ask(client, cq: CallbackQuery):
    uid          = cq.from_user.id
    task_id      = int(cq.data.split("_")[2])
    requester_uid = int(cq.data.split("_")[3])
    if uid != requester_uid and uid not in ADMIN_IDS:
        return await cq.answer(f"❗This is not your task!", show_alert=True)
    await cq.answer()
    confirm_msg = await cq.message.reply(
        f"<b>ʀᴇᴀʟʟʏ! ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄᴀɴᴄᴇʟ ᴛʜɪꜱ ᴛᴀꜱᴋ?</b>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes", callback_data=f"cancel_yes_{task_id}_{requester_uid}"),
            InlineKeyboardButton("❌ No",  callback_data=f"cancel_no_{task_id}_{requester_uid}"),
        ]])
    )
    await asyncio.sleep(30)
    try:
        await confirm_msg.delete()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^cancel_yes_(\d+)_(\d+)$"))
async def on_cancel_yes(client, cq: CallbackQuery):
    uid          = cq.from_user.id
    task_id      = int(cq.data.split("_")[2])
    requester_uid = int(cq.data.split("_")[3])
    if uid != requester_uid and uid not in ADMIN_IDS:
        return await cq.answer(f"❗This is not your task!", show_alert=True)
    cancel_task(task_id)
    await cq.answer(f"✅ Cancelled!")
    try:
        await cq.message.delete()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^cancel_no_(\d+)_(\d+)$"))
async def on_cancel_no(client, cq: CallbackQuery):
    uid          = cq.from_user.id
    requester_uid = int(cq.data.split("_")[3])
    if uid != requester_uid and uid not in ADMIN_IDS:
        return await cq.answer(f"❗This is not your task!", show_alert=True)
    await cq.answer(f"<b>Continuing task...</b>")
    try:
        await cq.message.delete()
    except Exception:
        pass


# /Cancel_<token> command
@Client.on_message(filters.regex(r"^/Cancel_([A-Za-z0-9_-]+)(?:@(\w+))?$") & filters.group)
async def on_cancel_cmd(client, msg):
    if not is_admin(msg.from_user.id):
        return

    match       = msg.matches[0]
    token       = match.group(1)
    cmd_botname = match.group(2)

    try:
        padded     = token + "=" * (-len(token) % 4)
        target_idx = int(base64.urlsafe_b64decode(padded).decode()) - 1
    except Exception:
        return

    if cmd_botname:
        me = await client.get_me()
        if me.username and cmd_botname.lower() != me.username.lower():
            return

    group_id = msg.chat.id
    q = _queues.get(group_id)
    jobs    = []
    removed = False
    if q:
        while not q.empty():
            try:
                jobs.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break

    for i, job in enumerate(jobs):
        if not removed and i == target_idx:
            _group_pending[group_id] = max(0, _group_pending.get(group_id, 0) - 1)
            removed = True
        elif q is not None:
            q.put_nowait(job)

    if removed:
        await msg.reply(f"<b>✅ Task removed from queue</b>")

# Active encode/upload task first while u use /cancel after that leeching 
def _cancel_target(g):
    _stages = ("downloading", "encoding", "uploading")
    active_uid = get_active_uid(g)
    tid = find_task_id(g, uid=active_uid, stages=_stages) if active_uid is not None else None
    if tid is None:
        tid = find_task_id(g, stages=("leeching",))
    return tid


@Client.on_message(filters.command("cancel") & allowed)
async def cmd_cancel_any(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    parts    = msg.text.split()
    group_id = msg.chat.id
    _ACTIVE_STAGES = ("downloading", "encoding", "uploading")

    if len(parts) == 1:
        task_id = _cancel_target(group_id)
        if task_id is None:
            return await msg.reply(f"<b>❗ɴᴏ ᴀᴄᴛɪᴠᴇ ᴛᴀꜱᴋ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ ʀɪɢʜᴛ ɴᴏᴡ</b>")
        cancel_task(task_id)
        return await msg.reply(f"<b>✅ ᴛᴀꜱᴋ ᴄᴀɴᴄᴇʟʟᴇᴅ ꜰᴏʀ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>")

    if parts[1].lower() == "all":
        active_groups = get_all_active_groups()
        if not active_groups:
            return await msg.reply(f"<b>❗ɴᴏ ᴀᴄᴛɪᴠᴇ ᴛᴀꜱᴋꜱ ʀɪɢʜᴛ ɴᴏᴡ</b>")
        for g in active_groups:
            active_uid = get_active_uid(g)
            task_id = find_task_id(g, uid=active_uid, stages=_ACTIVE_STAGES) if active_uid is not None else None
            if task_id is not None:
                cancel_task(task_id)
        lines = ", ".join(f"{g}" for g in active_groups)
        return await msg.reply(f"✅ ᴄᴀɴᴄᴇʟʟᴇᴅ ᴀʟʟ ᴀᴄᴛɪᴠᴇ ᴛᴀꜱᴋꜱ ᴀᴄʀᴏꜱꜱ ɢʀᴏᴜᴘꜱ — {lines}")

    if not parts[1].lstrip("-").isdigit():
        return await msg.reply(f"<b>❌ Invalid group ID.</b>")
    target_group = int(parts[1])
    task_id = _cancel_target(target_group)
    if task_id is None:
        return await msg.reply(f"<b>❗ɴᴏ ᴀᴄᴛɪᴠᴇ ᴛᴀꜱᴋ ꜰᴏᴜɴᴅ ꜰᴏʀ ɢʀᴏᴜᴘ {target_group}</b>")
    cancel_task(task_id)
    await msg.reply(f"<b>✅ ᴛᴀꜱᴋ ᴄᴀɴᴄᴇʟʟᴇᴅ ꜰᴏʀ ɢʀᴏᴜᴘ {target_group}</b>")
