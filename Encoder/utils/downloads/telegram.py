import os, asyncio
from Encoder.utils.tasks.cancel import is_cancelled

_download_semaphore = asyncio.Semaphore(1)

# Validate downloaded file looks like a real video by header
def _is_valid_video_file(path: str) -> tuple[bool, str]:
    try:
        size = os.path.getsize(path)
        if size < 16:
            return False, "File too small — download may be incomplete"
        with open(path, "rb") as f:
            header = f.read(12)
        if header[:4] == b'\x1a\x45\xdf\xa3':
            return True, ""
        if header[4:8] in (b'ftyp', b'moov', b'mdat', b'free', b'wide'):
            return True, ""
        if header[:4] == b'RIFF' and header[8:12] == b'AVI ':
            return True, ""
        if header[:4] == b'\x30\x26\xb2\x75':
            return True, ""
        if header[:4] == b'FLV\x01':
            return True, ""
        if header[:4] == b'OggS':
            return True, ""
        if header[0] == 0x47:
            return True, ""
        if header[0] != 0x00:
            return True, ""
        return False, "File header is invalid (0x00) — download was incomplete or corrupted"
    except Exception as e:
        return False, f"Could not verify file: {e}"

async def stream_download(client, message, dest_path: str, progress_cb=None, task_id: int = 0) -> bool:
    file_obj = message.video or message.document
    if not file_obj:
        raise ValueError("No video or document found in message.")

    file_size  = getattr(file_obj, "file_size", 0) or 0
    downloaded = 0

    async with _download_semaphore:
        with open(dest_path, "wb") as f:
            async for chunk in client.stream_media(message, limit=10*1024*1024):
                if task_id and is_cancelled(task_id):
                    raise asyncio.CancelledError()
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and file_size > 0:
                    await progress_cb(downloaded, file_size)

    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        raise ValueError("Telegram sent an empty file — try re-sending the video.")

    actual_size = os.path.getsize(dest_path)
    if file_size > 0 and actual_size < file_size:
        os.remove(dest_path)
        raise ValueError(
            f"Download incomplete: got {actual_size} of {file_size} bytes — connection likely dropped, retrying."
        )

    valid, reason = _is_valid_video_file(dest_path)
    if not valid:
        os.remove(dest_path)
        raise ValueError(f"Downloaded file is corrupt: {reason} — Please re-send the file.")

    return True
