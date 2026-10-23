import os
from dotenv import load_dotenv

if os.path.exists("config.env"):
    load_dotenv("config.env")
else:
    load_dotenv()


def _env(name, default):
    value = os.environ.get(name)
    return default if value is None or not value.strip() else value.strip()


def _required(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise SystemExit(f"❌ Missing required variable {name}.\nFill it in config.env (see config.env.sample).")
    return value.strip()


# ---------------- Telegram / bot ----------------
API_ID = int(_required("API_ID"))
API_HASH = _required("API_HASH")
BOT_TOKEN = _required("BOT_TOKEN")
SESSION = os.environ.get("SESSION", "")

ADMIN_IDS = set(int(x.strip()) for x in _required("ADMIN_IDS").split(",") if x.strip())
DB_CHANNEL = int(_env("DB_CHANNEL", "0"))   # 0 = disabled

# ---------------- Database ----------------
DB_URL = _required("DB_URL")
DB_NAME = _env("DB_NAME", "")

# ---------------- Updates (/update, update.sh) ----------------
UPSTREAM_REPO = os.environ.get("UPSTREAM_REPO", "").strip()      # e.g. https://github.com/you/Encoder.git
UPSTREAM_BRANCH = os.environ.get("UPSTREAM_BRANCH", "").strip()  # empty = current branch

# ---------------- Folders ----------------
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "./downloads")
OUTPUT_DIR   = os.environ.get("OUTPUT_DIR",   "./output")
THUMB_DIR    = os.environ.get("THUMB_DIR",    "./thumbs")

# Auto create
for folder in [DOWNLOAD_DIR, OUTPUT_DIR, THUMB_DIR]:
    os.makedirs(folder, exist_ok=True)

# ---------------- Split big files ----------------
SPLIT_SIZE = int(os.environ.get("SPLIT_SIZE", "2000000000"))

# ---------------- Default encode settings ----------------
DEFAULT_CODEC         = _env("DEFAULT_CODEC", "")
DEFAULT_CRF           = _env("DEFAULT_CRF", "")
DEFAULT_PRESET        = _env("DEFAULT_PRESET", "")
DEFAULT_RESOLUTION    = _env("DEFAULT_RESOLUTION", "")
DEFAULT_TUNE          = _env("DEFAULT_TUNE", "")
DEFAULT_AUDIO_CODEC   = _env("DEFAULT_AUDIO_CODEC", "")
DEFAULT_AUDIO_BITRATE = _env("DEFAULT_AUDIO_BITRATE", "")
DEFAULT_AUDIO_CHANNEL = _env("DEFAULT_AUDIO_CHANNEL", "")
DEFAULT_BIT_DEPTH     = _env("DEFAULT_BIT_DEPTH", "")
DEFAULT_FPS           = _env("DEFAULT_FPS", "")
DEFAULT_SEND_TYPE     = _env("DEFAULT_SEND_TYPE", "")
DEFAULT_RENAME_SOURCE = _env("DEFAULT_RENAME_SOURCE", "")
