import time

from Encoder.utils.helpers import safe_edit, cancel_button

# Human-readable progress-bars
def human_size(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TB"

def human_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def uptime_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    y, d = divmod(d, 365)
    parts = []
    if y:
        parts.append(f"{y}y")
    if y or d:
        parts.append(f"{d}d")
    if y or d or h:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

def progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "▱" * length
    filled = int(length * min(current, total) / total)
    return "▰" * filled + "▱" * (length - filled)

# Progress callback factory for downloads/uploads
def make_progress_callback(msg, action: str, start_time: list, task_id: int, uid: int):
    last_update  = [0.0]
    last_content = [""]

    async def callback(current: int, total: int):
        if total <= 0:
            return
        now = time.time()
        if now - last_update[0] < 8 and current < total:
            return
        elapsed   = now - start_time[0]
        speed     = current / elapsed if elapsed > 0 else 0
        remaining = (total - current) / speed if speed > 0 else 0
        pct       = min(current * 100 / total, 100.0)
        bar       = progress_bar(current, total)
        text = (
            f"**{action}**\n\n"
            f"[{bar}] {pct:.1f}%\n"
            f"**ᴅᴏɴᴇ:** {human_size(current)} / {human_size(total)}\n"
            f"**ꜱᴘᴇᴇᴅ:** {human_size(speed)}/s\n"
            f"**ᴇᴛᴀ:** {human_time(remaining)}"
        )
        if text == last_content[0]:
            return
        last_content[0] = text
        last_update[0]  = now
        await safe_edit(msg, text, reply_markup=cancel_button(task_id, uid))

    return callback
