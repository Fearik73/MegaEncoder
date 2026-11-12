import os

VARS = {
    "OCR_MODEL":        ("medium", "choice", ("medium", "small", "tiny", "old"),
                         "OCR model size: medium, small, tiny or old."),
    "OCR_WORKERS":      (3, "int", (1, 16),
                         "Parallel OCR processes. Used only for scans longer than OCR_PARALLEL_MIN."),
    "OCR_PARALLEL_MIN": (180.0, "float", (0, 86400),
                         "Workers are used only for scans longer than this (seconds)."),
    "OCR_FPS":          (16, "int", (1, 60),
                         "Frames scanned per second."),
    "OCR_STRIP":        (0.25, "float", (0.05, 1),
                         "Bottom part of the frame that is scanned (0.25 = bottom 25%)."),
    "OCR_MARGIN":       (0.14, "float", (0, 0.45),
                         "Ignore this much at the left and right edge (0.14 = 14%)."),
    "OCR_COLOR":        ("white", "choice", ("white", "any"),
                         "white = ignore coloured VFX, any = plain brightness."),
    "OCR_STROKE":       (25, "int", (1, 200),
                         "Thickest text stroke (px). Bigger bright areas (gray sky, fog) are ignored."),
    "OCR_LIFT":         (20, "int", (0, 255),
                         "Text must be this much brighter than its surroundings. 0 = off."),
    "OCR_PERSIST":      (3, "int", (0, 10),
                         "Keep text only if present in N consecutive frames (3 = 3 frames, 5 = 5 frames). 0 = off (1 and 2 also off). 3 is recommended: 5 and above can erase text of fading or short subtitles."),
    "OCR_OUTLINE":      (1, "int", (0, 1),
                         "1 = remove bright background noise (sky, floor, flowers) that has no dark outline around it; subtitle text is kept. 0 = off, use it if your hardsub has no outline."),
    "OCR_FOCUS":        (1, "int", (0, 1),
                         "1 = keep only character-sized shapes in the main text row, 0 = off."),
    "OCR_GAP":          (140, "int", (1, 2000),
                         "Shapes further apart than this (px) are treated as separate things. The biggest group is the subtitle."),
    "OCR_CHAR":         (90, "int", (10, 500),
                         "Biggest single character height (px at 1920 wide)."),
    "OCR_WHITE":        (190, "int", (0, 255),
                         "Brightness of subtitle text (0-255)."),
    "OCR_SIM":          (0.6, "float", (0, 1),
                         "Below this similarity = a new subtitle line."),
    "OCR_MIN_LINE":     (0.4, "float", (0, 10),
                         "Ignore lines shorter than this (seconds)."),
    "OCR_MIN_FRAC":     (0.0003, "float", (0, 1),
                         "Minimum bright pixels (fraction of the strip)."),
    "OCR_MAX_FRAC":     (0.12, "float", (0, 1),
                         "Maximum bright pixels (fraction of the strip)."),
    "OCR_MIN_CHARS":    (2, "int", (1, 20),
                         "Lines with fewer characters are dropped. 1 = single-character lines are kept."),
    "OCR_FLAG_CONF":    (0.8, "float", (0, 1),
                         "Lines read with less confidence than this get flagged for re-check."),
    "ASS_FONT":         ("Arial", "str", None,
                         "Font of the first .ass file."),
    "ASS_FONT_CJK":     ("Noto Sans CJK SC", "str", None,
                         "Font of the second (CJK) .ass file."),
    "ASS_GAP":          (8, "int", (0, 300),
                         "Gap above the hardsub (px on a 1080 canvas)."),
    "ASS_OPEN":         ("Good Subtitled by Fearik\\N[Telegram] - @Donghua_Heavens", "str", None,
                         "Opening credit, shown before the first subtitle (needs a start time, at least 8s). \\N = new line, - = off."),
    "ASS_THANKS":       ("Thanks for watching!\\N[Telegram] - @Donghua_Heavens", "str", None,
                         "Ending credit, shown after the last subtitle. \\N = new line, - = off."),
    "ASS_CREDIT_SEC":   (6.0, "float", (1, 30),
                         "How long each credit stays on screen (seconds)."),
}

RESTART_VARS = ("OCR_MODEL", "OCR_WORKERS")

ENV = {}


def parse(key: str, text) -> object:
    default, kind, rule, _ = VARS[key]
    text = str(text).strip()
    if kind in ("int", "float"):
        try:
            value = int(text) if kind == "int" else float(text)
        except ValueError:
            raise ValueError("send a " + ("whole number" if kind == "int" else "number"))
        if not rule[0] <= value <= rule[1]:
            raise ValueError(f"value must be between {rule[0]} and {rule[1]}")
        return value
    if kind == "choice":
        text = text.lower()
        if text not in rule:
            raise ValueError("use one of: " + ", ".join(rule))
        return text
    if not text:
        raise ValueError("value can't be empty")
    return text


def _from_env():
    g = globals()
    for key, (default, *_rest) in VARS.items():
        value = default
        raw = os.environ.get(key)
        if raw is not None and raw.strip():
            try:
                value = parse(key, raw)
            except ValueError as e:
                print(f"⚠️ {key} in config.env ignored ({e}), using {default!r}")
        ENV[key] = value
        g[key] = value


def snapshot() -> dict:
    g = globals()
    return {key: g[key] for key in VARS}


def apply(values: dict):
    g = globals()
    for key, value in (values or {}).items():
        if key not in VARS:
            continue
        try:
            g[key] = parse(key, value)
        except ValueError:
            pass


def set_value(key: str, value):
    globals()[key] = value


def reset_value(key: str):
    globals()[key] = ENV[key]


_from_env()
