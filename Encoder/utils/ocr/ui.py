import html

_SC = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢ"))

TITLE = "ᴏᴄʀ ꜱᴄᴀɴ"


def sc(s: str) -> str:
    return "".join(_SC.get(c.lower(), c) for c in s)


def esc(s) -> str:
    return html.escape(str(s))


def kv(k: str, v) -> str:
    return f"<b>{sc(k)}:</b> {v}"


def title(t: str) -> str:
    return f"<b>⧉ <u>{sc(t)}</u></b>"


def box(t: str, items: list, note: str = "") -> str:
    out = [title(t), ""]
    n = len(items)
    for i, it in enumerate(items):
        g = "┏" if i == 0 and n > 1 else ("┗" if i == n - 1 else "┣")
        out.append(f"<b>{g}</b> {it}")
    if note:
        out += ["", f"<blockquote>{note}</blockquote>"]
    return "\n".join(out)


def bar(frac: float, n: int = 10) -> str:
    f = int(n * min(max(frac, 0.0), 1.0))
    return "▰" * f + "▱" * (n - f)


def dur(sec: float) -> str:
    sec = int(max(sec, 0))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}ʜ {m:02d}ᴍ {s:02d}ꜱ"
    if m:
        return f"{m}ᴍ {s:02d}ꜱ"
    return f"{s}ꜱ"


def hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_time(s: str):
    parts = s.strip().split(":")
    if not 2 <= len(parts) <= 3 or not all(p.strip().isdigit() for p in parts):
        return None
    n = [int(p) for p in parts]
    if len(n) == 2:
        n = [0] + n
    if n[1] > 59 or n[2] > 59:
        return None
    return n[0] * 3600 + n[1] * 60 + n[2]


def wait_video() -> str:
    return box(TITLE, [kv("status", sc("waiting for video"))], sc("send me a video with hardsub. this session ends in 60 seconds"))


def expired() -> str:
    return box("ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ ❗", [kv("status", sc("no video received in 60 seconds"))], sc("use /ocr to start again"))


def ask_time(step: str, start, error: str = "") -> str:
    items = [kv("start", hms(start) if start else sc("beginning"))]
    if step == "start":
        what = sc("send the start time as ") + "<code>HH:MM:SS</code> " + sc("(example ") + "<code>00:02:35</code>" + sc("), or tap skip to begin at the start")
    else:
        what = sc("send the end time as ") + "<code>HH:MM:SS</code>" + sc(", or tap skip to scan till the end")
    return box("ꜱᴄᴀɴ ʀᴀɴɢᴇ", items, (f"<b>{error}</b>\n" if error else "") + what)


def queued(start, end, position: int) -> str:
    items = [
        kv("range", f"{hms(start or 0)} → {hms(end) if end else sc('end')}"),
        kv("position", f"#{position}"),
    ]
    return box("ᴀᴅᴅᴇᴅ ᴛᴏ Qᴜᴇᴜᴇ", items, sc("your ocr scan starts when its turn comes"))


def status(stage: str, frac=None, elapsed: float = 0.0, extra=()) -> str:
    items = [kv("status", sc(stage))]
    if frac is not None:
        items.append(f"[{bar(frac)}] {frac * 100:.0f}%")
    items += list(extra)
    items.append(kv("elapsed", dur(elapsed)))
    if frac and frac > 0.03:
        items.append(kv("eta", dur(elapsed * (1 - frac) / frac)))
    return box(TITLE, items)


def done(lines: int, took: float) -> str:
    items = [kv("lines", lines), kv("time taken", dur(took))]
    return box("ᴅᴏɴᴇ ✅", items, sc("the .srt and .ass files are above"))


def nothing() -> str:
    return box("ɴᴏ ꜱᴜʙᴛɪᴛʟᴇꜱ", [kv("status", sc("empty"))], sc("no hardsub text was found"))


def cancelled() -> str:
    return box("ᴄᴀɴᴄᴇʟʟᴇᴅ ❌", [kv("status", sc("stopped"))])


def failed(err) -> str:
    return box("ꜰᴀɪʟᴇᴅ ❌", [kv("status", sc("error"))], f"<code>{esc(err)}</code>")
  
