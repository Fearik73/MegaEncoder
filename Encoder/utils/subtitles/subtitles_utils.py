import os, re, json, subprocess, asyncio

# Subtitle extensions, codec mapping, and language detection tables
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".ttml"}

CODEC_EXT = {
    "subrip":            "srt",
    "srt":                "srt",
    "ass":                "ass",
    "ssa":                "ssa",
    "webvtt":             "vtt",
    "mov_text":           "srt",
    "dvd_subtitle":       "sub",
    "hdmv_pgs_subtitle":  "sup",
}

LANG_MAP = {
    "english": "English", "eng": "English",
    "hindi": "Hindi",
    "japanese": "Japanese", "jap": "Japanese",
    "indonesian": "Indonesian", "indo": "Indonesian",
    "spanish": "Spanish",
    "french": "French",
    "german": "German",
    "italian": "Italian",
    "portuguese": "Portuguese",
    "russian": "Russian",
    "chinese": "Chinese",
    "korean": "Korean",
    "arabic": "Arabic",
    "thai": "Thai",
    "vietnamese": "Vietnamese",
    "turkish": "Turkish",
    "urdu": "Urdu",
    "nepali": "Nepali",
    "malay": "Malay",
    "dutch": "Dutch",
    "swedish": "Swedish",
    "norwegian": "Norwegian",
    "danish": "Danish",
    "finnish": "Finnish",
    "polish": "Polish",
    "czech": "Czech",
    "greek": "Greek",
    "hebrew": "Hebrew",
    "ukrainian": "Ukrainian",
    "romanian": "Romanian",
    "hungarian": "Hungarian",
    "persian": "Persian", "farsi": "Persian",
    "sinhala": "Sinhala",
    "burmese": "Burmese",
    "khmer": "Khmer",
}

LANG_ISO = {
    "English": "eng", "Hindi": "hin", "Japanese": "jpn", "Indonesian": "ind",
    "Spanish": "spa", "French": "fre", "German": "ger", "Italian": "ita",
    "Portuguese": "por", "Russian": "rus", "Chinese": "chi", "Korean": "kor",
    "Arabic": "ara", "Thai": "tha", "Vietnamese": "vie", "Turkish": "tur",
    "Urdu": "urd", "Nepali": "nep", "Malay": "may", "Dutch": "dut",
    "Swedish": "swe", "Norwegian": "nor", "Danish": "dan", "Finnish": "fin",
    "Polish": "pol", "Czech": "cze", "Greek": "gre", "Hebrew": "heb",
    "Ukrainian": "ukr", "Romanian": "rum", "Hungarian": "hun", "Persian": "per",
    "Sinhala": "sin", "Burmese": "bur", "Khmer": "khm", "Unknown": "und",
}


# Language detection from subtitle filename
def detect_language(filename: str) -> str:
    base = os.path.splitext(filename)[0]
    for tok in re.split(r'[^A-Za-z]+', base):
        name = LANG_MAP.get(tok.lower())
        if name:
            return name
    return "Unknown"


# Detect existing subtitle streams via ffprobe
def _ffprobe_subtitle_streams_sync(path: str):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=index,codec_name:stream_tags=language,title",
             "-of", "json", path],
            capture_output=True, text=True, timeout=60,
        )
        return json.loads(r.stdout or "{}").get("streams", [])
    except Exception:
        return []


async def probe_subtitle_streams(path: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _ffprobe_subtitle_streams_sync, path)


# Active extract-sub job tracking
_active_xsub_uids: set = set()

def mark_xsub_active(uid: int):
    _active_xsub_uids.add(uid)

def mark_xsub_done(uid: int):
    _active_xsub_uids.discard(uid)

def is_xsub_active(uid: int) -> bool:
    return uid in _active_xsub_uids
