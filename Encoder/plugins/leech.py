import asyncio
import os
import re
import shutil
import uuid

from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.database.access_db import db
from Encoder.utils.downloads.aria2 import Aria2Job
from Encoder.utils.downloads.link_handler import download_from_link
from Encoder.utils.filters import allowed
from Encoder.utils.helpers import cancel_button, log_error, safe_edit, safe_reply
from Encoder.utils.logs.tasklog import (
    drop_log, send_failure_log, start_log, tfail, tlog,
)
from Encoder.utils.naming import rename_items
from Encoder.utils.tasks.cancel import (
    clear_cancelled, clear_task, is_cancelled, new_task_id, register_task,
)
from Encoder.utils.tasks.encode_job import RES_MAP
from Encoder.utils.tasks.queue import (
    enqueue, get_active_uid, group_queue_size, group_queue_worker, is_worker_running,
)


URL_REGEX = re.compile(r'\S+://\S+|magnet:\S+')


# Link extraction from message/reply chain
def _extract_link_from_text(text):
    if not text:
        return None
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


def _extract_link_from_entities(msg):
    for attr in ("entities", "caption_entities"):
        for ent in getattr(msg, attr, None) or []:
            url = getattr(ent, "url", None)
            if url:
                return url
    return None


def _extract_link_from_message(msg, depth=5):
    seen = msg
    for _ in range(depth):
        if seen is None:
            break
        link = (_extract_link_from_text(seen.text or seen.caption)
                or _extract_link_from_entities(seen))
        if link:
            return link, seen
        seen = seen.reply_to_message
    return None, None


def _is_torrent_source(url):
    return url.lower().startswith("magnet:") or url.lower().endswith(".torrent")


# Resolve torrent/magnet source
async def _resolve_torrent_source(client, message, url):
    if url and url.lower().startswith("magnet:"):
        return "magnet", url
    if message.reply_to_message and message.reply_to_message.document and \
            (message.reply_to_message.document.file_name or "").lower().endswith(".torrent"):
        path = await client.download_media(message.reply_to_message)
        with open(path, "rb") as f:
            data = f.read()
        os.remove(path)
        return "torrent_bytes", data
    if url:
        import aiohttp
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            max_attempts = 6
            for attempt in range(max_attempts):
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        try:
                            wait_s = float(retry_after) if retry_after else (5 * (attempt + 1))
                        except ValueError:
                            wait_s = 5 * (attempt + 1)
                        await resp.read()
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(min(wait_s, 60))
                            continue
                        raise Exception("ᴛᴏʀʀᴇɴᴛ ꜱɪᴛᴇ ɪꜱ ʀᴀᴛᴇ-ʟɪᴍɪᴛɪɴɢ ʀᴇQᴜᴇꜱᴛꜱ (HTTP 429) — ᴛʀʏ ᴀɢᴀɪɴ ɪɴ ᴀ ᴍɪɴᴜᴛᴇ")
                    data = await resp.read()
                    if resp.status != 200:
                        raise Exception(f"ᴛᴏʀʀᴇɴᴛ ʟɪɴᴋ ʀᴇᴛᴜʀɴᴇᴅ HTTP {resp.status} — ʟɪɴᴋ ᴍᴀʏ ʙᴇ ᴅᴇᴀᴅ ᴏʀ ʙʟᴏᴄᴋᴇᴅ")
                    break
        if not data.startswith(b"d"):
            raise Exception(
                "<i>_ᴛᴏʀʀᴇɴᴛ ʟɪɴᴋ ᴅɪᴅɴ'ᴛ ʀᴇᴛᴜʀɴ ᴀ ᴠᴀʟɪᴅ .torrent ꜰɪʟᴇ"
                "(ꜱɪᴛᴇ ᴍᴀʏ ʙᴇ ʙʟᴏᴄᴋɪɴɢ ᴀᴜᴛᴏᴍᴀᴛᴇᴅ ʀᴇQᴜᴇꜱᴛꜱ ᴏʀ ᴛʜᴇ ʟɪɴᴋ ɪꜱ ᴡʀᴏɴɢ)_</i>"
            )
        return "torrent_bytes", data
    return None, None


# Cancellable leech job wrapper
class _LeechProc:
    def __init__(self):
        self._job = None

    def set_job(self, job):
        self._job = job

    def kill(self):
        if self._job:
            asyncio.ensure_future(self._job.shutdown())


_leech_ctx = {}     # id(message) -> {"task_id", "status"} until the job is queued


@Client.on_message(filters.command("l") & allowed)
async def cmd_leech(client, message: Message):
    try:
        await _cmd_leech(client, message)
    except Exception as e:
        ctx = _leech_ctx.get(id(message))
        if not ctx:
            raise
        log_error(f"cmd_leech: unexpected error (uid={message.from_user.id})", e)
        tfail(ctx["task_id"], "leech", "Unexpected error", e)
        await send_failure_log(message, ctx["task_id"], "Leech failed", ctx["status"], "❌ Leech failed")
    finally:
        _leech_ctx.pop(id(message), None)


async def _cmd_leech(client, message: Message):
    uid = message.from_user.id
    group_id = message.chat.id
    task_id = new_task_id()
    parts = message.text.split(maxsplit=1)
    trailing = parts[1].strip() if len(parts) > 1 else ""

    new_filename = None
    url = None
    url_source_msg = None
    replied_torrent_doc = bool(
        message.reply_to_message and message.reply_to_message.document and
        (message.reply_to_message.document.file_name or "").lower().endswith(".torrent")
    )

    tokens = trailing.split() if trailing else []

    if "-n" in tokens:
        idx = tokens.index("-n")
        name_url_tokens = tokens[:idx] + tokens[idx + 1:]
        url_tokens  = [t for t in name_url_tokens if URL_REGEX.fullmatch(t)]
        name_tokens = [t for t in name_url_tokens if t not in url_tokens]
        new_filename = " ".join(name_tokens).strip() or None
        url = url_tokens[0] if url_tokens else None
        if url:
            url_source_msg = message
        if not new_filename:
            return
        if not url and message.reply_to_message and not replied_torrent_doc:
            url, url_source_msg = _extract_link_from_message(message.reply_to_message)
    elif trailing:
        url = trailing
        url_source_msg = message
    elif message.reply_to_message and not replied_torrent_doc:
        url, url_source_msg = _extract_link_from_message(message.reply_to_message)

    if not url and not replied_torrent_doc:
        return

    if url and not replied_torrent_doc and not _is_torrent_source(url) and \
            not (url.startswith("http://") or url.startswith("https://")):
        return

    is_torrent = replied_torrent_doc or (url and _is_torrent_source(url))

    if replied_torrent_doc:
        source_msg = message.reply_to_message
    else:
        source_msg = url_source_msg or message
    source_uid = source_msg.from_user.id if source_msg and source_msg.from_user else uid

    status = await safe_reply(message, f"<b>ꜱᴛᴀʀᴛɪɴɢ ʟᴇᴇᴄʜ...</b>", reply_markup=cancel_button(task_id, uid))
    start_log("leech", task_id, uid, group_id, url=url, new_filename=new_filename, is_torrent=bool(is_torrent))
    _leech_ctx[id(message)] = {"task_id": task_id, "status": status}

    dl_proc = _LeechProc()
    register_task(task_id, dl_proc, "leeching", group_id=group_id, uid=uid)

    downloaded = []
    dest_dir = f"/tmp/leech/{uid}_{uuid.uuid4().hex[:8]}"

    job = None
    try:
        if is_torrent:
            kind, payload = await _resolve_torrent_source(client, message, url)
            await safe_edit(status, f"<b>ꜱᴛᴀʀᴛɪɴɢ ᴀʀɪᴀ2....</b>", reply_markup=cancel_button(task_id, uid))
            job = Aria2Job(dest_dir)
            dl_proc.set_job(job)
            await job.start()
            if kind == "magnet":
                gid = await job.add_uri(payload)
            else:
                gid = await job.add_torrent(payload)
            downloaded = await job.wait_for_download(gid, status, task_id, uid, return_all=True)
        else:
            downloaded = await download_from_link(url, dest_dir, status, task_id, uid)
    except asyncio.CancelledError:
        clear_task(task_id)
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        drop_log(task_id)
        return await safe_edit(status, f"<b>Cancelled!</b>", reply_markup=None)
    except Exception as e:
        log_error(f"cmd_leech: leech failed (uid={uid}, url={url})", e)
        clear_task(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        tfail(task_id, "leech", "Leech failed", e)
        return await send_failure_log(message, task_id, "Leech failed", status, "❌ Leech failed")
    finally:
        if job:
            await job.shutdown()

    clear_task(task_id)

    if is_cancelled(task_id):
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        drop_log(task_id)
        return await safe_edit(status, f"<b>Cancelled!</b>", reply_markup=None)

    downloaded = [(p, n) for p, n in downloaded if p and os.path.exists(p)]
    if not downloaded:
        print(f"[ERROR] cmd_leech: leech finished but file not saved (uid={uid}, url={url})")
        tfail(task_id, "leech", "Download finished but no file was saved")
        return await send_failure_log(message, task_id, "Leech failed: file not saved", status, "❌ Leech failed: file not saved")
    tlog(task_id, "leech", f"downloaded {len(downloaded)} file(s): {[n for _, n in downloaded][:20]}")

    if new_filename:
        s = await db.get_settings(source_uid)
        res = s["resolution"]
        target_quality = None if res == "original" else RES_MAP.get(res, res)
        downloaded = rename_items(downloaded, new_filename, target_quality)
        tlog(task_id, "rename", f"-n '{new_filename}' -> {[n for _, n in downloaded][:20]}")

    (dl_path, final_name), extras = downloaded[0], downloaded[1:]

    will_wait = get_active_uid(group_id) is not None or group_queue_size(group_id) > 0
    leech_batch = {"root": dest_dir, "left": len(downloaded)}    # folder is removed after the last file get encode
    queue_pos = await enqueue(group_id, {
        "msg": message,
        "local_path": dl_path,
        "original_name": final_name,
        "compress_uid": source_uid,
        "status_msg": status,
        "was_queued": will_wait,
        "leech_batch": leech_batch,
    })
    _leech_ctx.pop(id(message), None)
    for extra_path, extra_name in extras:
        extra_status = await safe_reply(
            message,
            f"<b>ʟᴇᴇᴄʜᴇᴅ — ᴀᴅᴅᴇᴅ ᴛᴏ ᴇɴᴄᴏᴅᴇ Qᴜᴇᴜᴇ</b>\n<blockquote>{extra_name}</blockquote>",
        )
        extra_pos = await enqueue(group_id, {
            "msg": message,
            "local_path": extra_path,
            "original_name": extra_name,
            "compress_uid": source_uid,
            "status_msg": extra_status,
            "was_queued": True,
            "leech_batch": leech_batch,
        })
        await safe_edit(
            extra_status,
            f"<b>ʟᴇᴇᴄʜᴇᴅ — ᴀᴅᴅᴇᴅ ᴛᴏ ᴇɴᴄᴏᴅᴇ Qᴜᴇᴜᴇ</b> #{extra_pos}\n<blockquote>{extra_name}</blockquote>\n"
            f"ʏᴏᴜʀ ᴇɴᴄᴏᴅᴇ ᴡɪʟʟ ꜱᴛᴀʀᴛ ᴡʜᴇɴ ɪᴛꜱ ᴛᴜʀɴ ᴄᴏᴍᴇꜱ",
            reply_markup=None,
        )
    tlog(task_id, "leech", f"queued {len(downloaded)} file(s) for encoding")
    drop_log(task_id)
    if not is_worker_running(group_id):
        asyncio.ensure_future(group_queue_worker(client, group_id))
    if will_wait:
        await safe_edit(
            status,
            f"<b>ʟᴇᴇᴄʜᴇᴅ — ᴀᴅᴅᴇᴅ ᴛᴏ ᴇɴᴄᴏᴅᴇ Qᴜᴇᴜᴇ</b> #{queue_pos}\n"
            f"ʏᴏᴜʀ ᴇɴᴄᴏᴅᴇ ᴡɪʟʟ ꜱᴛᴀʀᴛ ᴡʜᴇɴ ɪᴛꜱ ᴛᴜʀɴ ᴄᴏᴍᴇꜱ",
            reply_markup=None,
        )
