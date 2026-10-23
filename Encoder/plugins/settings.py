from pyrogram import Client, filters
from pyrogram.types import Message

from Encoder.utils.database.access_db import db
from Encoder.utils.encoding.thumb import get_user_thumb
from Encoder.utils.filters import allowed
from Encoder.utils.settings.settings import (
    ACODEC_INPUT, ACODEC_LABEL, ACODEC_MAX_KBPS, ACODEC_NO_BITRATE, adjust_for_codec,
    CHANNEL_LABEL, is_valid_resolution, parse_fps, RENAME_LABEL, VALID_PRESETS,
    VALID_TUNES,
)


@Client.on_message(filters.command("settings") & allowed)
async def cmd_settings(client, msg: Message):
    uid = msg.from_user.id
    s  = await db.get_settings(uid)
    th = "ꜱᴀᴠᴇᴅ" if await get_user_thumb(uid) else "ɴᴏᴛ ꜱᴀᴠᴇᴅ"
    meta = await db.get_metadata_status(uid)
    await msg.reply(
        f"<b>⧉ <u>ʏᴏᴜʀ ᴇɴᴄᴏᴅᴇ ꜱᴇᴛᴛɪɴɢꜱ</u></b>\n\n"
        f"<b>┏ ᴄᴏᴅᴇᴄ:</b> {s['codec']}\n"
        f"<b>┣ ᴄʀꜰ:</b> {s['crf']}\n"
        f"<b>┣ ᴘʀᴇꜱᴇᴛ:</b> {s['preset']}\n"
        f"<b>┣ ʀᴇꜱᴏʟᴜᴛɪᴏɴ:</b> {s['resolution']}\n"
        f"<b>┣ ʙɪᴛ ᴅᴇᴘᴛʜ:</b> {s['bit_depth']} bit\n"
        f"<b>┣ ꜰᴘꜱ:</b> {'Copy' if s['fps'] == 'copy' else s['fps']}\n"
        f"<b>┣ ᴀᴜᴅɪᴏ ᴄᴏᴅᴇᴄ:</b> {ACODEC_LABEL.get(s['audio_codec'], s['audio_codec'])}\n"
        f"<b>┣ ᴀᴜᴅɪᴏ ᴄʜᴀɴɴᴇʟ:</b> {CHANNEL_LABEL.get(s['audio_channel'], s['audio_channel'])}\n"
        f"<b>┣ ᴀᴜᴅɪᴏ ʙɪᴛʀᴀᴛᴇ:</b> {'Copy' if s['audio_bitrate'] == 'copy' else s['audio_bitrate']}\n"
        f"<b>┣ ᴛᴜɴᴇ:</b> {s['tune']}\n"
        f"<b>┣ ꜱᴇɴᴅ ᴛʏᴘᴇ:</b> {'Document' if s['send_type'] == 'document' else 'Media'}\n"
        f"<b>┣ ʀᴇɴᴀᴍᴇ ꜱᴏᴜʀᴄᴇ:</b> {RENAME_LABEL.get(s['rename_source'], s['rename_source'])}\n"
        f"<b>┣ ᴍᴇᴛᴀᴅᴀᴛᴀ:</b> {meta}\n"
        f"<b>┗ ᴛʜᴜᴍʙɴᴀɪʟ:</b> {th}\n"
    )


@Client.on_message(filters.command("video") & allowed)
async def cmd_vc(client, msg: Message):
    uid = msg.from_user.id
    mapping = {"x264":"libx264","x265":"libx265","libx264":"libx264","libx265":"libx265"}
    parts = msg.text.split()
    if len(parts) != 2 or parts[1].lower() not in mapping:
        return
    value = mapping[parts[1].lower()]
    await db.set_setting(uid, "codec", value)
    await msg.reply(f"✅ Codec → {value}")


@Client.on_message(filters.command("crf") & allowed)
async def cmd_crf(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return
    val = int(parts[1])
    if not 0 <= val <= 51:
        return
    await db.set_setting(uid, "crf", val)
    await msg.reply(f"✅ Crf → {val}")


@Client.on_message(filters.command("preset") & allowed)
async def cmd_pre(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2 or parts[1] not in VALID_PRESETS:
        return
    await db.set_setting(uid, "preset", parts[1])
    await msg.reply(f"✅ Preset → {parts[1]}")


@Client.on_message(filters.command("resolution") & allowed)
async def cmd_res(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2 or not is_valid_resolution(parts[1]):
        return
    await db.set_setting(uid, "resolution", parts[1])
    await msg.reply(f"✅ Resolution → {parts[1]}")


@Client.on_message(filters.command("audiobit") & allowed)
async def cmd_ab(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2:
        return
    val = parts[1].lower()
    if val != "copy":
        if not val.endswith("k") or not val[:-1].isdigit():
            return
        s = await db.get_settings(uid)
        limit = ACODEC_MAX_KBPS.get(s["audio_codec"])
        if limit and int(val[:-1]) > limit:
            return await msg.reply(f"❌ Max audio bitrate for {ACODEC_LABEL[s['audio_codec']]} is {limit}k")
    await db.set_setting(uid, "audio_bitrate", val)
    await msg.reply(f"✅ Audio Bitrate → {val}")


@Client.on_message(filters.command("audio") & allowed)
async def cmd_ac(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2 or parts[1].lower() not in ACODEC_INPUT:
        return
    codec = ACODEC_INPUT[parts[1].lower()]
    s = await db.get_settings(uid)
    channel, bitrate, notes = adjust_for_codec(codec, s["audio_channel"], s["audio_bitrate"])
    await db.set_setting(uid, "audio_codec", codec)
    if channel != s["audio_channel"]:
        await db.set_setting(uid, "audio_channel", channel)
    if bitrate != s["audio_bitrate"]:
        await db.set_setting(uid, "audio_bitrate", bitrate)
    if codec in ACODEC_NO_BITRATE and codec != "copy":
        notes.append("Bitrate has no effect with this codec")
    await msg.reply("\n".join([f"✅ Audio Codec → {ACODEC_LABEL[codec]}"] + notes))


@Client.on_message(filters.command("bitdepth") & allowed)
async def cmd_bitdepth(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2:
        return
    val = parts[1].lower().removesuffix("bit")
    if val not in ("8", "10"):
        return
    await db.set_setting(uid, "bit_depth", val)
    await msg.reply(f"✅ Bit Depth → {val} bit")


@Client.on_message(filters.command("fps") & allowed)
async def cmd_fps(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2:
        return
    fps = parse_fps(parts[1])
    if fps is None:
        return
    await db.set_setting(uid, "fps", fps)
    await msg.reply(f"✅ FPS → {'Copy' if fps == 'copy' else fps}")


@Client.on_message(filters.command("tune") & allowed)
async def cmd_tune(client, msg: Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    if len(parts) != 2 or parts[1] not in VALID_TUNES:
        return
    await db.set_setting(uid, "tune", parts[1])
    await msg.reply(f"✅ Tune → {parts[1]}")
