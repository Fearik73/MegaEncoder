import re, asyncio, traceback
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import FloodWait, RPCError

def log_error(context: str, exc: Exception):
    print(f"[ERROR] {context}: {exc!r}")
    traceback.print_exc()

async def safe_reply(msg, text: str, **kwargs):
    for attempt in range(3):
        try:
            return await msg.reply(text, **kwargs)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
        except RPCError as e:
            if "RANDOM_ID_DUPLICATE" in str(e) and attempt < 2:
                await asyncio.sleep(1)
                continue
            raise

def cancel_button(task_id: int, requester_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("𝗖𝗔𝗡𝗖𝗘𝗟", callback_data=f"cancel_ask_{task_id}_{requester_uid}")
    ]])


async def safe_edit(msg, text: str, reply_markup=None):
    try:
        await msg.edit(text, reply_markup=reply_markup)
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await msg.edit(text, reply_markup=reply_markup)
        except Exception:
            pass
    except Exception:
        pass

def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>"/\\|?*\x00-\x1f]', "_", name).strip()

async def not_admin(msg: Message):
    await msg.reply("Why Bro 🙂") # non admin 🥹
