import asyncio
import html
from math import ceil

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from Encoder.utils.database.access_db import db
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import not_admin, safe_edit
from Encoder.utils.ocr import config as ocfg
from Encoder.utils.tasks.cancel import is_admin


PER_PAGE      = 10
EDIT_TIMEOUT  = 60

# (chat_id, uid) -> {"key", "page", "msg", "timer"}
_editing: dict[tuple[int, int], dict] = {}


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def _hint(key: str) -> str:
    _, kind, rule, _ = ocfg.VARS[key]
    if kind in ("int", "float"):
        return f"{rule[0]} - {rule[1]}"
    if kind == "choice":
        return " / ".join(rule)
    return "text"


# --- screens ----------------------------------------------------------
def _main():
    text = "<b>OCR Settings:</b>"
    kb = InlineKeyboardMarkup([
        [_btn("Config Variables", "os|vars|0")],
        [_btn("Close", "os|close")],
    ])
    return text, kb


def _vars(page: int):
    keys  = sorted(ocfg.VARS)
    pages = ceil(len(keys) / PER_PAGE)
    page  = min(max(page, 0), pages - 1)
    chunk = keys[page * PER_PAGE:(page + 1) * PER_PAGE]

    rows = []
    for i in range(0, len(chunk), 2):
        rows.append([_btn(k, f"os|var|{k}|{page}") for k in chunk[i:i + 2]])
    rows.append([_btn("Back", "os|menu"), _btn("Close", "os|close")])
    nums = [_btn(str(i + 1), f"os|vars|{i}") for i in range(pages)] if pages > 1 else []
    for i in range(0, len(nums), 8):
        rows.append(nums[i:i + 8])

    return f"<b>Config Variables</b> | <b>Page: {page + 1}</b>", InlineKeyboardMarkup(rows)


def _var(key: str, page: int, editing: bool = False):
    value = html.escape(str(getattr(ocfg, key)))
    if editing:
        text = (
            f"<b>Send a valid value for</b> <code>{key}</code>\n"
            f"<b>Allowed:</b> {_hint(key)}\n"
            f"<b>Current value:</b> <code>{value}</code>\n\n"
            f"<i>Timeout: {EDIT_TIMEOUT}s</i>"
        )
        first = _btn("Stop Edit", f"os|stop|{key}|{page}")
    else:
        text = (
            f"<b>Variable:</b> <code>{key}</code>\n\n"
            f"<b>Description:</b> {ocfg.VARS[key][3]}\n\n"
            f"<b>Value:</b> <code>{value}</code>\n"
            f"<b>Default:</b> <code>{html.escape(str(ocfg.ENV[key]))}</code>"
        )
        if key in ocfg.RESTART_VARS:
            text += "\n\n<b>Note:</b> Restart required for this edit to take effect!"
        first = _btn("Edit Value", f"os|edit|{key}|{page}")
    kb = InlineKeyboardMarkup([
        [first, _btn("Reset", f"os|reset|{key}|{page}")],
        [_btn("Back", f"os|vars|{page}"), _btn("Close", "os|close")],
    ])
    return text, kb


# --- edit-mode bookkeeping --------------------------------------------
def _stop_edit(chat_id: int, uid: int):
    st = _editing.pop((chat_id, uid), None)
    if st and st.get("timer"):
        st["timer"].cancel()
    return st


async def _edit_timeout(chat_id: int, uid: int, st: dict):
    await asyncio.sleep(EDIT_TIMEOUT)
    if _editing.get((chat_id, uid)) is st:
        _editing.pop((chat_id, uid), None)
        text, kb = _var(st["key"], st["page"])
        await safe_edit(st["msg"], text, reply_markup=kb)


# --- command ----------------------------------------------------------
@Client.on_message(filters.command(["osetting", "os"]) & allowed)
async def cmd_osetting(client, msg: Message):
    if not msg.from_user:
        return
    if not is_admin(msg.from_user.id):
        return await not_admin(msg)
    text, kb = _main()
    await msg.reply(text, reply_markup=kb)


# --- buttons ----------------------------------------------------------
@Client.on_callback_query(filters.regex(r"^os\|"))
async def on_os_button(client, cq: CallbackQuery):
    uid     = cq.from_user.id
    msg     = cq.message
    chat_id = msg.chat.id
    if not is_admin(uid):
        return await cq.answer("Not for you!", show_alert=True)

    parts  = cq.data.split("|")
    action = parts[1]
    _stop_edit(chat_id, uid)

    if action == "close":
        await cq.answer()
        for m in (msg, msg.reply_to_message):
            try:
                if m:
                    await m.delete()
            except Exception:
                pass
        return

    if action == "menu":
        text, kb = _main()
    elif action == "vars":
        text, kb = _vars(int(parts[2]))
    else:
        key, page = parts[2], int(parts[3])
        if key not in ocfg.VARS:
            return await cq.answer("Unknown variable.", show_alert=True)
        if action == "edit":
            st = {"key": key, "page": page, "msg": msg, "timer": None}
            st["timer"] = asyncio.create_task(_edit_timeout(chat_id, uid, st))
            _editing[(chat_id, uid)] = st
            text, kb = _var(key, page, editing=True)
        elif action == "reset":
            try:
                await db.unset_ocr_config(key)
            except Exception as e:
                return await cq.answer(f"Reset failed: {e}", show_alert=True)
            ocfg.reset_value(key)
            await cq.answer("Reset Done!", show_alert=True)
            text, kb = _var(key, page)
            return await safe_edit(msg, text, reply_markup=kb)
        else:  # "var" and "stop"
            text, kb = _var(key, page)

    await cq.answer()
    await safe_edit(msg, text, reply_markup=kb)


# --- value typed by the admin -----------------------------------------
def _pending(_, __, m):
    return bool(
        m.from_user and m.text and not m.text.startswith("/")
        and (m.chat.id, m.from_user.id) in _editing
    )


@Client.on_message(filters.create(_pending) & allowed, group=-1)
async def on_os_value(client, msg: Message):
    chat_id, uid = msg.chat.id, msg.from_user.id
    st  = _editing[(chat_id, uid)]
    key = st["key"]
    try:
        value = ocfg.parse(key, msg.text)
    except ValueError as e:
        await msg.reply(f"<b>❌ {html.escape(str(e))}</b>")
        raise StopPropagation

    try:
        await db.set_ocr_config(key, value)
    except Exception as e:
        await msg.reply(f"<b>❌ Could not save:</b> <code>{html.escape(str(e))}</code>")
        raise StopPropagation

    ocfg.set_value(key, value)
    _stop_edit(chat_id, uid)
    try:
        await msg.delete()
    except Exception:
        pass
    text, kb = _var(key, st["page"])
    await safe_edit(st["msg"], text, reply_markup=kb)
    raise StopPropagation
