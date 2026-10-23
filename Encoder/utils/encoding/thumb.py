import os, asyncio, subprocess
from Encoder.config import THUMB_DIR

# Fetch user's saved thumbnail
async def get_user_thumb(uid: int):
    path = os.path.join(THUMB_DIR, f"{uid}.jpg")
    if os.path.exists(path):
        return path
    from Encoder.utils.database.access_db import db
    data = await db.get_user_thumb_bytes(uid)
    if not data:
        return None
    try:
        os.makedirs(THUMB_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return None

# Video duration via ffprobe
def _get_video_duration_sync(path: str) -> float:
    for args in [
        ["-analyzeduration", "100M", "-probesize", "100M",
         "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1"],
        ["-analyzeduration", "100M", "-probesize", "100M",
         "-select_streams", "v:0", "-show_entries", "stream=duration",
         "-of", "default=noprint_wrappers=1:nokey=1"],
    ]:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error"] + args + [path],
                capture_output=True, text=True, timeout=60
            )
            val = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
            if val and val not in ("N/A", ""):
                return float(val)
        except Exception:
            pass
    return 0.0

async def get_video_duration(path: str) -> float:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_video_duration_sync, path)

# Auto-generate thumbnail from mid-video frame
def _extract_auto_thumb_sync(video_path: str, uid: int):
    try:
        duration = _get_video_duration_sync(video_path)
        seek     = max(duration / 2, 1.0) if duration > 2 else 0.0
        out      = os.path.join(THUMB_DIR, f"auto_{uid}.jpg")
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(seek), "-i", video_path,
             "-vframes", "1", "-vf", "scale=320:-1", "-q:v", "2", out],
            capture_output=True, timeout=30
        )
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    except Exception:
        pass
    return None

async def extract_auto_thumb(video_path: str, uid: int):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract_auto_thumb_sync, video_path, uid)
