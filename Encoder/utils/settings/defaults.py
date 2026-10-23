from Encoder.config import (
    DEFAULT_CODEC, DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_RESOLUTION, DEFAULT_TUNE,
    DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE, DEFAULT_AUDIO_CHANNEL,
    DEFAULT_BIT_DEPTH, DEFAULT_FPS, DEFAULT_SEND_TYPE, DEFAULT_RENAME_SOURCE,
)
from Encoder.utils.settings.settings import (
    ACODEC_INPUT, ACODEC_LABEL, ACODEC_MAX_KBPS, VALID_CHANNELS, VALID_PRESETS,
    VALID_TUNES, VALID_RENAME_SOURCES, is_valid_resolution, parse_fps, parse_kbps,
)


# ---------------- check the defaults from config.env once, when the bot starts ----------------
def _check_defaults():
    g = globals()
    problems = []

    def bad(name, hint):
        problems.append(f"  {name} = {g[name]!r}  ->  {hint}")

    codec = str(DEFAULT_CODEC).lower()
    codec = {"x264": "libx264", "x265": "libx265"}.get(codec, codec)
    if codec in ("libx264", "libx265"):
        g["DEFAULT_CODEC"] = codec
    else:
        bad("DEFAULT_CODEC", "use libx264 or libx265")

    if str(DEFAULT_CRF).isdigit() and 0 <= int(DEFAULT_CRF) <= 51:
        g["DEFAULT_CRF"] = int(DEFAULT_CRF)
    else:
        bad("DEFAULT_CRF", "use a number from 0 to 51")

    if str(DEFAULT_PRESET).lower() in VALID_PRESETS:
        g["DEFAULT_PRESET"] = str(DEFAULT_PRESET).lower()
    else:
        bad("DEFAULT_PRESET", "use one of: " + ", ".join(VALID_PRESETS))

    if str(DEFAULT_TUNE).lower() in VALID_TUNES:
        g["DEFAULT_TUNE"] = str(DEFAULT_TUNE).lower()
    else:
        bad("DEFAULT_TUNE", "use one of: " + ", ".join(VALID_TUNES))

    if is_valid_resolution(str(DEFAULT_RESOLUTION).lower()):
        g["DEFAULT_RESOLUTION"] = str(DEFAULT_RESOLUTION).lower()
    else:
        bad("DEFAULT_RESOLUTION", "use original, or width x height with even numbers like 1280x720")

    acodec = ACODEC_INPUT.get(str(DEFAULT_AUDIO_CODEC).lower())
    if acodec:
        g["DEFAULT_AUDIO_CODEC"] = acodec
    else:
        bad("DEFAULT_AUDIO_CODEC", "use copy, aac, mp3, opus, ac3, flac or wav")

    if str(DEFAULT_AUDIO_CHANNEL) in VALID_CHANNELS:
        g["DEFAULT_AUDIO_CHANNEL"] = str(DEFAULT_AUDIO_CHANNEL)
    else:
        bad("DEFAULT_AUDIO_CHANNEL", "use one of: " + ", ".join(VALID_CHANNELS))

    kbps = parse_kbps(DEFAULT_AUDIO_BITRATE)
    if str(DEFAULT_AUDIO_BITRATE).lower() == "copy":
        g["DEFAULT_AUDIO_BITRATE"] = "copy"
    elif kbps is None or kbps < 8:
        bad("DEFAULT_AUDIO_BITRATE", "use copy or a value like 64k")
    elif acodec and ACODEC_MAX_KBPS.get(acodec) and kbps > ACODEC_MAX_KBPS[acodec]:
        bad("DEFAULT_AUDIO_BITRATE", f"{ACODEC_LABEL[acodec]} supports max {ACODEC_MAX_KBPS[acodec]}k")
    else:
        g["DEFAULT_AUDIO_BITRATE"] = f"{kbps}k"

    depth = str(DEFAULT_BIT_DEPTH).lower().removesuffix("bit").strip()
    if depth in ("8", "10"):
        g["DEFAULT_BIT_DEPTH"] = depth
    else:
        bad("DEFAULT_BIT_DEPTH", "use 8 or 10")

    fps = parse_fps(DEFAULT_FPS)
    if fps is None:
        bad("DEFAULT_FPS", "use copy or a number like 24, 23.976, 24000/1001")
    else:
        g["DEFAULT_FPS"] = fps

    if str(DEFAULT_SEND_TYPE).lower() in ("document", "media"):
        g["DEFAULT_SEND_TYPE"] = str(DEFAULT_SEND_TYPE).lower()
    else:
        bad("DEFAULT_SEND_TYPE", "use document or media")

    source = {"file": "filename", "name": "filename"}.get(str(DEFAULT_RENAME_SOURCE).lower(), str(DEFAULT_RENAME_SOURCE).lower())
    if source in VALID_RENAME_SOURCES:
        g["DEFAULT_RENAME_SOURCE"] = source
    else:
        bad("DEFAULT_RENAME_SOURCE", "use filename, caption or both")

    if problems:
        raise ValueError("Wrong default settings in config.env:\n" + "\n".join(problems))


_check_defaults()
