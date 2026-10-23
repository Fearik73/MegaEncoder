import asyncio
import html
from uuid import uuid4

from pyrogram import Client, filters, StopPropagation
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from Encoder.utils.database.access_db import db
from Encoder.utils.filters import allowed
from Encoder.utils.settings.defaults import DEFAULT_CRF
from Encoder.utils.settings.settings import (
    ACODEC_LABEL, ACODEC_MAX_KBPS, ACODEC_NO_BITRATE, adjust_for_codec, CHANNEL_LABEL,
    is_valid_resolution, parse_fps, parse_kbps, RENAME_LABEL, VALID_ACODECS,
    VALID_CHANNELS, VALID_PRESETS, VALID_RENAME_SOURCES, VALID_RESOLUTIONS,
    VALID_TUNES,
)


TIMEOUT = 60


META_FIELDS = ("title", "author", "artist", "audio", "subtitle", "video")


META_DESC = "Your channel name that should be used while editing metadata of the file"


RES_BUTTONS = [("240p", "426x240"), ("360p", "640x360"), ("480p", "854x480"),
               ("540p", "960x540"), ("720p", "1280x720"), ("1080p", "1920x1080")]


RES_LABEL = {v: k for k, v in RES_BUTTONS}


RES_LABEL["original"] = "Original"


AB_VALUES = [32, 48, 64, 96, 128, 160, 192, 224, 256, 320]


ACODEC_ORDER = ["copy", "aac", "libmp3lame", "libopus", "ac3", "flac", "pcm_s16le"]


VCODEC_LABEL = {"libx264": "x264", "libx265": "x265"}


PAGE_FOR = {"meta": "meta", "crf": "crf", "res": "res", "ab": "ab", "fps": "fps"}


_pending: dict = {}


# ---------------- small helpers ----------------
def _b(uid, label, action, arg=""):
    return Btn(label, callback_data=f"us|{uid}|{action}|{arg}")


def _grid(buttons, per_row):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _back(uid, page="home"):
    return [_b(uid, "Back", "page", page)]


def _opt(uid, label, field, value, current):
    mark = "✅ " if str(current) == str(value) else ""
    return _b(uid, f"{mark}{label}", "set", f"{field}={value}")


def _bitrate_label(v):
    return "Copy" if v == "copy" else v


def _fps_label(v):
    return "Copy" if v == "copy" else v


async def _meta_state(uid):
    fields = await db.get_metadata_fields(uid)
    value = next((fields[k] for k in META_FIELDS if fields.get(k)), None)
    status = await db.get_metadata_status(uid)
    if not value:
        status = "Off"
    return status, value


async def _clear_metadata(uid):
    for f in META_FIELDS:
        await db.set_metadata_field(uid, f, None)
    await db.set_metadata_status(uid, "Off")


# ---------------- main pages ----------------
async def build_page(page, uid, name):
    s = await db.get_settings(uid)
    name = html.escape(name or "User")

    if page == "home":
        status, value = await _meta_state(uid)
        meta_line = f"{html.escape(value)} ({status})" if value else "Not Exists"
        text = (
            f"㊂ <b>Encode Settings for {name}</b>\n\n"
            f"┎ Send Type : {'Document' if s['send_type'] == 'document' else 'Media'}\n"
            f"┠ Rename Source : {RENAME_LABEL.get(s['rename_source'], s['rename_source'])}\n"
            f"┠ Metadata : {meta_line}\n"
            f"┠ CRF : {s['crf']}\n"
            f"┠ Preset : {s['preset']}\n"
            f"┠ Tune : {s['tune']}\n"
            f"┠ Resolution : {RES_LABEL.get(s['resolution'], s['resolution'])}\n"
            f"┠ Audio Channel : {CHANNEL_LABEL.get(s['audio_channel'], s['audio_channel'])}\n"
            f"┠ Audio Bitrate : {_bitrate_label(s['audio_bitrate'])}\n"
            f"┠ Audio Codec : {ACODEC_LABEL.get(s['audio_codec'], s['audio_codec'])}\n"
            f"┠ Video Codec : {VCODEC_LABEL.get(s['codec'], s['codec'])}\n"
            f"┠ Bit Depth : {s['bit_depth']} bit\n"
            f"┖ FPS : {_fps_label(s['fps'])}"
        )
        send_label = "Send as Media" if s["send_type"] == "document" else "Send as Document"
        kb = [
            [_b(uid, send_label, "send"), _b(uid, "Metadata", "page", "meta")],
            [_b(uid, "CRF", "page", "crf"), _b(uid, "Preset", "page", "preset")],
            [_b(uid, "Tune", "page", "tune"), _b(uid, "Resolution", "page", "res")],
            [_b(uid, "Audio Channel", "page", "ach"), _b(uid, "Audio Bitrate", "page", "ab")],
            [_b(uid, "Audio Codec", "page", "acodec"), _b(uid, "Video Codec", "page", "vcodec")],
            [_b(uid, "Bit Depth", "page", "bits"), _b(uid, "FPS", "page", "fps")],
            [_b(uid, "Source", "page", "source")],
            [_b(uid, "Close", "close")],
        ]
        return text, Markup(kb)

    if page == "meta":
        status, value = await _meta_state(uid)
        text = (
            f"㊂ <b>Metadata Settings :</b>\n\n"
            f"➲ Status : {status}\n\n"
            f"➲ Saved Metadata : {html.escape(value) if value else 'Not Exists'}\n\n"
            f"➲ Description : {META_DESC}"
        )
        if value:
            toggle = "Turn Off" if status == "On" else "Turn On"
            kb = [
                [_b(uid, toggle, "mtog"), _b(uid, "Delete", "mdel")],
                [_b(uid, "Change Metadata", "ask", "meta")],
                _back(uid),
            ]
        else:
            kb = [[_b(uid, "Add Metadata", "ask", "meta")], _back(uid)]
        return text, Markup(kb)

    if page == "crf":
        text = (
            f"㊂ <b>CRF Settings :</b>\n\n"
            f"➲ Current : {s['crf']}\n"
            f"➲ Default : {DEFAULT_CRF}\n"
            f"➲ Range : 0 – 51 (lower = better quality, bigger file)"
        )
        kb = [[_b(uid, "Change Value", "ask", "crf"), _b(uid, "Reset", "crfreset")], _back(uid)]
        return text, Markup(kb)

    if page == "preset":
        text = f"㊂ <b>Preset Settings :</b>\n\n➲ Current : {s['preset']}"
        btns = [_opt(uid, p, "preset", p, s["preset"]) for p in VALID_PRESETS]
        return text, Markup(_grid(btns, 3) + [_back(uid)])

    if page == "tune":
        text = f"㊂ <b>Tune Settings :</b>\n\n➲ Current : {s['tune']}"
        btns = [_opt(uid, t, "tune", t, s["tune"]) for t in VALID_TUNES]
        return text, Markup(_grid(btns, 2) + [_back(uid)])

    if page == "res":
        text = (
            f"㊂ <b>Resolution Settings :</b>\n\n"
            f"➲ Current : {RES_LABEL.get(s['resolution'], s['resolution'])}"
        )
        btns = [_opt(uid, lab, "resolution", val, s["resolution"]) for lab, val in RES_BUTTONS]
        kb = _grid(btns, 3)
        kb.append([_opt(uid, "Original", "resolution", "original", s["resolution"]),
                   _b(uid, "Custom", "ask", "res")])
        kb.append(_back(uid))
        return text, Markup(kb)

    if page == "ach":
        text = f"㊂ <b>Audio Channel Settings :</b>\n\n➲ Current : {CHANNEL_LABEL.get(s['audio_channel'], s['audio_channel'])}"
        btns = [_opt(uid, CHANNEL_LABEL[c], "audio_channel", c, s["audio_channel"]) for c in VALID_CHANNELS]
        return text, Markup(_grid(btns, 3) + [_back(uid)])

    if page == "ab":
        codec = s["audio_codec"]
        text = f"㊂ <b>Audio Bitrate Settings :</b>\n\n➲ Current : {_bitrate_label(s['audio_bitrate'])}"
        if codec in ACODEC_MAX_KBPS:
            text += f"\n➲ Max for {ACODEC_LABEL[codec]} : {ACODEC_MAX_KBPS[codec]}k"
        elif codec != "copy":
            text += f"\n➲ Note : {ACODEC_LABEL[codec]} ignores bitrate"
        else:
            text += "\n➲ Note : Audio codec is Copy, bitrate is not used"
        btns = [_opt(uid, f"{v}k", "audio_bitrate", f"{v}k", s["audio_bitrate"]) for v in AB_VALUES]
        kb = [[_opt(uid, "Copy", "audio_bitrate", "copy", s["audio_bitrate"])]]
        kb += _grid(btns, 3)
        kb.append([_b(uid, "Custom", "ask", "ab")])
        kb.append(_back(uid))
        return text, Markup(kb)

    if page == "acodec":
        text = f"㊂ <b>Audio Codec Settings :</b>\n\n➲ Current : {ACODEC_LABEL.get(s['audio_codec'], s['audio_codec'])}"
        btns = [_opt(uid, ACODEC_LABEL[c], "audio_codec", c, s["audio_codec"]) for c in ACODEC_ORDER]
        return text, Markup(_grid(btns, 3) + [_back(uid)])

    if page == "vcodec":
        text = f"㊂ <b>Video Codec Settings :</b>\n\n➲ Current : {VCODEC_LABEL.get(s['codec'], s['codec'])}"
        btns = [_opt(uid, lab, "codec", val, s["codec"]) for val, lab in VCODEC_LABEL.items()]
        return text, Markup([btns, _back(uid)])

    if page == "bits":
        text = f"㊂ <b>Bit Depth Settings :</b>\n\n➲ Current : {s['bit_depth']} bit"
        btns = [_opt(uid, "8 bit", "bit_depth", "8", s["bit_depth"]),
                _opt(uid, "10 bit", "bit_depth", "10", s["bit_depth"])]
        return text, Markup([btns, _back(uid)])

    if page in ("source", "source_cmd"):
        cur = s["rename_source"]
        text = (
            f"㊂ <b>Rename Source Settings :</b>\n\n"
            f"➲ Current : {RENAME_LABEL.get(cur, cur)}\n\n"
            f"<blockquote>▸ File Name : rename from the file's own name\n"
            f"▸ Caption : rename from the caption\n"
            f"▸ Both : caption first, the file name if there is no caption</blockquote>"
        )
        btns = [
            _b(uid, ("✅ " if cur == v else "") + RENAME_LABEL[v], "srcset", f"{v}|{page}")
            for v in VALID_RENAME_SOURCES
        ]
        last = _back(uid) if page == "source" else [_b(uid, "Close", "close")]
        return text, Markup([btns, last])

    if page == "fps":
        text = (
            f"㊂ <b>FPS Settings :</b>\n\n"
            f"➲ Current : {_fps_label(s['fps'])}\n"
            f"➲ Copy : keep the source frame rate"
        )
        kb = [[_opt(uid, "Copy", "fps", "copy", s["fps"]), _b(uid, "Custom", "ask", "fps")], _back(uid)]
        return text, Markup(kb)

    return await build_page("home", uid, name)


async def prompt_text(kind, uid):
    s = await db.get_settings(uid)
    tail = f"\n\n⌬ You have {TIMEOUT}s — send the value now."
    if kind == "meta":
        _, value = await _meta_state(uid)
        return (f"㊂ <b>Metadata :</b>\n\nSend the metadata text (e.g. <code>@Od3ns_Animes</code>)\n\n"
                f"➲ Current : {html.escape(value) if value else 'Not Exists'}{tail}")
    if kind == "crf":
        return f"㊂ <b>CRF :</b>\n\nSend a CRF value (0 – 51)\n\n➲ Current : {s['crf']}{tail}"
    if kind == "res":
        return (f"㊂ <b>Resolution :</b>\n\nSend width x height with even numbers (e.g. <code>1280x720</code>)\n\n"
                f"➲ Current : {RES_LABEL.get(s['resolution'], s['resolution'])}{tail}")
    if kind == "ab":
        codec = s["audio_codec"]
        limit = f" (max {ACODEC_MAX_KBPS[codec]}k for {ACODEC_LABEL[codec]})" if codec in ACODEC_MAX_KBPS else ""
        return (f"㊂ <b>Audio Bitrate :</b>\n\nSend a bitrate (e.g. <code>128k</code>){limit}\n\n"
                f"➲ Current : {_bitrate_label(s['audio_bitrate'])}{tail}")
    if kind == "fps":
        return (f"㊂ <b>FPS :</b>\n\nSend a frame rate (e.g. <code>24</code>, <code>23.976</code> or "
                f"<code>24000/1001</code>) or <code>copy</code>\n\n➲ Current : {_fps_label(s['fps'])}{tail}")
    return "Send the value."


# ---------------- actions (buttons) ----------------
async def handle_action(uid, action, arg):
    s = await db.get_settings(uid)

    if action == "page":
        return None, arg, None

    if action == "ask":
        return None, None, arg

    if action == "send":
        new = "media" if s["send_type"] == "document" else "document"
        await db.set_setting(uid, "send_type", new)
        return f"Send type → {new.capitalize()}", "home", None

    if action == "mtog":
        status, value = await _meta_state(uid)
        if value:
            await db.set_metadata_status(uid, "Off" if status == "On" else "On")
        return None, "meta", None

    if action == "mdel":
        await _clear_metadata(uid)
        return "Metadata deleted", "meta", None

    if action == "srcset":
        value, _, page = arg.partition("|")
        if value in VALID_RENAME_SOURCES:
            await db.set_setting(uid, "rename_source", value)
            return f"Rename source → {RENAME_LABEL[value]}", page if page in ("source", "source_cmd") else "source", None
        return None, "source", None

    if action == "crfreset":
        await db.set_setting(uid, "crf", DEFAULT_CRF)
        return f"CRF changed to default ({DEFAULT_CRF})", "crf", None

    if action == "set" and "=" in arg:
        field, value = arg.split("=", 1)
        notes = []

        if field == "preset" and value in VALID_PRESETS:
            await db.set_setting(uid, "preset", value)
            return f"Preset → {value}", "preset", None
        if field == "tune" and value in VALID_TUNES:
            await db.set_setting(uid, "tune", value)
            return f"Tune → {value}", "tune", None
        if field == "resolution" and value in VALID_RESOLUTIONS:
            await db.set_setting(uid, "resolution", value)
            return f"Resolution → {RES_LABEL.get(value, value)}", "res", None
        if field == "codec" and value in VCODEC_LABEL:
            await db.set_setting(uid, "codec", value)
            return f"Video codec → {VCODEC_LABEL[value]}", "vcodec", None
        if field == "bit_depth" and value in ("8", "10"):
            await db.set_setting(uid, "bit_depth", value)
            return f"Bit depth → {value} bit", "bits", None
        if field == "fps" and value == "copy":
            await db.set_setting(uid, "fps", "copy")
            return "FPS → Copy", "fps", None
        if field == "audio_channel" and value in VALID_CHANNELS:
            channel, _, notes = adjust_for_codec(s["audio_codec"], value, "copy")
            await db.set_setting(uid, "audio_channel", channel)
            return "\n".join(notes) or f"Audio channel → {CHANNEL_LABEL[channel]}", "ach", None
        if field == "audio_bitrate" and (value == "copy" or (parse_kbps(value) in AB_VALUES)):
            await db.set_setting(uid, "audio_bitrate", value)
            note = ""
            if s["audio_codec"] in ACODEC_NO_BITRATE:
                note = f" ({ACODEC_LABEL[s['audio_codec']]} ignores bitrate)"
            return f"Audio bitrate → {_bitrate_label(value)}{note}", "ab", None
        if field == "audio_codec" and value in VALID_ACODECS:
            channel, bitrate, notes = adjust_for_codec(value, s["audio_channel"], s["audio_bitrate"])
            await db.set_setting(uid, "audio_codec", value)
            if channel != s["audio_channel"]:
                await db.set_setting(uid, "audio_channel", channel)
            if bitrate != s["audio_bitrate"]:
                await db.set_setting(uid, "audio_bitrate", bitrate)
            if value in ACODEC_NO_BITRATE and value != "copy":
                notes.append("Bitrate has no effect with this codec")
            return "\n".join([f"Audio codec → {ACODEC_LABEL[value]}"] + notes), "acodec", None

    return None, "home", None


# ---------------- typed values ----------------
async def apply_input(kind, uid, text):
    text = (text or "").strip()
    s = await db.get_settings(uid)

    if kind == "meta":
        if not text or len(text) > 128:
            return False, "❌ Send a metadata text (max 128 characters)."
        _, had = await _meta_state(uid)
        for f in META_FIELDS:
            await db.set_metadata_field(uid, f, text)
        if not had:
            await db.set_metadata_status(uid, "On")
        return True, None

    if kind == "crf":
        if not text.isdigit() or not 0 <= int(text) <= 51:
            return False, "❌ CRF must be a number from 0 to 51."
        await db.set_setting(uid, "crf", int(text))
        return True, None

    if kind == "res":
        value = text.lower().replace("×", "x")
        if not is_valid_resolution(value):
            return False, "❌ Use width x height with even numbers, e.g. 1280x720."
        await db.set_setting(uid, "resolution", value)
        return True, None

    if kind == "ab":
        kbps = parse_kbps(text)
        if kbps is None or kbps < 8:
            return False, "❌ Send a bitrate like 128k (minimum 8k)."
        codec = s["audio_codec"]
        limit = ACODEC_MAX_KBPS.get(codec)
        if limit and kbps > limit:
            return False, f"❌ Max audio bitrate for {ACODEC_LABEL[codec]} is {limit}k."
        await db.set_setting(uid, "audio_bitrate", f"{kbps}k")
        return True, None

    if kind == "fps":
        fps = parse_fps(text)
        if fps is None:
            return False, "❌ Send a frame rate like 24, 23.976, 24000/1001 or copy."
        await db.set_setting(uid, "fps", fps)
        return True, None

    return False, "❌ Nothing to set."


# ---------------- pyrogram glue ----------------
async def _edit(msg, text, kb):
    try:
        await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        pass


async def _expire(key, token):
    await asyncio.sleep(TIMEOUT)
    st = _pending.get(key)
    if st and st["token"] == token:
        _pending.pop(key, None)
        text, kb = await build_page(PAGE_FOR[st["kind"]], key[1], st["name"])
        await _edit(st["msg"], text, kb)


def _pending_filter(_, __, m):
    return bool(
        m.from_user and m.text and not m.text.startswith("/")
        and (m.chat.id, m.from_user.id) in _pending
    )


@Client.on_message(filters.command(["us", "usersettings"]) & allowed)
async def cmd_us(client, msg):
    uid = msg.from_user.id
    text, kb = await build_page("home", uid, msg.from_user.first_name)
    await msg.reply(text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_message(filters.command("source") & allowed)
async def cmd_source(client, msg):
    uid = msg.from_user.id
    text, kb = await build_page("source_cmd", uid, msg.from_user.first_name)
    await msg.reply(text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^us\|"))
async def us_callback(client, cq):
    try:
        _, owner, action, arg = cq.data.split("|", 3)
        owner = int(owner)
    except ValueError:
        return await cq.answer()
    if cq.from_user.id != owner:
        return await cq.answer("This menu isn't yours, go and open your own", show_alert=True)

    key = (cq.message.chat.id, owner)
    _pending.pop(key, None)
    name = cq.from_user.first_name

    if action == "close":
        try:
            await cq.message.delete()
        except Exception:
            pass
        return await cq.answer()

    toast, page, kind = await handle_action(owner, action, arg)
    if kind:
        token = uuid4().hex
        _pending[key] = {"kind": kind, "msg": cq.message, "name": name, "token": token}
        await _edit(cq.message, await prompt_text(kind, owner), None)
        asyncio.ensure_future(_expire(key, token))
    else:
        text, kb = await build_page(page, owner, name)
        await _edit(cq.message, text, kb)
    await cq.answer(toast)


@Client.on_message(filters.create(_pending_filter) & allowed, group=-1)
async def us_input(client, msg):
    key = (msg.chat.id, msg.from_user.id)
    st = _pending.get(key)
    if not st:
        return
    ok, err = await apply_input(st["kind"], msg.from_user.id, msg.text)
    if not ok:
        await msg.reply(err)          # keep waiting until the 60s window ends
    else:
        _pending.pop(key, None)
        text, kb = await build_page(PAGE_FOR[st["kind"]], msg.from_user.id, st["name"])
        await _edit(st["msg"], text, kb)
    raise StopPropagation
