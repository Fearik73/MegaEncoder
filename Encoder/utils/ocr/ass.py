import re

TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
RES = {"1080p": (1920, 1080, 60, 3, 1, 10, 40), "4k": (3840, 2160, 120, 6, 2, 20, 80)}

BASE_H = 1080
SIZE = 60
FALLBACK_MARGIN = 110
TOP_MIN, TOP_MAX = 0.78, 0.97
OWN_RISE = 0.10
FIRST_N = 6
TOL = 0.012
OPEN_AT = 2.0
END_AFTER = 2.0
GOLD = "&H4EC1F2&"


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


def build_ass_geo(entries, width: int, height: int, size: int, margin: int, font: str, credits=()) -> str:
    side = round(height / 54)
    k = height / BASE_H
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
        f"0,0,2,{side},{side},{margin},1\n"
        f"Style: Credit,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,{0.5 * k:g},0,1,"
        f"{2 * k:g},{k:g},2,{side},{side},{margin},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = []
    for s, e, body, *own in entries:
        text = "\\N".join(_text(x) for x in body)
        mv = own[0] if own and own[0] else 0
        rows.append((s, f"Dialogue: 0,{_time(s)},{_time(e)},Default,,0,0,{mv},,{text}"))
    for s, e, raw in credits:
        rows.append((s, f"Dialogue: 1,{_time(s)},{_time(e)},Credit,,0,0,0,,{_credit_text(raw, e - s, k)}"))
    rows.sort(key=lambda r: r[0])
    return head + "\n".join(r for _, r in rows) + "\n"


def _hl(m) -> str:
    return "{\\c" + GOLD + "}" + m.group(1) + "{\\c&HFFFFFF&}"


def _credit_text(raw: str, dur: float, k: float = 1.0) -> str:
    raw = raw.strip().replace("\\n", "\\N").replace("{", "(").replace("}", ")")
    out = []
    for i, part in enumerate(raw.split("\\N")):
        part = re.sub(r"(?<=\bby )(\w+)", _hl, part)
        part = re.sub(r"(@\w+)", _hl, part)
        out.append((f"{{\\fs{round(48 * k)}\\fsp{1.5 * k:g}}}" if i else "") + part)
    fade = int(min(600, dur * 1000 / 4))
    return "{\\fad(" + str(fade) + "," + str(fade) + f")\\blur{1.2 * k:g}}}" + "\\N".join(out)


def credit_lines(t_start, last_end, texts, sec: float, final: bool):
    """texts = (opening, thanks). A text that is empty or "-" is skipped."""
    use = [(i, t) for i, t in enumerate(texts) if t and t.strip() not in ("", "-")]
    out = []
    for i, t in use:
        if i == 0 and t_start and t_start >= OPEN_AT + sec:
            out.append((OPEN_AT, OPEN_AT + sec, t))
    if final and last_end is not None:
        at = last_end + END_AFTER
        for i, t in use:
            if i:
                out.append((at, at + sec, t))
                at += sec
    return out


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _common(xs):
    if not xs:
        return None
    med = _median(xs)
    best = max(xs, key=lambda x: (sum(abs(x - y) <= TOL for y in xs), -abs(x - med)))
    return _median([y for y in xs if abs(y - best) <= TOL])


def auto_layout(metas: list, video_w: int, video_h: int, gap: float):
    play_w, play_h = video_w, video_h
    k = play_h / BASE_H
    base = [m for m in metas if m.get("bands", 1) == 1] or metas
    base = sorted(base, key=lambda m: m.get("start", 0.0))
    tops = [m["top"] for m in base if TOP_MIN <= m["top"] <= TOP_MAX]
    if len(tops) > 200:
        tops = tops[:: -(-len(tops) // 200)]
    top = _common(tops)
    margin = round((1 - top) * play_h + gap * k) if top is not None else round(FALLBACK_MARGIN * k)
    return play_w, play_h, round(SIZE * k), margin, top


def base_height(metas: list):
    base = [m for m in metas if m.get("bands", 1) == 1 and "h1" in m]
    base = sorted(base, key=lambda m: m.get("start", 0.0))[:FIRST_N]
    return _median([m["h1"] for m in base]) if base else None


def line_margin(meta: dict, play_h: int, base_top, gap: float, base_h=None):
    top = meta["top"]
    if base_top is None or not (base_top - OWN_RISE <= top <= TOP_MAX):
        return None
    g = gap * play_h / BASE_H
    floor = round((1 - base_top) * play_h + g)
    rows = max(1, meta.get("bands", 1))
    rise = (rows - 1) * (base_h * 1.5 if base_h else OWN_RISE) * play_h
    return max(floor, min(round((1 - top) * play_h + g), floor + round(rise)))

                  
