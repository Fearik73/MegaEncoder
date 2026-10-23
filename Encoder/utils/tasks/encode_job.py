import os, re, shutil, asyncio, time
from pyrogram.types import Message

from Encoder.config import DOWNLOAD_DIR, OUTPUT_DIR, DB_CHANNEL
from Encoder.utils.database.access_db import db
from Encoder.utils.tasks.cancel import (
    is_cancelled, clear_cancelled, register_task, clear_task, new_task_id,
)
from Encoder.utils.helpers import (
    sanitize_filename, log_error, safe_edit, safe_reply, cancel_button,
)
from Encoder.utils.display_progress import make_progress_callback
from Encoder.utils.encoding.thumb import get_user_thumb, extract_auto_thumb
from Encoder.utils.downloads.telegram import stream_download
from Encoder.utils.encoding.ffmpeg import ffmpeg_encode
from Encoder.utils.encoding.splitter import split_video, SPLIT_SIZE
from Encoder.utils.logs.tasklog import (
    start_log, tlog, tfail, set_info, probe_into_log, send_failure_log,
)

# Duration / width / height for "Send as Media" uploads
async def _video_info(path: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "default=noprint_wrappers=1:nokey=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        info = dict(l.split("=", 1) for l in out.decode().splitlines() if "=" in l)
        return int(float(info.get("duration", 0))), int(info.get("width", 0)), int(info.get("height", 0))
    except Exception:
        return 0, 0, 0


RES_MAP = {
    "1920x1080": "1080p",
    "1280x720":  "720p",
    "960x540":   "540p",
    "854x480":   "480p",
    "640x360":   "360p",
    "426x240":   "240p",
}

_QUALITY_RE = re.compile(
    r'(\[|\()?'
    r'(4k|2k|Hdrip|hdrip|HDRIP|HDRip|WEBRip|WEB-DL|BluRay|BDRip|DVDRip|HDTV|CAMRip|HQ|SD|HD|\d{3,4}p)'
    r'(\]|\))?',
    re.IGNORECASE
)

# Rename files with new resolution 
def smart_filename(original: str, resolution: str) -> str:
    original = sanitize_filename(original)
    base, ext = os.path.splitext(original)
    if not ext:
        ext = ".mkv"
    if resolution == "original":
        return original
    new_tag = RES_MAP.get(resolution, resolution)

    def _replace(m: re.Match) -> str:
        open_b  = m.group(1) or ""
        close_b = m.group(3) or ""
        if open_b and close_b:
            return f"{open_b}{new_tag}{close_b}"
        return new_tag

    replaced, n = _QUALITY_RE.subn(_replace, base, count=1)
    if n:
        return replaced + ext
    return f"{base} [{new_tag}]{ext}"


def _pick_original_name(rename_source, msg, file):
    caption = (msg.caption or msg.text or "").strip()
    file_name = file.file_name if getattr(file, "file_name", None) else ""
    if rename_source == "filename":
        chosen = file_name
    elif rename_source == "caption":
        chosen = caption
    else:
        chosen = caption or file_name
    return sanitize_filename(chosen) if chosen else f"video_{file.file_id[:8]}.mkv"


async def _report_failure(msg, task_id, reason, stage, detail=None, exc=None, status=None, fallback=None):
    tfail(task_id, stage, detail or reason, exc)
    await send_failure_log(msg, task_id, reason, status, fallback)


_BANNER = re.compile(r"^\s*(ffmpeg version|built with|configuration:|lib\w+\s+\d+\.)")


def _ffmpeg_error_tail(err, n=5):
    lines = [l for l in str(err).splitlines() if l.strip() and not _BANNER.match(l)]
    return "\n".join(lines[-n:])


def _release_leech_file(job: dict):
    batch = job.get("leech_batch")
    if not batch:
        return
    batch["left"] -= 1
    if batch["left"] <= 0:
        shutil.rmtree(batch["root"], ignore_errors=True)


async def run_encode_job(client, job: dict, group_id: int):
    try:
        await _run_encode_job(client, job, group_id)
    finally:
        _release_leech_file(job)

#------------------- Main Encode Job-----------------------
async def _run_encode_job(client, job: dict, group_id: int):
    msg:  Message = job["msg"]
    file          = job.get("file")
    local_path    = job.get("local_path")
    uid           = job.get("compress_uid") or msg.from_user.id
    s             = await db.get_settings(uid)
    task_id       = new_task_id()

    clear_cancelled(task_id)
    start_log(
        "encode", task_id, uid, group_id,
        source="leech" if local_path else "telegram",
        settings=dict(s),
        queued_name=job.get("original_name"),
    )
    job["_task_id"] = task_id

    dl_path = None

    if local_path:
        original_name = sanitize_filename(job.get("original_name") or os.path.basename(local_path))

        old_status = job.get("status_msg")
        if old_status and job.get("was_queued"):
            try:
                await old_status.delete()
            except Exception:
                pass
            status = await safe_reply(msg, f"**ᴘʀᴇᴘᴀʀɪɴɢ ʟᴇᴇᴄʜᴇᴅ ꜰɪʟᴇ...**", reply_markup=cancel_button(task_id, uid))
        elif old_status:
            status = old_status
            await safe_edit(status, f"**ᴘʀᴇᴘᴀʀɪɴɢ ʟᴇᴇᴄʜᴇᴅ ꜰɪʟᴇ...**", reply_markup=cancel_button(task_id, uid))
        else:
            status = await safe_reply(msg, f"**ᴘʀᴇᴘᴀʀɪɴɢ ʟᴇᴇᴄʜᴇᴅ ꜰɪʟᴇ...**", reply_markup=cancel_button(task_id, uid))
        job["_status"] = status

        if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
            print(f"[ERROR] run_encode_job: leeched file missing or empty (uid={uid}, path={local_path})")
            await _report_failure(msg, task_id, "Leeched file missing or empty", "prepare", f"path: {local_path}",
                                  status=status, fallback="❌ **Leeched file missing or empty.**")
            return
        dl_path = local_path
        tlog(task_id, "prepare", f"leeched file: {local_path} ({os.path.getsize(local_path)} bytes)")
        
    else:
        original_name = _pick_original_name(s["rename_source"], msg, file)

        orig_ext = os.path.splitext(original_name)[1] or ".mkv"

        old_status = job.get("status_msg")
        if old_status and job.get("was_queued"):
            try:
                await old_status.delete()
            except Exception:
                pass
            status = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ**", reply_markup=cancel_button(task_id, uid))
        elif old_status:
            status = old_status
            await safe_edit(status, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ**", reply_markup=cancel_button(task_id, uid))
        else:
            status = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ**", reply_markup=cancel_button(task_id, uid))
        job["_status"] = status
        dl_start = [time.time()]

        class _FakeProc:
            def __init__(self): self._task = None
            def set(self, t):   self._task = t
            def kill(self):
                if self._task and not self._task.done():
                    self._task.cancel()

        _dl_proc = _FakeProc()
        register_task(task_id, _dl_proc, "downloading", group_id=group_id, uid=uid)

        try:
            last_exc = None
            base_dest = os.path.join(DOWNLOAD_DIR, f"{uid}_{file.file_id[:8]}{orig_ext}")
            for _attempt in range(3):
                if is_cancelled(task_id):
                    break
                dest = base_dest
                if os.path.exists(dest):
                    os.remove(dest)
                try:
                    if _attempt > 0:
                        await safe_edit(status, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ** (attempt {_attempt + 1}/3)...", reply_markup=cancel_button(task_id, uid))
                    progress_cb = make_progress_callback(status, "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...", dl_start, task_id, uid)
                    _dl_task = asyncio.ensure_future(
                        stream_download(client, msg, dest, progress_cb, task_id=task_id)
                    )
                    _dl_proc.set(_dl_task)
                    await _dl_task
                    dl_path = dest
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log_error(f"run_encode_job: download attempt {_attempt + 1}/3 failed (uid={uid})", e)
                    last_exc = e
                    dl_path = None
                    if _attempt < 2:
                        await asyncio.sleep(5)
                        dl_start[0] = time.time()
            if not dl_path and last_exc:
                raise last_exc
        except asyncio.CancelledError:
            clear_task(task_id)
            if dl_path and os.path.exists(dl_path): os.remove(dl_path)
            await safe_edit(status, f"**Cancelled!**", reply_markup=None)
            return
        except Exception as e:
            log_error(f"run_encode_job: download failed (uid={uid})", e)
            clear_task(task_id)
            await _report_failure(msg, task_id, "Download failed", "download", exc=e,
                                  status=status, fallback="❌ **Download failed**")
            return

        clear_task(task_id)

        if is_cancelled(task_id):
            clear_cancelled(task_id)
            if dl_path and os.path.exists(dl_path): os.remove(dl_path)
            await safe_edit(status, f"**Cancelled!**", reply_markup=None)
            return

        if not dl_path or not os.path.exists(dl_path):
            print(f"[ERROR] run_encode_job: download failed, file not saved (uid={uid})")
            await _report_failure(msg, task_id, "Download failed: file not saved", "download",
                                  status=status, fallback="❌ **Download failed: file not saved.**")
            return

        if os.path.getsize(dl_path) == 0:
            print(f"[ERROR] run_encode_job: download produced empty file (uid={uid}, path={dl_path})")
            os.remove(dl_path)
            await _report_failure(msg, task_id, "Download failed: empty file", "download",
                                  status=status, fallback="❌ **Download failed: empty file.**")
            return
            
    out_filename = smart_filename(original_name, s["resolution"])
    out_filename = os.path.splitext(out_filename)[0] + ".mkv"
    job_out_dir  = os.path.join(OUTPUT_DIR, f"{group_id}_{uid}_{int(time.time()*1000)}")
    os.makedirs(job_out_dir, exist_ok=True)
    out_path     = os.path.join(job_out_dir, out_filename)

    set_info(task_id, original_name=original_name, output_name=out_filename, input_path=dl_path)
    tlog(task_id, "encode", f"input {original_name} ({os.path.getsize(dl_path)} bytes) -> {out_filename}")
    await probe_into_log(task_id, dl_path)

    await safe_edit(
        status,
        f"**ꜱᴛᴀʀᴛɪɴɢ ᴇɴᴄᴏᴅᴇ...**\n\n"
        f"**ꜰɪʟᴇ:** {original_name}\n"
        f"**ᴄᴏᴅᴇᴄ:** {s['codec']}  **ᴄʀꜰ:** {s['crf']}\n"
        f"**ᴘʀᴇꜱᴇᴛ:** {s['preset']}  **ᴛᴜɴᴇ:** {s['tune']}\n"
        f"**ʀᴇꜱᴏʟᴜᴛɪᴏɴ:** {s['resolution']}\n"
        f"**ᴀᴜᴅɪᴏ:** {s['audio_codec']} @ {s['audio_bitrate']}",
        reply_markup=cancel_button(task_id, uid)
    )

    success, err = await ffmpeg_encode(
        dl_path, out_path,
        s["codec"], s["crf"], s["preset"],
        s["audio_bitrate"], s["audio_codec"],
        s["resolution"], s["tune"],
        group_id, uid, task_id, status,
        audio_channel=s["audio_channel"], bit_depth=s["bit_depth"], fps=s["fps"],
    )

    if dl_path and os.path.exists(dl_path):
        os.remove(dl_path)

    if err == "cancelled" or is_cancelled(task_id):
        clear_cancelled(task_id)
        shutil.rmtree(job_out_dir, ignore_errors=True)
        await safe_edit(status, f"**Cancelled!**", reply_markup=None)
        return

    if not success:
        print(f"[ERROR] run_encode_job: ffmpeg encode failed (uid={uid}, file={original_name}): {err}")
        shutil.rmtree(job_out_dir, ignore_errors=True)
        await _report_failure(msg, task_id, "Encoding failed", "ffmpeg", detail=_ffmpeg_error_tail(err),
                              status=status, fallback="<b>⚠️ Encoding Failed!</b>")
        return

    tlog(task_id, "encode", f"ffmpeg finished OK ({os.path.getsize(out_path)} bytes)")

    meta_status = await db.get_metadata_status(uid)
    if meta_status == "On":
        try:
            await safe_edit(status, f"**ᴀᴘᴘʟʏɪɴɢ ᴍᴇᴛᴀᴅᴀᴛᴀ...**", reply_markup=cancel_button(task_id, uid))
            from Encoder.utils.encoding.metadata import add_metadata
            meta_out_path = os.path.splitext(out_path)[0] + "_meta.mkv"
            await add_metadata(out_path, meta_out_path, uid, db)
            if os.path.exists(meta_out_path) and os.path.getsize(meta_out_path) > 0:
                os.remove(out_path)
                out_path = meta_out_path
        except Exception as e:
            log_error(f"run_encode_job: metadata mux skipped (uid={uid})", e)
            tlog(task_id, "metadata", f"skipped: {e!r}", "warn")

    await safe_edit(status, f"**ᴜᴘʟᴏᴀᴅɪɴɢ**", reply_markup=cancel_button(task_id, uid))
    up_start   = [time.time()]
    thumb      = await get_user_thumb(uid)
    auto_thumb = None
    if not thumb:
        auto_thumb = await extract_auto_thumb(out_path, uid)
        thumb      = auto_thumb

    try:
        if is_cancelled(task_id):
            raise asyncio.CancelledError()

        # Bigger than the limit so cut them into parts
        upload_parts = [(out_path, out_filename)]
        if os.path.getsize(out_path) > SPLIT_SIZE:
            await safe_edit(status, f"**ꜱᴘʟɪᴛᴛɪɴɢ ꜰɪʟᴇ...**", reply_markup=cancel_button(task_id, uid))
            try:
                split_res = await split_video(
                    out_path, job_out_dir, os.path.splitext(out_filename)[0], ".mkv",
                    task_id, group_id, uid,
                )
            except Exception as e:
                log_error(f"run_encode_job: split failed (uid={uid}, file={out_filename})", e)
                raise
            if split_res is None:
                raise asyncio.CancelledError()
            upload_parts = split_res
            tlog(task_id, "split", f"split into {len(split_res)} part(s)")
            os.remove(out_path)

        for idx, (part_path, part_name) in enumerate(upload_parts, 1):
            if is_cancelled(task_id):
                raise asyncio.CancelledError()
            tlog(task_id, "upload", f"uploading {part_name} ({os.path.getsize(part_path)} bytes) as {s['send_type']} [{idx}/{len(upload_parts)}]")
            if len(upload_parts) > 1:
                up_label = f"ᴜᴘʟᴏᴀᴅɪɴɢ ᴘᴀʀᴛ {idx}/{len(upload_parts)}..."
                up_start = [time.time()]
            else:
                up_label = "ᴜᴘʟᴏᴀᴅɪɴɢ..."
            if s["send_type"] == "media":
                v_dur, v_w, v_h = await _video_info(part_path)
                sent = await msg.reply_video(
                    video=part_path,
                    thumb=thumb,
                    file_name=part_name,
                    caption=f"**{part_name}**",
                    duration=v_dur, width=v_w, height=v_h,
                    supports_streaming=True,
                    progress=make_progress_callback(status, up_label, up_start, task_id, uid),
                )
            else:
                sent = await msg.reply_document(
                    document=part_path,
                    thumb=thumb,
                    file_name=part_name,
                    caption=f"**{part_name}**",
                    progress=make_progress_callback(status, up_label, up_start, task_id, uid),
                )
            if DB_CHANNEL:
                try:
                    await sent.copy(DB_CHANNEL)
                except Exception as e:
                    log_error(f"run_encode_job: DB_CHANNEL copy failed (uid={uid})", e)
        await status.delete()
    except asyncio.CancelledError:
        await safe_edit(status, f"**Cancelled!**", reply_markup=None)
    except Exception as e:
        log_error(f"run_encode_job: upload failed (uid={uid}, file={out_filename})", e)
        await _report_failure(msg, task_id, "Upload failed", "upload", exc=e,
                              status=status, fallback="<b>⚠️ Upload failed</b>")
    finally:
        clear_cancelled(task_id)
        shutil.rmtree(job_out_dir, ignore_errors=True)
        if auto_thumb and os.path.exists(auto_thumb): os.remove(auto_thumb)
