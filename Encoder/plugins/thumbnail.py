import os
from uuid import uuid4

from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.config import THUMB_DIR
from Encoder.utils.database.access_db import db
from Encoder.utils.encoding.thumb import get_user_thumb
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import log_error


@Client.on_message(filters.command("t") & allowed)
async def cmd_setthumb(client, msg: Message):
    target = msg.reply_to_message if msg.reply_to_message else msg
    if not (target and target.photo):
        return
    status = await msg.reply(f"<b>Saving Thumbnail...</b>")
    try:
        uid       = msg.from_user.id
        final_path = os.path.join(THUMB_DIR, f"{uid}.jpg")
        tmp_path   = os.path.join(THUMB_DIR, f"{uid}_{uuid4().hex}.jpg")
        await target.download(file_name=tmp_path)
        with open(tmp_path, "rb") as f:
            data = f.read()
        await db.set_user_thumb(uid, data)
        os.replace(tmp_path, final_path)
        await status.edit(f"<b>Thumbnail Saved Successfully ✅</b>")
    except Exception as e:
        log_error(f"cmd_setthumb: failed to save thumbnail (uid={uid})", e)
        await status.edit(f"<b>❌ Failed in saving</b>")


@Client.on_message(filters.command("dt") & allowed)
async def cmd_delthumb(client, msg: Message):
    uid     = msg.from_user.id
    deleted = False
    for p in [os.path.join(THUMB_DIR, f"{uid}.jpg"), os.path.join(THUMB_DIR, f"auto_{uid}.jpg")]:
        if os.path.exists(p):
            os.remove(p)
            deleted = True
    await db.delete_user_thumb(uid)
    await msg.reply(f"<b>Thumbnail Deleted ✅</b>" if deleted else f"<b>❌ Thumbnail not found</b>")


@Client.on_message(filters.command("vt") & allowed)
async def cmd_viewthumb(client, msg: Message):
    path = await get_user_thumb(msg.from_user.id)
    if not path:
        return await msg.reply(f"<b>❌ Thumbnail not found</b>")
    await msg.reply_photo(path, caption=f"<b>🖼️ Your saved image</b>")
    
