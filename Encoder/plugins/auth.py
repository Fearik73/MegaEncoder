from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.database.access_db import db
from Encoder.utils.helpers import not_admin
from Encoder.utils.tasks.cancel import is_admin


@Client.on_message(filters.command("authorize") & filters.group)
async def cmd_authorize(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    await db.authorize_group(msg.chat.id, title=msg.chat.title)
    await msg.reply(f"<b>✅ This group is now Authorize</b>\n{msg.chat.title} || {msg.chat.id}")


@Client.on_message(filters.command("unauthorize") & filters.group)
async def cmd_unauthorize(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    removed = await db.unauthorize_group(msg.chat.id)
    if removed:
        await msg.reply(f"<b>✅ This group has been Unauthorize</b>")
    else:
        await msg.reply(f"<b>❌ This group was not authorized<b>")


@Client.on_message(filters.command("authorizedlist"))
async def cmd_authorizedlist(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    groups = await db.get_all_authorized_groups()
    if not groups:
        return await msg.reply(f"❗No authorized group yet")
    lines = [f"• {g['_id']} — {g.get('title') or 'Unknown'}" for g in groups]
    await msg.reply(f"<b>ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ɢʀᴏᴜᴘꜱ</b>\n\n" + "\n".join(lines))
