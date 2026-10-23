import os
import re

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".ts", ".flv", ".wmv", ".mpg", ".mpeg"}

_PLACEHOLDER = re.compile(r"\{(episode|season|quality)\}", re.IGNORECASE)
_RESOLUTIONS = {240, 360, 480, 540, 576, 720, 1080, 1440, 2160}

_SEASON_PATTERNS = [
    re.compile(r"S(\d{1,2})[\s._-]*E\d{1,4}", re.IGNORECASE),
    re.compile(r"Season[\s._-]*(\d{1,2})", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])S(\d{1,2})(?![A-Za-z0-9])", re.IGNORECASE),
]
_EPISODE_PATTERNS = [
    re.compile(r"S\d{1,2}[\s._-]*E(\d{1,4})", re.IGNORECASE),
    re.compile(r"(?<![a-z0-9])(?:episode|ep|e)[\s._-]*(\d{1,4})(?!\d)", re.IGNORECASE),
    re.compile(r"(?<=[\s\]\)])-\s*(\d{1,4})(?:v\d+)?(?=[\s.\[\(_]|$)"),
]
_BRACKET_NUM = re.compile(r"\[(\d{2,4})\]")
_LOOSE_NUM   = re.compile(r"(?<![\d.xXhH_])(\d{2,4})(?![\d.pPiIkKxX])")
_QUALITY     = re.compile(r"(?<![0-9])(2160|1440|1080|720|576|540|480|360|240)[pP]|(?<![A-Za-z0-9])4[kK](?![A-Za-z0-9])")


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def has_placeholders(template: str) -> bool:
    return bool(_PLACEHOLDER.search(template or ""))


def _plausible_number(text: str) -> bool:
    n = int(text)
    return n not in _RESOLUTIONS and not 1900 <= n <= 2099


def parse_media_info(filename: str):
    base = os.path.splitext(filename)[0]

    season = None
    for pat in _SEASON_PATTERNS:
        m = pat.search(base)
        if m:
            season = f"{int(m.group(1)):02d}"
            break

    episode = None
    for pat in _EPISODE_PATTERNS:
        m = pat.search(base)
        if m:
            episode = m.group(1)
            break
    if episode is None:
        for m in _BRACKET_NUM.finditer(base):
            if _plausible_number(m.group(1)):
                episode = m.group(1)
                break
    if episode is None:
        loose = [m.group(1) for m in _LOOSE_NUM.finditer(base) if _plausible_number(m.group(1))]
        if loose:
            episode = loose[-1]
    if episode is not None and len(episode) < 2:
        episode = episode.zfill(2)

    quality = None
    m = _QUALITY.search(base)
    if m:
        quality = f"{m.group(1)}p" if m.group(1) else "2160p"

    return {"season": season, "episode": episode, "quality": quality}


def apply_placeholders(template: str, source_name: str, target_quality=None):
    info = parse_media_info(source_name)
    values = {
        "episode": info["episode"],
        "season":  info["season"] or "01",
        "quality": target_quality or info["quality"],
    }
    return _PLACEHOLDER.sub(lambda m: values[m.group(1).lower()] or "UNKNOWN", template)


def rename_items(items, template, target_quality=None):
    if not template:
        return list(items)
    apply_to_all = has_placeholders(template) or len(items) == 1
    out = []
    for idx, (path, name) in enumerate(items):
        if not (apply_to_all or idx == 0):
            out.append((path, name))
            continue
        new = apply_placeholders(template, name, target_quality)
        if not new.lower().endswith(tuple(VIDEO_EXTS)):
            new += os.path.splitext(name)[1]
        out.append((path, new))
    return out
