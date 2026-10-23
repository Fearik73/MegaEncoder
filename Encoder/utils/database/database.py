import logging
import motor.motor_asyncio

from Encoder.utils.settings.settings import ACODEC_INPUT
from Encoder.utils.settings.defaults import (
    DEFAULT_CODEC, DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_AUDIO_BITRATE,
    DEFAULT_AUDIO_CODEC, DEFAULT_RESOLUTION, DEFAULT_TUNE, DEFAULT_SEND_TYPE,
    DEFAULT_AUDIO_CHANNEL, DEFAULT_BIT_DEPTH, DEFAULT_FPS, DEFAULT_RENAME_SOURCE,
)

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "codec":         DEFAULT_CODEC,
    "crf":           DEFAULT_CRF,
    "preset":        DEFAULT_PRESET,
    "audio_bitrate": DEFAULT_AUDIO_BITRATE,
    "audio_codec":   DEFAULT_AUDIO_CODEC,
    "resolution":    DEFAULT_RESOLUTION,
    "tune":          DEFAULT_TUNE,
    "send_type":     DEFAULT_SEND_TYPE,
    "audio_channel": DEFAULT_AUDIO_CHANNEL,
    "bit_depth":     DEFAULT_BIT_DEPTH,
    "fps":           DEFAULT_FPS,
    "rename_source": DEFAULT_RENAME_SOURCE,
}


class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col      = self.db.encoder_users
        self.groupcol = self.db.encoder_groups

    # ---------------- Per-user encode settings ----------------
    async def get_settings(self, uid: int) -> dict:
        try:
            user = await self.col.find_one({"_id": int(uid)})
        except Exception as e:
            logger.error(f"Error fetching settings for {uid}: {e}")
            user = None
        s = dict(DEFAULT_SETTINGS)
        if user:
            for k in s:
                if k in user:
                    s[k] = user[k]
        s["audio_codec"] = ACODEC_INPUT.get(str(s["audio_codec"]).lower(), s["audio_codec"])
        return s

    async def set_setting(self, uid: int, key: str, value):
        try:
            await self.col.update_one({"_id": int(uid)}, {"$set": {key: value}}, upsert=True)
        except Exception as e:
            logger.error(f"Error setting {key} for {uid}: {e}")

    # ---------------- Metadata ----------------
    async def get_metadata_status(self, uid: int) -> str:
        try:
            user = await self.col.find_one({"_id": int(uid)})
            return (user or {}).get("metadata", "Off")
        except Exception as e:
            logger.error(f"Error getting metadata status for {uid}: {e}")
            return "Off"

    async def set_metadata_status(self, uid: int, status: str):
        try:
            await self.col.update_one({"_id": int(uid)}, {"$set": {"metadata": status}}, upsert=True)
        except Exception as e:
            logger.error(f"Error setting metadata status for {uid}: {e}")

    async def get_metadata_fields(self, uid: int) -> dict:
        try:
            user = await self.col.find_one({"_id": int(uid)}) or {}
        except Exception as e:
            logger.error(f"Error getting metadata fields for {uid}: {e}")
            user = {}
        return {
            "title":    user.get("title"),
            "author":   user.get("author"),
            "artist":   user.get("artist"),
            "video":    user.get("video"),
            "audio":    user.get("audio"),
            "subtitle": user.get("subtitle"),
        }

    async def set_metadata_field(self, uid: int, field: str, value):
        try:
            await self.col.update_one({"_id": int(uid)}, {"$set": {field: value}}, upsert=True)
        except Exception as e:
            logger.error(f"Error setting metadata field {field} for {uid}: {e}")

    # ---------------- Thumbnails ----------------
    async def set_user_thumb(self, uid: int, thumb_bytes: bytes):
        try:
            await self.col.update_one(
                {"_id": int(uid)}, {"$set": {"thumb": thumb_bytes}}, upsert=True
            )
        except Exception as e:
            logger.error(f"Error saving thumbnail for {uid}: {e}")

    async def get_user_thumb_bytes(self, uid: int):
        try:
            user = await self.col.find_one({"_id": int(uid)})
            return (user or {}).get("thumb")
        except Exception as e:
            logger.error(f"Error fetching thumbnail for {uid}: {e}")
            return None

    async def delete_user_thumb(self, uid: int):
        try:
            await self.col.update_one({"_id": int(uid)}, {"$unset": {"thumb": ""}})
        except Exception as e:
            logger.error(f"Error deleting thumbnail for {uid}: {e}")

    # ---------------- Group authorization ----------------
    async def authorize_group(self, chat_id: int, title: str = None):
        try:
            await self.groupcol.update_one(
                {"_id": int(chat_id)}, {"$set": {"title": title}}, upsert=True
            )
        except Exception as e:
            logger.error(f"Error authorizing group {chat_id}: {e}")

    async def unauthorize_group(self, chat_id: int) -> bool:
        try:
            result = await self.groupcol.delete_one({"_id": int(chat_id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error unauthorizing group {chat_id}: {e}")
            return False

    async def is_group_authorized(self, chat_id: int) -> bool:
        try:
            doc = await self.groupcol.find_one({"_id": int(chat_id)})
            return doc is not None
        except Exception as e:
            logger.error(f"Error checking group authorization for {chat_id}: {e}")
            return False

    async def get_all_authorized_groups(self):
        try:
            return await self.groupcol.find().to_list(length=None)
        except Exception as e:
            logger.error(f"Error fetching authorized groups: {e}")
            return []
