import os
import re
import time
import asyncio

from Encoder.utils.tasks.cancel import is_cancelled

from Encoder.utils.naming import VIDEO_EXTS, natural_key
from Encoder.utils.logs.tasklog import tlog

_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4,
          "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4}


_PROG_RE = re.compile(r"([\d.]+)%.*?\sof\s([\d.]+)\s*([KMGT]?i?B)", re.IGNORECASE)


def _dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _collect_files(dest_dir):
    found = []
    for root, _, files in os.walk(dest_dir):
        for f in files:
            if f.startswith("."):
                continue
            found.append(os.path.join(root, f))
    found.sort(key=natural_key)
    if len(found) > 1:
        found = [p for p in found if os.path.splitext(p)[1].lower() in VIDEO_EXTS]
        if not found:
            raise Exception("Mega folder has no video files")
    return found


async def mega_download(url, dest_dir, status_msg, task_id: int, uid: int):
    from Encoder.utils.helpers import safe_edit, cancel_button
    from Encoder.utils.display_progress import make_progress_callback, human_size

    os.makedirs(dest_dir, exist_ok=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            "megadl", "--path", dest_dir, url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        raise Exception("megadl not found — install megatools")

    tlog(task_id, "mega", f"megadl --path {dest_dir} {url}")
    start = time.time()
    progress_cb = make_progress_callback(status_msg, "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...", [start], task_id, uid)
    tail = []
    seen_progress = False
    last_poll = 0.0

    try:
        while True:
            if is_cancelled(task_id):
                proc.kill()
                await proc.wait()
                raise asyncio.CancelledError()

            try:
                chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=2)
            except asyncio.TimeoutError:
                chunk = None

            if chunk == b"":
                break

            if chunk:
                text = chunk.decode(errors="replace")
                for line in re.split(r"[\r\n]+", text):
                    line = line.strip()
                    if line and not _PROG_RE.search(line):
                        tail.append(line)
                        tail[:] = tail[-8:]
                matches = _PROG_RE.findall(text)
                if matches:
                    pct, size, unit = matches[-1]
                    mult = _UNITS.get(unit.upper(), 0)
                    total = int(float(size) * mult)
                    if total > 0:
                        seen_progress = True
                        await progress_cb(int(total * float(pct) / 100), total)

            # progress line not recognised - show how much has landed on disk
            now = time.time()
            if not seen_progress and now - last_poll > 10:
                last_poll = now
                done = _dir_size(dest_dir)
                await safe_edit(
                    status_msg,
                    f"**ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...**\n\n**ᴅᴏɴᴇ:** {human_size(done)}",
                    reply_markup=cancel_button(task_id, uid),
                )

        rc = await proc.wait()
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

    if is_cancelled(task_id):
        raise asyncio.CancelledError()
    tlog(task_id, "mega", f"megadl exit code {rc}; last output: {' | '.join(tail[-5:])}", "info" if rc == 0 else "error")
    if rc != 0:
        raise Exception("megadl failed: " + " | ".join(tail[-3:]))

    files = _collect_files(dest_dir)
    if not files:
        raise Exception("Mega finished but no file was saved")
    return [(p, os.path.basename(p)) for p in files]
