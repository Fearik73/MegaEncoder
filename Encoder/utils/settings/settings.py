import re

VALID_PRESETS     = ["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"]

VALID_RESOLUTIONS = ["original","1920x1080","1280x720","960x540","854x480","640x360","426x240"]

VALID_ACODECS     = ["copy","aac","libmp3lame","libopus","ac3","flac","pcm_s16le"]

VALID_RENAME_SOURCES = ["filename", "caption", "both"]

RENAME_LABEL         = {"filename": "File Name", "caption": "Caption", "both": "Both"}

VALID_TUNES       = ["none","film","animation","grain","stillimage","fastdecode","zerolatency"]

_CUSTOM_RES_RE = re.compile(r"^\d{2,5}x\d{2,5}$")

def is_valid_resolution(value: str) -> bool:
    if value in VALID_RESOLUTIONS:
        return True
    if not _CUSTOM_RES_RE.match(value):
        return False
    w, h = value.split("x")
    w, h = int(w), int(h)
    return 16 <= w <= 7680 and 16 <= h <= 4320 and w % 2 == 0 and h % 2 == 0

# ---------------- Audio rules ----------------
ACODEC_INPUT = {
    "copy": "copy", "aac": "aac", "mp3": "libmp3lame", "libmp3lame": "libmp3lame",
    "opus": "libopus", "libopus": "libopus", "ac3": "ac3", "flac": "flac",
    "wav": "pcm_s16le", "pcm_s16le": "pcm_s16le",
}

ACODEC_LABEL = {
    "copy": "Copy", "aac": "AAC", "libmp3lame": "MP3", "libopus": "Opus",
    "ac3": "AC3", "flac": "FLAC", "pcm_s16le": "WAV",
}

# Highest bitrate (kbps) each lossy codec accepts
ACODEC_MAX_KBPS = {"libmp3lame": 320, "libopus": 512, "aac": 576, "ac3": 640}

# Lossless / pass-through codecs: no bitrate applies
ACODEC_NO_BITRATE = {"copy", "flac", "pcm_s16le"}

# Highest channel count each codec accepts (default 8)
ACODEC_MAX_CH = {"libmp3lame": 2, "ac3": 6}

CHANNEL_COUNT = {"1": 1, "2": 2, "5.1": 6, "7.1": 8}

CHANNEL_LABEL = {"copy": "Copy", "1": "Mono (1)", "2": "Stereo (2)", "5.1": "5.1", "7.1": "7.1"}

VALID_CHANNELS = list(CHANNEL_LABEL)

_KBPS_RE = re.compile(r"^(\d{1,4})k?$", re.IGNORECASE)

_FPS_FRAC_RE = re.compile(r"^(\d{1,6})/(\d{1,6})$")

def parse_kbps(value: str):
    m = _KBPS_RE.match(str(value).strip())
    return int(m.group(1)) if m else None

def adjust_for_codec(codec: str, channel: str, bitrate: str):
    notes = []
    max_ch = ACODEC_MAX_CH.get(codec, 8)
    if channel in CHANNEL_COUNT and CHANNEL_COUNT[channel] > max_ch:
        new_ch = "2" if max_ch == 2 else "5.1"
        notes.append(f"Audio channel → {CHANNEL_LABEL[new_ch]} ({ACODEC_LABEL.get(codec, codec)} supports max {max_ch} ch)")
        channel = new_ch
    limit = ACODEC_MAX_KBPS.get(codec)
    kbps = parse_kbps(bitrate) if bitrate != "copy" else None
    if limit and kbps and kbps > limit:
        notes.append(f"Audio bitrate → {limit}k ({ACODEC_LABEL.get(codec, codec)} max)")
        bitrate = f"{limit}k"
    return channel, bitrate, notes

def parse_fps(value: str):
    v = str(value).strip().lower()
    if v in ("copy", "auto"):
        return "copy"
    m = _FPS_FRAC_RE.match(v)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return v if b and 1 <= a / b <= 240 else None
    try:
        f = float(v)
    except ValueError:
        return None
    if not 1 <= f <= 240:
        return None
    return str(int(f)) if f == int(f) else str(f)
