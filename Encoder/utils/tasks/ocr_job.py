import asyncio
import gc
import os
import re
import shutil
import time

from pyrogram import enums
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InputMediaDocument

from Encoder.config import DOWNLOAD_DIR
from Encoder.utils.helpers import (
    cancel_button, log_error, safe_edit, safe_reply, sanitize_filename,
)
from Encoder.utils.logs.tasklog import start_log, tlog
from Encoder.utils.ocr import ass, config as ocfg, engine, ocr, ui
from Encoder.utils.ocr.subs import build_srt, core_len, srt_time, tidy
from Encoder.utils.ocr.ui import esc, kv, sc
from Encoder.utils.tasks.cancel import (
    clear_cancelled, clear_task, is_cancelled, new_task_id, register_task,
)
from Encoder.utils.tasks.sub_jobs import _download_video, _report_failure

HTML = enums.ParseMode.HTML


class _Cancelled(Exception):
    pass


class _Status:
    def __init__(self, msg, task_id: int, uid: int, src=None):
        self.msg, self.task_id, self.uid, self.src = msg, task_id, uid, src
        self.t0 = time.monotonic()
        self.last = 0.0

    async def show(self, stage, frac=None, extra=(), force=False):
        now = time.monotonic()
        if not force and now - self.last < 4:
            return
        self.last = now
        await safe_edit(
            self.msg, ui.status(stage, frac, now - self.t0, extra),
            reply_markup=cancel_button(self.task_id, self.uid),
        )

    async def end(self, text):
        await safe_edit(self.msg, text)

    async def finish(self, text):
        if self.src is not None:
            try:
                await safe_reply(self.src, text, parse_mode=HTML, quote=True)
            except Exception as e:
                print(f"[OCR] done message failed: {e!r}")
            else:
                try:
                    await self.msg.delete()
                except Exception:
                    pass
                return
        await safe_edit(self.msg, text)


async def _reply_doc(m, path, caption):
    return await m.reply_document(path, caption=caption, parse_mode=HTML, quote=True)


class _LiveFile:
    INTERVAL = 10.0

    def __init__(self, m, path, render=None, title="live subtitles"):
        self.m, self.path = m, path
        self.render = render or (lambda its, final: build_srt(its, "zh"))
        self.title = title
        self.msg = None
        self.last = 0.0
        self.shown = 0

    async def update(self, items, force=False, caption=None, final=False):
        now = time.monotonic()
        if not force and (len(items) == self.shown or now - self.last < self.INTERVAL):
            return
        self.last, self.shown = now, len(items)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.render(items, final))
        caption = caption or f"<b>⧉ {sc(self.title)}</b>\n{kv('lines', len(items))}"
        for _ in range(3):
            try:
                if self.msg is None:
                    self.msg = await _reply_doc(self.m, self.path, caption)
                else:
                    await self.msg.edit_media(InputMediaDocument(self.path, caption=caption, parse_mode=HTML))
                return True
            except MessageNotModified:
                return True
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                print(f"[OCR] live file update failed: {e!r}")
                return False
        return False


def _ass_text(items, metas, video_size, font, t_start, final):
    pw, ph, fsize, margin, base_top = ass.auto_layout(metas, video_size[0], video_size[1], ocfg.ASS_GAP)
    entries = []
    base_h = ass.base_height(metas)
    for p in items:
        own = None
        m = p.get("meta")
        if m and m.get("bands", 1) > 1 and m["conf"] >= 0.9:
            own = ass.line_margin(m, ph, base_top, ocfg.ASS_GAP, base_h)
        entries.append((p["start"], p["end"], [p["zh"]], own))
    last_end = max((p["end"] for p in items), default=None)
    credits = ass.credit_lines(
        t_start, last_end, (ocfg.ASS_OPEN, ocfg.ASS_THANKS), ocfg.ASS_CREDIT_SEC, final,
    )
    return ass.build_ass_geo(entries, pw, ph, fsize, margin, font, credits)


async def run_ocr_job(client, job: dict, group_id: int):
    msg     = job["src_msg"]
    uid     = job["uid"]
    t_start = job.get("t_start") or 0.0
    t_end   = job.get("t_end")
    task_id = new_task_id()
    clear_cancelled(task_id)
    start_log("ocr", task_id, uid, group_id)

    file = msg.video or msg.document

    old_status = job.get("status_msg")
    if old_status and job.get("was_queued"):
        try:
            await old_status.delete()
        except Exception:
            pass
        status_msg = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    elif old_status:
        status_msg = old_status
        await safe_edit(status_msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    else:
        status_msg = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    status = _Status(status_msg, task_id, uid, msg)

    dest_dir   = os.path.join(DOWNLOAD_DIR, f"ocr_{uid}_{int(time.time())}")
    os.makedirs(dest_dir, exist_ok=True)
    orig_name  = sanitize_filename(getattr(file, "file_name", None) or f"video_{file.file_id[:8]}.mkv")
    video_path = os.path.join(dest_dir, orig_name)
    base = re.sub(r"[^\w\-. ]+", "_", os.path.splitext(orig_name)[0]).strip()[:60] or "subtitles"

    try:
        try:
            await _download_video(client, msg, video_path, status_msg, task_id, uid)
        except asyncio.CancelledError:
            raise _Cancelled
        except Exception as e:
            log_error(f"run_ocr_job: download failed (uid={uid})", e)
            return await _report_failure(msg, task_id, "Download failed", "download", exc=e,
                                         status=status_msg, fallback="❌ **Download failed**")
        if is_cancelled(task_id):
            raise _Cancelled

        if not engine.state["started"]:
            return await _report_failure(msg, task_id, "OCR is not available", "ocr",
                                         detail="OCR engine was never started (check OCR dependencies)",
                                         status=status_msg, fallback="❌ **OCR is not available**")
        while not engine.ready.is_set():
            if engine.state["error"]:
                return await _report_failure(msg, task_id, "OCR is not available", "ocr",
                                             detail=engine.state["error"], status=status_msg,
                                             fallback=ui.failed(f"OCR is not available: {engine.state['error']}"))
            if is_cancelled(task_id):
                raise _Cancelled
            await status.show("loading ocr")
            await asyncio.sleep(2)

        register_task(task_id, None, "ocr", group_id, uid)
        await _scan_and_send(msg, status, task_id, t_start, t_end, video_path, dest_dir, base)

    except (_Cancelled, asyncio.CancelledError):
        await status.end(ui.cancelled())
    except Exception as e:
        log_error(f"run_ocr_job (uid={uid})", e)
        await _report_failure(msg, task_id, "OCR failed", "ocr", exc=e, status=status_msg,
                              fallback=ui.failed(e))
    finally:
        clear_task(task_id)
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        gc.collect()


async def _scan_and_send(msg, status, task_id, t_start, t_end, video_path, dest_dir, base):
    t_begin = time.monotonic()
    cancelled = lambda: is_cancelled(task_id)
    live = _LiveFile(msg, os.path.join(dest_dir, f"{base}.zh.srt"))

    video_size = await asyncio.to_thread(ocr.video_size, video_path)
    items, metas, unread = [], [], []
    live_ass = None
    if video_size:
        live_ass = _LiveFile(
            msg, os.path.join(dest_dir, f"{base}.arial.ass"),
            lambda its, fin: _ass_text(its, metas, video_size, ocfg.ASS_FONT, t_start, fin),
            "live ass",
        )
    gen = ocr.scan_auto(video_path, cancelled, t_start, t_end)
    try:
        while True:
            r = await asyncio.to_thread(next, gen, None)
            if r is None:
                break
            s, e, text, frac, flag, meta = r
            if meta and meta["conf"] >= 0.9 and "glare" not in flag:
                metas.append({**meta, "start": s})
            if text is None and flag == "unread":
                unread.append((s, e))
            if text is not None:
                items.append({"start": s, "end": e, "zh": text, "flag": flag, "meta": meta})
                items.sort(key=lambda p: p["start"])
                await live.update(items)
                if live_ass:
                    await live_ass.update(items)
            await status.show("scanning", frac, [kv("lines", len(items))])
    finally:
        try:
            gen.close()
        except ValueError:
            pass
    if cancelled():
        raise _Cancelled
    os.remove(video_path)

    items = [p for p in ocr.merge(items) if core_len(p["zh"]) >= ocfg.OCR_MIN_CHARS]
    if not items:
        return await status.end(ui.nothing())
    tlog(task_id, "ocr", f"{len(items)} subtitle lines read")

    tidy(items)
    await live.update(items, force=True, caption=f"<b>⧉ {sc('chinese subtitles')}</b>")

    if video_size:
        for font, tag in ((ocfg.ASS_FONT, "arial"), (ocfg.ASS_FONT_CJK, "cjk")):
            caption = f"<b>⧉ {sc('ass subtitles')}</b>\n{kv('font', esc(font))}\n{kv('lines', len(items))}"
            if tag == "arial" and live_ass and await live_ass.update(items, force=True, caption=caption, final=True):
                continue
            path = os.path.join(dest_dir, f"{base}.{tag}.ass")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_ass_text(items, metas, video_size, font, t_start, True))
            await _reply_doc(msg, path, caption)

    await status.finish(ui.done(len(items), time.monotonic() - t_begin))
    if unread:
        spans = []
        for s0, e0 in sorted(unread):
            if spans and s0 - spans[-1][1] <= 1.0:
                spans[-1][1] = max(spans[-1][1], e0)
            else:
                spans.append([s0, e0])
        lines = "\n".join(f"{srt_time(a)[:8]} - {srt_time(b)[:8]}" for a, b in spans[:25])
        await safe_reply(msg, f"<b>⧉ {sc('unread lines')} ({len(spans)})</b>\n{lines}")

    
