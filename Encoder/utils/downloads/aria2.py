import os
import time
import socket
import base64
import asyncio
import logging

import aiohttp

from Encoder.utils.naming import VIDEO_EXTS, natural_key
from Encoder.utils.logs.tasklog import tlog

logger = logging.getLogger(__name__)

# Public tracker list: magnets/torrents find far more peers with it
TRACKERS_URL = "https://ngosang.github.io/trackerslist/trackers_all_http.txt"
_trackers_cache = None

# Timeouts / limits
BT_STOP_TIMEOUT      = 180
MAX_DOWNLOAD_SECONDS = 3600
POLL_INTERVAL        = 5
DAEMON_BOOT_TIMEOUT  = 10


async def _get_trackers():
    global _trackers_cache
    if _trackers_cache is not None:
        return _trackers_cache
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(TRACKERS_URL) as resp:
                text = await resp.text()
        _trackers_cache = ",".join(t.strip() for t in text.splitlines() if t.strip())
    except Exception:
        return ""
    return _trackers_cache


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Per-job aria2c daemon
_ERROR_HINTS = {
    "2": "timed out",
    "3": "file not found on the server (404)",
    "5": "download speed too slow",
    "6": "network problem",
    "9": "not enough disk space",
    "19": "DNS lookup failed",
    "24": "authorization failed",
    "29": "server overloaded / temporarily unavailable (HTTP 503)",
}


def _explain_error(status):
    msg  = status.get("errorMessage") or "aria2 reported an error"
    code = str(status.get("errorCode", "?"))
    done, total = int(status.get("completedLength") or 0), int(status.get("totalLength") or 0)
    parts = [f"aria2 error {code}"]
    if code in _ERROR_HINTS:
        parts.append(_ERROR_HINTS[code])
    if total and 0 < done < total:
        parts.append(f"stopped at {done * 100 / total:.1f}% ({done}/{total} bytes)")
    if status.get("bittorrent") and total and 0 < done < total and str(status.get("numSeeders", "0")) == "0":
        parts.append("no seeders: the remaining pieces aren't available from any peer (dead/incomplete torrent)")
    return f"{msg} [{'; '.join(parts)}]"


class Aria2Job:

    def __init__(self, dest_dir):
        self.dest_dir = dest_dir
        self.port = _free_port()
        self.rpc_url = f"http://127.0.0.1:{self.port}/jsonrpc"
        self.proc = None

    async def start(self):
        os.makedirs(self.dest_dir, exist_ok=True)
        trackers = await _get_trackers()
        cmd = [
            "aria2c",
            "--enable-rpc=true",
            "--rpc-listen-all=false",
            f"--rpc-listen-port={self.port}",
            f"--dir={self.dest_dir}",
            "--max-concurrent-downloads=1",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--continue=true",
            "--allow-overwrite=true",
            "--disk-cache=64M",
            "--file-allocation=none",
            "--max-tries=20",
            "--max-file-not-found=0",
            "--check-certificate=false",
            "--http-accept-gzip=true",
            "--content-disposition-default-utf8=true",
            "--bt-max-peers=0",
            "--bt-enable-lpd=true",
            "--peer-id-prefix=-qB4520-",
            "--peer-agent=qBittorrent/4.5.2",
            f"--bt-stop-timeout={BT_STOP_TIMEOUT}",
            "--seed-time=0",
            "--follow-torrent=true",
            "--summary-interval=0",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        ]
        if trackers:
            cmd.append(f"--bt-tracker={trackers}")
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
        except FileNotFoundError:
            raise Exception("aria2c binary not found — torrent/magnet leech is disabled until it's installed")

        deadline = time.time() + DAEMON_BOOT_TIMEOUT
        async with aiohttp.ClientSession() as session:
            while time.time() < deadline:
                if await self._alive(session):
                    return
                await asyncio.sleep(0.5)
        await self.shutdown()
        raise Exception("aria2c didn't come up in time")

    async def _alive(self, session):
        try:
            await self._call(session, "aria2.getVersion", [])
            return True
        except Exception:
            return False

    async def _call(self, session, method, params):
        payload = {"jsonrpc": "2.0", "id": "encoderbot", "method": method, "params": params}
        async with session.post(self.rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
        if "error" in data:
            raise Exception(data["error"].get("message", "aria2 RPC error"))
        return data.get("result")

    async def add_uri(self, magnet_or_url, options=None):
        params = [[magnet_or_url]]
        if options:
            params.append(options)
        async with aiohttp.ClientSession() as session:
            return await self._call(session, "aria2.addUri", params)

    async def add_torrent(self, torrent_bytes):
        b64 = base64.b64encode(torrent_bytes).decode()
        async with aiohttp.ClientSession() as session:
            return await self._call(session, "aria2.addTorrent", [b64])

    # Poll download status until complete
    async def wait_for_download(self, gid, status_msg, task_id: int, uid: int, max_seconds=MAX_DOWNLOAD_SECONDS, return_all=False):
        from Encoder.utils.display_progress import make_progress_callback
        from Encoder.utils.tasks.cancel import is_cancelled

        start = time.time()
        last_log = 0.0
        progress_cb = make_progress_callback(status_msg, "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...", [start], task_id, uid)
        tlog(task_id, "aria2", f"waiting for download (gid {gid})")

        async with aiohttp.ClientSession() as session:
            while True:
                if is_cancelled(task_id):
                    try:
                        await self._call(session, "aria2.remove", [gid])
                    except Exception:
                        pass
                    raise asyncio.CancelledError()

                status = await self._call(session, "aria2.tellStatus", [gid])
                state = status.get("status")

                if state == "error":
                    reason = _explain_error(status)
                    tlog(task_id, "aria2", f"error {status.get('errorCode')}: {reason}", "error")
                    raise Exception(reason)

                followed_by = status.get("followedBy") or []
                if state == "complete" and followed_by:
                    tlog(task_id, "aria2", f"metadata fetched, following gid {followed_by[0]}")
                    gid = followed_by[0]
                    continue

                if time.time() - last_log >= 30:
                    last_log = time.time()
                    tlog(task_id, "aria2",
                         f"{status.get('completedLength')}/{status.get('totalLength')} bytes, "
                         f"speed={status.get('downloadSpeed')} B/s, seeders={status.get('numSeeders')}, "
                         f"connections={status.get('connections')}, state={state}")

                files   = status.get("files", [])

                if state == "complete":
                    tlog(task_id, "aria2", f"download complete, {len(files)} file(s)")

                if state == "complete" and return_all:
                    found = [
                        f["path"] for f in files
                        if f.get("selected", "true") != "false"
                        and int(f.get("length", 0)) > 0 and os.path.exists(f["path"])
                    ]
                    if not found:
                        raise Exception("aria2 marked the download complete but the files are missing/empty")
                    if len(found) > 1:
                        found = [p for p in found if os.path.splitext(p)[1].lower() in VIDEO_EXTS]
                        if not found:
                            raise Exception("batch has no video files")
                    found.sort(key=natural_key)
                    return [(p, os.path.basename(p)) for p in found]

                if state == "complete":
                    if not files:
                        raise Exception("aria2 finished but reported no files")
                    largest = max(files, key=lambda f: int(f.get("length", 0)))
                    if int(largest.get("length", 0)) == 0 or not os.path.exists(largest["path"]):
                        raise Exception("aria2 marked the download complete but the file is missing/empty")
                    return largest["path"], os.path.basename(largest["path"])

                if max_seconds and time.time() - start > max_seconds:
                    raise Exception("gave up after an hour — likely a dead torrent with no seeds")

                total = int(status.get("totalLength", 0))
                done  = int(status.get("completedLength", 0))
                await progress_cb(done, total)

                await asyncio.sleep(POLL_INTERVAL)

    async def shutdown(self):
        if self.proc is None:
            return
        try:
            async with aiohttp.ClientSession() as session:
                await self._call(session, "aria2.shutdown", [])
            await asyncio.wait_for(self.proc.wait(), timeout=5)
        except Exception:
            try:
                self.proc.kill()
                await self.proc.wait()
            except Exception:
                pass
        self.proc = None
