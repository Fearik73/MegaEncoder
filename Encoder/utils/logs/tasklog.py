import os
import json
import time
import shutil
import asyncio
import traceback
from collections import OrderedDict
from datetime import datetime, timezone


LOG_DIR     = "/tmp/tasklogs"
MAX_EVENTS  = 1500
MAX_MSG     = 6000
KEEP_LOGS   = 30          # only the newest logs stay in memory

_logs: "OrderedDict[int, TaskLog]" = OrderedDict()


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskLog:
    def __init__(self, kind, task_id, uid, group_id, info=None):
        self.kind       = kind
        self.task_id    = task_id
        self.uid        = uid
        self.group_id   = group_id
        self.info       = dict(info or {})
        self.events     = []
        self.started    = time.time()
        self.started_at = _now_iso()
        self.error      = None

    def add(self, stage, msg, level="info"):
        if len(self.events) >= MAX_EVENTS:
            return
        self.events.append({
            "t":     round(time.time() - self.started, 1),
            "time":  datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "stage": stage,
            "level": level,
            "msg":   str(msg)[:MAX_MSG],
        })

    def fail(self, stage, msg, exc=None):
        tb = None
        if exc is not None and exc.__traceback__ is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.error = {
            "stage":     stage,
            "type":      type(exc).__name__ if exc is not None else None,
            "message":   str(exc) if exc is not None else str(msg),
            "summary":   str(msg),
            "traceback": tb,
        }
        self.add(stage, f"{msg}" + (f" — {exc!r}" if exc is not None else ""), "error")

    def to_text(self, reason):
        err = self.error or {}
        lines = [
            f"{self.kind.upper()} FAILED - {reason}",
            "=" * 64,
            f"Task     : {self.task_id} ({self.kind})",
            f"User     : {self.uid}",
            f"Group    : {self.group_id}",
            f"Started  : {self.started_at}",
            f"Ended    : {_now_iso()}",
            f"Duration : {round(time.time() - self.started, 1)}s",
            "",
            "ERROR",
            "-" * 64,
            f"Stage    : {err.get('stage') or '-'}",
            f"Type     : {err.get('type') or '-'}",
            "Message  :",
            _indent(err.get("message") or reason),
        ]
        if err.get("traceback"):
            lines += ["", "Traceback:", _indent(err["traceback"].rstrip())]
        lines += ["", "INFO", "-" * 64]
        for key, val in self.info.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{key}:")
                lines.append(_indent(json.dumps(val, indent=2, ensure_ascii=False, default=str)))
            else:
                lines.append(f"{key}: {val}")
        lines += ["", "EVENTS", "-" * 64]
        for e in self.events:
            head = f"[{e['time']}] +{e['t']:>7.1f}s {e['level'].upper():<5} {e['stage']:<8} "
            msg_lines = str(e["msg"]).splitlines() or [""]
            lines.append(head + msg_lines[0])
            lines += [" " * 4 + l for l in msg_lines[1:]]
        return "\n".join(lines) + "\n"


def _indent(text, n=4):
    return "\n".join(" " * n + l for l in str(text).splitlines())


# ---------------- registry ----------------
def start_log(kind, task_id, uid, group_id, **info):
    log = TaskLog(kind, task_id, uid, group_id, info)
    _logs[task_id] = log
    while len(_logs) > KEEP_LOGS:
        _logs.popitem(last=False)
    log.add("start", f"{kind} task started")
    return log


def drop_log(task_id):
    _logs.pop(task_id, None)


def tlog(task_id, stage, msg, level="info"):
    log = _logs.get(task_id)
    if log is not None:
        log.add(stage, msg, level)


def tfail(task_id, stage, msg, exc=None):
    log = _logs.get(task_id)
    if log is not None:
        log.fail(stage, msg, exc)


def set_info(task_id, **info):
    log = _logs.get(task_id)
    if log is not None:
        log.info.update(info)


async def probe_into_log(task_id, path):
    log = _logs.get(task_id)
    if log is None:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries",
            "stream=index,codec_type,codec_name,width,height,r_frame_rate,pix_fmt,channels,bit_rate"
            ":stream_tags=language:format=format_name,duration,size,bit_rate",
            "-of", "json", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode == 0 and out:
            log.info["input_probe"] = json.loads(out.decode(errors="replace"))
        else:
            log.add("probe", f"ffprobe failed: {err.decode(errors='replace')[:500]}", "warn")
    except Exception as e:
        log.add("probe", f"ffprobe error: {e!r}", "warn")


# ---------------- send ----------------
async def _reply_doc(target_msg, path, caption):
    attempts = []
    if getattr(target_msg, "id", None) is not None:
        attempts.append({"reply_to_message_id": target_msg.id})
    attempts += [{"quote": True}, {}]
    for kwargs in attempts:
        try:
            return await target_msg.reply_document(document=path, caption=caption, **kwargs)
        except TypeError:
            continue
    raise RuntimeError("reply_document failed")


async def send_failure_log(target_msg, task_id, reason, status_msg=None, fallback_text=None):
    log = _logs.get(task_id)
    folder = None
    sent = False
    try:
        if log is not None:
            folder = os.path.join(LOG_DIR, f"{log.kind}_{task_id}_{int(time.time())}")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "error.logs.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(log.to_text(reason))
            caption = fallback_text or reason
            try:
                await _reply_doc(target_msg, path, caption)
            except Exception as e:
                wait = getattr(e, "value", None)
                if not isinstance(wait, int):
                    raise
                await asyncio.sleep(wait + 1)
                await _reply_doc(target_msg, path, caption)
            sent = True
    except Exception as e:
        print(f"[ERROR] send_failure_log: couldn't send the log for task {task_id}: {e!r}")
    finally:
        if folder and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        drop_log(task_id)

    if status_msg is not None:
        try:
            if sent:
                await status_msg.delete()
            elif fallback_text:
                await status_msg.edit_text(fallback_text)
        except Exception:
            pass
    return sent
