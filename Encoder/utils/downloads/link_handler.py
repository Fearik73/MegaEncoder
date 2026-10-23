import os
import re
import shutil

import aiohttp

from Encoder.utils.downloads.aria2 import Aria2Job
from Encoder.utils.logs.tasklog import tlog

# Supported link patterns
GDRIVE_REGEX    = re.compile(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=|drive/folders/|folders/|drive/u/\d+/folders/)([\w-]+)')
MEDIAFIRE_REGEX = re.compile(r'mediafire\.com/file/([\w]+)')
MEGA_REGEX      = re.compile(r'mega(?:\.co)?\.nz/(?:file/|folder/|#!|#F!)')



def extract_source(url):
    if GDRIVE_REGEX.search(url):
        return "gdrive"
    if MEDIAFIRE_REGEX.search(url):
        return "mediafire"
    if MEGA_REGEX.search(url):
        return "mega"
    if url.lower().startswith(("http://", "https://")):
        return "direct"
    return None


# Per-host link resolvers
async def _resolve_mediafire(session, url):
    async with session.get(url) as resp:
        text = await resp.text()
    match = re.search(r'href="(https://download[\d]*\.mediafire\.com/[^"]+)"', text)
    if not match:
        raise Exception("couldn't find a MediaFire download link on that page (page layout may have changed)")
    return match.group(1)


def _gdrive_public_url(url):
    # Fallback when no Drive credentials are configured
    if "folders/" in url:
        raise Exception("GDrive folders need Drive credentials (accounts/*.json or token.pickle)")
    gdrive_id = GDRIVE_REGEX.search(url).group(1)
    return f"https://drive.usercontent.google.com/download?id={gdrive_id}&export=download&confirm=t"


# aria2-backed download (direct / mediafire)
async def _aria2_many(items, dest_dir, headers, status_msg, task_id: int, uid: int):
    from Encoder.utils.helpers import sanitize_filename

    job = Aria2Job(dest_dir)
    results = []
    used = set()
    try:
        await job.start()
        for link, name in items:
            opts = {}
            if headers:
                opts["header"] = headers
            if name:
                clean = sanitize_filename(os.path.basename(name))
                base, ext = os.path.splitext(clean)
                final, i = clean, 2
                while final in used:
                    final = f"{base} ({i}){ext}"
                    i += 1
                used.add(final)
                opts["out"] = final
            tlog(task_id, "download", f"aria2 add: {link} -> {opts.get('out', '(name from server)')}")
            gid = await job.add_uri(link, opts)
            path, fname = await job.wait_for_download(gid, status_msg, task_id, uid, max_seconds=None)
            results.append((path, fname))
    finally:
        await job.shutdown()
    return results


# Main link download — returns a list of (path, filename)
async def download_from_link(url, dest_dir, status_msg, task_id: int, uid: int):
    os.makedirs(dest_dir, exist_ok=True)
    kind = extract_source(url)
    tlog(task_id, "download", f"link type: {kind}")
    if kind is None:
        raise Exception("Unsupported link")

    try:
        if kind == "gdrive":
            from Encoder.utils.downloads.gdrive import gdrive_download, has_credentials
            if has_credentials():
                return await gdrive_download(url, dest_dir, status_msg, task_id, uid)
            return await _aria2_many([(_gdrive_public_url(url), None)], dest_dir, None, status_msg, task_id, uid)

        if kind == "mega":
            from Encoder.utils.downloads.mega import mega_download
            return await mega_download(url, dest_dir, status_msg, task_id, uid)

        if kind == "mediafire":
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                direct = await _resolve_mediafire(session, url)
            return await _aria2_many([(direct, None)], dest_dir, None, status_msg, task_id, uid)

        return await _aria2_many([(url, None)], dest_dir, None, status_msg, task_id, uid)
    except BaseException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
