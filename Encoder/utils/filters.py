from pyrogram import filters, enums

from Encoder.config import ADMIN_IDS
from Encoder.utils.database.access_db import db


# Group + admin authorization filter
async def _allowed_chat(_, __, msg):
    if msg.from_user:
        uid = msg.from_user.id
    elif msg.sender_chat:
        uid = None
    else:
        return False

    if msg.chat.type == enums.ChatType.PRIVATE:
        return False

    if uid in ADMIN_IDS:
        return True

    if msg.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return await db.is_group_authorized(msg.chat.id)

    return False


allowed = filters.create(_allowed_chat)
