import os
import re
import glob
import pickle
import random
import asyncio

from Encoder.utils.tasks.cancel import is_cancelled
from Encoder.utils.naming import VIDEO_EXTS, natural_key
from Encoder.utils.logs.tasklog import tlog

SCOPES         = ["https://www.googleapis.com/auth/drive"]
ACCOUNTS_DIR   = os.environ.get("GDRIVE_ACCOUNTS_DIR", "accounts")
TOKEN_PICKLE   = os.environ.get("GDRIVE_TOKEN_PICKLE", "token.pickle")
FOLDER_MIME    = "application/vnd.google-apps.folder"
SHORTCUT_MIME  = "application/vnd.google-apps.shortcut"
CHUNK_SIZE     = 16 * 1024 * 1024

_ID_PATTERNS = (
    re.compile(r"/folders/([\w-]+)"),
    re.compile(r"/file/d/([\w-]+)"),
    re.compile(r"[?&]id=([\w-]+)"),
)


class _UserCancelled(Exception):
    pass


def get_id_from_url(link: str):
    for pat in _ID_PATTERNS:
        m = pat.search(link)
        if m:
            return m.group(1)
    return None


def has_credentials() -> bool:
    return bool(glob.glob(os.path.join(ACCOUNTS_DIR, "*.json"))) or os.path.exists(TOKEN_PICKLE)


def _build_service():
    from googleapiclient.discovery import build
    from google.oauth2 import service_account

    accounts = glob.glob(os.path.join(ACCOUNTS_DIR, "*.json"))
    if accounts:
        creds = service_account.Credentials.from_service_account_file(
            random.choice(accounts), scopes=SCOPES
        )
    elif os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
    else:
        raise Exception("GDrive credentials not found")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _is_video(name: str, mime: str) -> bool:
    if (mime or "").startswith("video/"):
        return True
    return os.path.splitext(name or "")[1].lower() in VIDEO_EXTS


def _get_meta(service, file_id):
    meta = service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,shortcutDetails",
        supportsAllDrives=True,
    ).execute()
    if meta.get("mimeType") == SHORTCUT_MIME:
        target = meta.get("shortcutDetails", {})
        return _get_meta(service, target.get("targetId"))
    return meta


def _list_folder(service, folder_id, out):
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id,name,mimeType,size,shortcutDetails)",
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for item in resp.get("files", []):
            if item.get("mimeType") == SHORTCUT_MIME:
                try:
                    item = _get_meta(service, item["shortcutDetails"]["targetId"])
                except Exception:
                    continue
            if item.get("mimeType") == FOLDER_MIME:
                _list_folder(service, item["id"], out)
            elif not item.get("mimeType", "").startswith("application/vnd.google-apps."):
                out.append(item)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _download_one(service, file_id, path, task_id, on_bytes):
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=CHUNK_SIZE)
        done = False
        while not done:
            if is_cancelled(task_id):
                raise _UserCancelled()
            status, done = downloader.next_chunk(num_retries=3)
            if status:
                on_bytes(int(status.resumable_progress))
    if is_cancelled(task_id):
        raise _UserCancelled()


def _unique_name(name, used):
    if name not in used:
        used.add(name)
        return name
    base, ext = os.path.splitext(name)
    i = 2
    while f"{base} ({i}){ext}" in used:
        i += 1
    final = f"{base} ({i}){ext}"
    used.add(final)
    return final


def _run_blocking(link, dest_dir, task_id, loop, progress_cb):
    from Encoder.utils.helpers import sanitize_filename

    service = _build_service()
    file_id = get_id_from_url(link)
    if not file_id:
        raise Exception("Couldn't read a Google Drive ID from that link")

    try:
        meta = _get_meta(service, file_id)
    except Exception as e:
        raise Exception(f"GDrive: can't access this link ({e.__class__.__name__}) — check that it's shared/public")

    if meta.get("mimeType") == FOLDER_MIME:
        files = []
        _list_folder(service, meta["id"], files)
        files = [f for f in files if _is_video(f.get("name"), f.get("mimeType"))]
        files.sort(key=lambda f: natural_key(f.get("name", "")))
        if not files:
            raise Exception("GDrive folder has no video files")
    else:
        if meta.get("mimeType", "").startswith("application/vnd.google-apps."):
            raise Exception("This is a Google Docs/Sheets type file — it can't be downloaded as a video")
        files = [meta]

    total = sum(int(f.get("size", 0) or 0) for f in files)
    tlog(task_id, "gdrive", f"{len(files)} file(s) to download, {total} bytes: {[f.get('name') for f in files][:20]}")
    done_before = 0
    used = set()
    results = []

    for f in files:
        name = _unique_name(sanitize_filename(f.get("name") or f["id"]), used)
        path = os.path.join(dest_dir, name)
        base = done_before

        def on_bytes(n, base=base):
            if total:
                asyncio.run_coroutine_threadsafe(progress_cb(base + n, total), loop)

        tlog(task_id, "gdrive", f"downloading {name}")
        _download_one(service, f["id"], path, task_id, on_bytes)
        done_before += int(f.get("size", 0) or 0)
        results.append((path, name))

    return results


async def gdrive_download(link, dest_dir, status_msg, task_id: int, uid: int):
    import time
    from Encoder.utils.display_progress import make_progress_callback

    os.makedirs(dest_dir, exist_ok=True)
    progress_cb = make_progress_callback(status_msg, "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...", [time.time()], task_id, uid)
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.to_thread(_run_blocking, link, dest_dir, task_id, loop, progress_cb)
    except _UserCancelled:
        raise asyncio.CancelledError()
