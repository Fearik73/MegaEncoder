import asyncio
import os
import sys
import time

from pyrogram import Client
from pyrogram.errors import RandomIdDuplicate

from Encoder.config import (
    API_ID, API_HASH, BOT_TOKEN, DB_CHANNEL, SESSION,
)

botStartTime = time.time()


# ---------------- Retry on RANDOM_ID_DUPLICATE ----------------
def _patch_random_id_duplicate():
    for _method_name in ("send_message", "send_document"):
        _original = getattr(Client, _method_name)

        def _make_patched(original):
            async def _patched(self, *args, **kwargs):
                for attempt in range(3):
                    try:
                        return await original(self, *args, **kwargs)
                    except RandomIdDuplicate:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(1)
            return _patched

        setattr(Client, _method_name, _make_patched(_original))


_patch_random_id_duplicate()


# ---------------- Log to file and stdout ----------------
LOG_FILE = os.environ.get("LOG_FILE", "bot_logs.txt")


class _Tee:
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self._streams:
            s.flush()


_log_fh = open(LOG_FILE, "a", buffering=1)
sys.stdout = _Tee(sys.stdout, _log_fh)
sys.stderr = _Tee(sys.stderr, _log_fh)


# ---------------- Bot client ----------------
class EncoderBot(Client):
    async def start(self):
        await super().start()
        me = await self.get_me()
        print(f"✅ Starting @{me.username}")

        if DB_CHANNEL:
            try:
                chat = await self.get_chat(DB_CHANNEL)
                print(f"✅ DB_CHANNEL Found: {chat.title} ({DB_CHANNEL})")
            except Exception as e:
                print(f"⚠️ DB_CHANNEL failed: {e}")


PLUGINS = [
    "subtitles", "start", "encode", "settings", "queue", "thumbnail",
    "metadata", "status", "update", "cancel", "auth", "leech", "usersettings",
]

app = EncoderBot(
    SESSION,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="Encoder.plugins", include=PLUGINS),
    sleep_threshold=60,
)
