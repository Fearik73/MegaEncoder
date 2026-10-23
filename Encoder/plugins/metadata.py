from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.database.access_db import db
from Encoder.utils.filters import allowed


@Client.on_message(filters.command("metadata") & allowed)
async def cmd_metadata(client, msg: Message):
    uid = msg.from_user.id

    if len(msg.command) > 1:
        value = msg.text.split(" ", 1)[1]
        await db.set_metadata_field(uid, "title", value)
        await db.set_metadata_field(uid, "author", value)
        await db.set_metadata_field(uid, "artist", value)
        await db.set_metadata_field(uid, "audio", value)
        await db.set_metadata_field(uid, "subtitle", value)
        await db.set_metadata_field(uid, "video", value)
        await db.set_metadata_status(uid, "On")
        return await msg.reply(f"**✅ Metadata Saved: **{value}")
