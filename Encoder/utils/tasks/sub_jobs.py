import os, time, shutil, asyncio

from Encoder.config import DOWNLOAD_DIR
from Encoder.utils.helpers import (
    safe_reply, safe_edit, sanitize_filename, cancel_button, log_error,
)
from Encoder.utils.display_progress import (
    progress_bar, human_time, make_progress_callback,
)
from Encoder.utils.encoding.thumb import (
    get_video_duration, get_user_thumb, extract_auto_thumb,
)
from Encoder.utils.logs.tasklog import (
    start_log, tlog, tfail, send_failure_log,
)
from Encoder.utils.downloads.telegram import stream_download
from Encoder.utils.tasks.cancel import (
    register_task, clear_task, is_cancelled, clear_cancelled, new_task_id,
)
from Encoder.utils.subtitles.subtitles_utils import (
    LANG_ISO, CODEC_EXT, LANG_MAP, probe_subtitle_streams, mark_xsub_done,
)

# ISO code - language name reverse mapping
ISO_TO_LANG = {v: k for k, v in LANG_ISO.items() if k != "Unknown"}


class _CancellableTask:
    def __init__(self): self._task = None
    def set(self, t):   self._task = t
    def kill(self):
        if self._task and not self._task.done():
            self._task.cancel()


async def _report_failure(msg, task_id, reason, stage, detail=None, exc=None, status=None, fallback=None):
    tfail(task_id, stage, detail or reason, exc)
    await send_failure_log(msg, task_id, reason, status, fallback)


async def _download_video(client, src_msg, dest_path: str, status_msg, task_id: int, uid: int):
    dl_proc = _CancellableTask()
    register_task(task_id, dl_proc, "downloading", uid=uid)
    try:
        dl_task = asyncio.ensure_future(
            stream_download(
                client, src_msg, dest_path,
                make_progress_callback(status_msg, "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...", [time.time()], task_id, uid),
                task_id=task_id,
            )
        )
        dl_proc.set(dl_task)
        await dl_task
    finally:
        clear_task(task_id)


# mux subtitle files into video
async def run_addsub_job(client, job: dict, group_id: int):
    msg       = job["msg"]
    video_msg = job["video_msg"]
    subs      = job["subs"]
    uid       = job["uid"]
    task_id   = new_task_id()
    clear_cancelled(task_id)
    start_log(
        "addsub", task_id, uid, group_id,
        subs=[{"lang": s.get("lang"), "file": os.path.basename(str(s.get("path")))} for s in subs],
    )

    old_status = job.get("status_msg")
    if old_status and job.get("was_queued"):
        try:
            await old_status.delete()
        except Exception:
            pass
        status = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    elif old_status:
        status = old_status
        await safe_edit(status, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    else:
        status = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))

    dest_dir = os.path.join(DOWNLOAD_DIR, f"esub_{uid}_{int(time.time())}")
    os.makedirs(dest_dir, exist_ok=True)

    file       = video_msg.video or video_msg.document
    orig_name  = sanitize_filename(getattr(file, "file_name", None) or f"video_{file.file_id[:8]}.mkv")
    video_path = os.path.join(dest_dir, orig_name)

    try:
        await _download_video(client, video_msg, video_path, status, task_id, uid)
    except asyncio.CancelledError:
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"**Cancelled!**", reply_markup=None)
    except Exception as e:
        log_error(f"run_addsub_job: video download failed (uid={uid})", e)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await _report_failure(msg, task_id, "Video download failed", "download", exc=e,
                                     status=status, fallback="❌ **Video download failed**")

    tlog(task_id, "download", f"video downloaded ({os.path.getsize(video_path)} bytes): {orig_name}")

    if is_cancelled(task_id):
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"**Cancelled!**", reply_markup=None)

    await safe_edit(status, f"**ᴍᴇʀɢɪɴɢ ꜱᴜʙᴛɪᴛʟᴇꜱ...**", reply_markup=cancel_button(task_id, uid))

    out_name = os.path.splitext(orig_name)[0] + ".mkv"
    out_path = os.path.join(dest_dir, "merged_" + out_name)

    cmd = ["ffmpeg", "-y", "-sub_charenc", "UTF-8", "-i", video_path]
    for s in subs:
        cmd += ["-i", s["path"]]
    cmd += ["-map", "0:v", "-map", "0:a?", "-c:v", "copy", "-c:a", "copy"]
    for i in range(len(subs)):
        cmd += ["-map", f"{i + 1}:0"]
    cmd += ["-c:s", "copy"]
    for i, s in enumerate(subs):
        iso = LANG_ISO.get(s["lang"], "und")
        cmd += [f"-metadata:s:s:{i}", f"language={iso}", f"-metadata:s:s:{i}", f"title={s['lang']}"]
    cmd += ["-progress", "pipe:1", "-nostats", out_path]
    tlog(task_id, "merge", "cmd: " + " ".join(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await _report_failure(msg, task_id, "ffmpeg not found", "merge", exc=e,
                                     status=status, fallback="❌ **ffmpeg not found on this system.**")

    register_task(task_id, proc, "merging", uid=uid)

    total_duration = await get_video_duration(video_path)
    merge_start     = time.time()
    current_time    = 0.0
    last_update     = 0.0
    stderr_chunks: list[bytes] = []

    async def _drain_stderr():
        try:
            async for raw in proc.stderr:
                stderr_chunks.append(raw)
        except Exception:
            pass

    stderr_task = asyncio.ensure_future(_drain_stderr())

    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode(errors="replace").strip()

        if line.startswith("out_time_us="):
            try:
                us = int(line.split("=", 1)[1])
                if us >= 0:
                    current_time = us / 1_000_000
            except (ValueError, IndexError):
                pass

        elif line.startswith("progress="):
            is_end = line == "progress=end"
            now    = time.time()
            if now - last_update < 3 and not is_end:
                continue
            last_update = now
            if is_end and total_duration > 0:
                current_time = total_duration

            if total_duration > 0:
                pct  = min(current_time / total_duration * 100, 100.0)
                bar  = progress_bar(int(current_time), max(int(total_duration), 1))
                text = (
                    f"**ᴍᴇʀɢɪɴɢ ꜱᴜʙᴛɪᴛʟᴇꜱ...**\n\n"
                    f"[{bar}] {pct:.1f}%\n"
                    f"**ᴅᴏɴᴇ:** {human_time(current_time)} / {human_time(total_duration)}"
                )
            else:
                text = f"**ᴍᴇʀɢɪɴɢ ꜱᴜʙᴛɪᴛʟᴇꜱ...**\n\n**ᴇʟᴀᴘꜱᴇᴅ:** {human_time(now - merge_start)}"
            await safe_edit(status, text, reply_markup=cancel_button(task_id, uid))

    await proc.wait()
    if not stderr_task.done():
        try:
            await asyncio.wait_for(stderr_task, timeout=5)
        except Exception:
            stderr_task.cancel()

    clear_task(task_id)

    if is_cancelled(task_id):
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"**Cancelled!**", reply_markup=None)

    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        tail = b"".join(stderr_chunks).decode(errors="replace").strip()[-1200:]
        print(f"[ERROR] run_addsub_job: ffmpeg merge failed (uid={uid}, returncode={proc.returncode}): {tail}")
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await _report_failure(msg, task_id, "Merge failed", "merge",
                                     detail=f"ffmpeg returncode={proc.returncode}\n{tail}",
                                     status=status, fallback="❌ **Merge failed**")

    await safe_edit(status, f"**ᴜᴘʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    thumb      = await get_user_thumb(uid)
    auto_thumb = None
    if not thumb:
        auto_thumb = await extract_auto_thumb(out_path, uid)
        thumb      = auto_thumb

    try:
        if is_cancelled(task_id):
            raise asyncio.CancelledError()
        await video_msg.reply_document(
            document=out_path,
            thumb=thumb,
            file_name=out_name,
            caption=f"**{out_name}**\nSubtitles added: {len(subs)}",
            progress=make_progress_callback(status, "ᴜᴘʟᴏᴀᴅɪɴɢ...", [time.time()], task_id, uid),
        )
        await status.delete()
    except asyncio.CancelledError:
        await safe_edit(status, f"**Cancelled!**", reply_markup=None)
    except Exception as e:
        log_error(f"run_addsub_job: upload failed (uid={uid})", e)
        await _report_failure(msg, task_id, "Upload failed", "upload", exc=e,
                              status=status, fallback="❌ **Upload failed**")
    finally:
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        if auto_thumb and os.path.exists(auto_thumb): os.remove(auto_thumb)


async def run_extractsub_job(client, job: dict, group_id: int):
    uid = job["uid"]
    try:
        await _run_extractsub_job(client, job, group_id)
    finally:
        mark_xsub_done(uid)


async def _run_extractsub_job(client, job: dict, group_id: int):
    msg = job["src_msg"]
    uid = job["uid"]
    task_id = new_task_id()
    clear_cancelled(task_id)
    start_log("extractsub", task_id, uid, group_id)

    file = msg.video or msg.document

    old_status = job.get("status_msg")
    if old_status and job.get("was_queued"):
        try:
            await old_status.delete()
        except Exception:
            pass
        status = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    elif old_status:
        status = old_status
        await safe_edit(status, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))
    else:
        status = await safe_reply(msg, f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**", reply_markup=cancel_button(task_id, uid))

    dest_dir   = os.path.join(DOWNLOAD_DIR, f"xsub_{uid}_{int(time.time())}")
    os.makedirs(dest_dir, exist_ok=True)
    orig_name  = sanitize_filename(getattr(file, "file_name", None) or f"video_{file.file_id[:8]}.mkv")
    video_path = os.path.join(dest_dir, orig_name)

    try:
        await _download_video(client, msg, video_path, status, task_id, uid)
    except asyncio.CancelledError:
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"**Cancelled!**", reply_markup=None)
    except Exception as e:
        log_error(f"run_extractsub_job: download failed (uid={uid})", e)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await _report_failure(msg, task_id, "Download failed", "download", exc=e,
                                     status=status, fallback="❌ **Download failed**")

    if is_cancelled(task_id):
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"**Cancelled!**", reply_markup=None)

    await safe_edit(status, f"**ꜱᴄᴀɴɴɪɴɢ ꜱᴜʙᴛɪᴛʟᴇ ᴛʀᴀᴄᴋꜱ...**", reply_markup=cancel_button(task_id, uid))
    streams = await probe_subtitle_streams(video_path)
    if not streams:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"❌ **No subtitle tracks found in this video.**", reply_markup=None)

    if is_cancelled(task_id):
        clear_cancelled(task_id)
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await safe_edit(status, f"**Cancelled!**", reply_markup=None)

    await safe_edit(status, f"**ᴇxᴛʀᴀᴄᴛɪɴɢ** {len(streams)} ꜱᴜʙᴛɪᴛʟᴇ ᴛʀᴀᴄᴋ(ꜱ)...", reply_markup=cancel_button(task_id, uid))
    base_name = os.path.splitext(orig_name)[0]
    extracted = []
    for idx, st in enumerate(streams):
        codec = st.get("codec_name", "")
        ext   = CODEC_EXT.get(codec, "srt")
        tags  = st.get("tags") or {}
        lang_tag  = (tags.get("language") or "").lower()
        lang_name = ISO_TO_LANG.get(lang_tag) or LANG_MAP.get(lang_tag) or "Unknown"
        out_name  = sanitize_filename(f"{base_name}.{lang_tag or idx + 1}.{ext}")
        out_path  = os.path.join(dest_dir, out_name)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", video_path, "-map", f"0:{st['index']}", "-c:s", "copy", out_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            extracted.append((out_path, out_name, lang_name))
        else:
            tlog(task_id, "extract",
                 f"stream {st['index']} ({codec or 'unknown'}) failed rc={proc.returncode}: "
                 f"{err.decode(errors='replace').strip()[-800:]}", "warn")

    if not extracted:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return await _report_failure(msg, task_id, "Subtitle extraction failed", "extract",
                                     detail=f"no subtitle stream could be extracted ({len(streams)} found)",
                                     status=status, fallback="❌ **Subtitle extraction failed.**")

    thumb      = await get_user_thumb(uid)
    auto_thumb = None
    if not thumb:
        auto_thumb = await extract_auto_thumb(video_path, uid)
        thumb      = auto_thumb
    upload_failed = False

    for i, (path, name, lang_name) in enumerate(extracted, 1):
        if is_cancelled(task_id):
            break
        await safe_edit(status, f"<b>ᴜᴘʟᴏᴀᴅɪɴɢ... {i}/{len(extracted)} ꜱᴜʙᴛɪᴛʟᴇ ꜰɪʟᴇ(ꜱ)...</b>", reply_markup=cancel_button(task_id, uid))
        try:
            await msg.reply_document(
                document=path, thumb=thumb, file_name=name,
                caption=f"<b>{name}</b>\n\n<b>Language</b>: {lang_name}",
                progress=make_progress_callback(status, f"ᴜᴘʟᴏᴀᴅɪɴɢ {i}/{len(extracted)}...", [time.time()], task_id, uid),
            )
        except Exception as e:
            log_error(f"run_extractsub_job: upload of subtitle {i}/{len(extracted)} failed (uid={uid})", e)
            tfail(task_id, "upload", f"upload of subtitle {i}/{len(extracted)} failed ({name})", e)
            upload_failed = True

    if upload_failed:
        await send_failure_log(msg, task_id, "Subtitle upload failed", None, "❌ **Some subtitle uploads failed**")

    clear_cancelled(task_id)
    try:
        await status.delete()
    except Exception:
        pass
    shutil.rmtree(dest_dir, ignore_errors=True)
    if auto_thumb and os.path.exists(auto_thumb): os.remove(auto_thumb)
    
