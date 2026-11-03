import re

TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
RES = {"1080p": (1920, 1080, 60, 3, 1, 10, 40), "4k": (3840, 2160, 120, 6, 2, 20, 80)}


def _sec(g):
    h, m, s, ms = g
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeError:
            pass
    return data.decode("latin-1")


def parse_srt(text: str):
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = TIME.search(line)
            if m:
                g = m.groups()
                body = [x.strip() for x in lines[i + 1 :] if x.strip()]
                if body:
                    out.append((_sec(g[:4]), _sec(g[4:]), body))
                break
    return out


def _time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _text(line: str) -> str:
    return re.sub(r"<[^>]+>", "", line).replace("{", "(").replace("}", ")")


def default_margin(quality: str) -> int:
    return RES[quality][6]


def max_margin(quality: str) -> int:
    return RES[quality][1] // 2


def build_ass(entries, quality: str, margin: int, font: str) -> str:
    w, h, size, _, _, side, _ = RES[quality]
    head = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"0,0,2,{side},{side},{margin},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = []
    for s, e, body in entries:
        text = "\\N".join(_text(x) for x in body)
        rows.append(f"Dialogue: 0,{_time(s)},{_time(e)},Default,,0,0,0,,{text}")
    return head + "\n".join(rows) + "\n"


def build_ass_geo(entries, width: int, height: int, size: int, margin: int, font: str) -> str:
    side = round(height / 54)
    head = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"0,0,2,{side},{side},{margin},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = []
    for s, e, body, *own in entries:
        text = "\\N".join(_text(x) for x in body)
        mv = own[0] if own and own[0] else 0
        rows.append(f"Dialogue: 0,{_time(s)},{_time(e)},Default,,0,0,{mv},,{text}")
    return head + "\n".join(rows) + "\n"


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def auto_layout(metas: list, video_w: int, video_h: int, gap: float):
    play_h = 2160
    play_w = max(2, round(play_h * video_w / video_h / 2) * 2)
    base = [m for m in metas if m.get("bands", 1) == 1] or metas
    h1 = _median([m["h1"] for m in base]) * play_h
    top = _median([m["top"] for m in base]) * play_h
    size = max(24, round(h1 / 0.9))
    margin = round((play_h - top) + gap * h1)
    return play_w, play_h, size, margin, h1


def line_margin(meta: dict, play_h: int, h1: float, gap: float) -> int:
    return round(play_h - meta["top"] * play_h + gap * h1)
