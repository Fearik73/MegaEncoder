import os
import asyncio

from Encoder.utils.tasks.cancel import is_cancelled, register_task, clear_task
from Encoder.utils.encoding.thumb import get_video_duration


from Encoder.config import SPLIT_SIZE
HARD_MAX   = 2_097_152_000
MARGIN     = 5_000_000


async def _run_ffmpeg(cmd, task_id, group_id, uid):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    register_task(task_id, proc, "encoding", group_id=group_id, uid=uid)
    try:
        _, err = await proc.communicate()
    finally:
        clear_task(task_id)
    return proc.returncode, (err or b"").decode(errors="replace").strip()


async def split_video(src_path, out_dir, base_name, ext, task_id, group_id, uid):
    os.makedirs(out_dir, exist_ok=True)
    size     = os.path.getsize(src_path)
    duration = await get_video_duration(src_path)
    if duration <= 0:
        raise Exception("split: couldn't read video duration")

    split_size = SPLIT_SIZE - MARGIN
    max_parts  = -(-size // max(split_size // 2, 1)) + 5   # safety against endless loops
    results    = []
    start_time = 0.0
    i          = 1
    map_all    = True

    while start_time < duration - 4 and i <= max_parts:
        if is_cancelled(task_id):
            return None
        name     = f"{base_name}.part{i:03}{ext}"
        out_path = os.path.join(out_dir, name)

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", str(start_time), "-i", src_path,
               "-fs", str(split_size)]
        if map_all:
            cmd += ["-map", "0"]
        cmd += ["-map_chapters", "-1", "-strict", "-2", "-c", "copy", out_path]

        code, err = await _run_ffmpeg(cmd, task_id, group_id, uid)
        if is_cancelled(task_id) or code in (-9, -15):
            return None
        if code != 0:
            if os.path.exists(out_path):
                os.remove(out_path)
            if map_all:
                map_all = False
                continue
            raise Exception(f"split: ffmpeg failed: {err[:200]}")

        out_size = os.path.getsize(out_path)
        if out_size > HARD_MAX:
            split_size -= (out_size - HARD_MAX) + MARGIN
            os.remove(out_path)
            continue

        part_dur = await get_video_duration(out_path)
        if part_dur <= 3:
            os.remove(out_path)
            break
        results.append((out_path, name))
        if abs(duration - part_dur) < 1:
            break
        start_time += part_dur
        i += 1

    if not results:
        raise Exception("split: no parts were produced")
    return results
