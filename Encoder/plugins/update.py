from html import escape

from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin
from Encoder.utils.tasks.cancel import is_admin
from Encoder.utils.updater import update_from_upstream


@Client.on_message(filters.command("update") & allowed)
async def cmd_update(client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    status_msg = await msg.reply("♻️ Checking for updates...")
    status, text = await update_from_upstream()
    if status == "updated":
        text = f"✅ <b>Updated</b>\n<pre>{escape(text)}</pre>\nRestart the bot to apply new commits"
    elif status == "uptodate":
        text = f"✅ {escape(text)}"
    else:
        text = f"❌ <b>Update failed</b>\n<pre>{escape(text)}</pre>"
    await status_msg.edit_text(text)
