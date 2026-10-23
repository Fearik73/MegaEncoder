
import itertools

from Encoder.config import ADMIN_IDS

_id_counter = itertools.count(1)

# Active task registry
_cancel_store: dict[int, dict] = {}
_cancelled:    set[int]        = set()


def is_admin(uid: int) -> bool:
    if uid in ADMIN_IDS:
        return True
    return False

def new_task_id() -> int:
    return next(_id_counter)

def register_task(task_id: int, process, stage: str, group_id: int = None, uid: int = None):
    _cancel_store[task_id] = {"process": process, "stage": stage, "group_id": group_id, "uid": uid}

def clear_task(task_id: int):
    _cancel_store.pop(task_id, None)

def is_cancelled(task_id: int) -> bool:
    return task_id in _cancelled

def mark_cancelled(task_id: int):
    _cancelled.add(task_id)

def clear_cancelled(task_id: int):
    _cancelled.discard(task_id)

# Cancel a running task
def cancel_task(task_id: int) -> bool:
    mark_cancelled(task_id)
    task = _cancel_store.get(task_id)
    if task:
        proc = task.get("process")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        clear_task(task_id)
    return True

def find_task_id(group_id: int, uid: int = None, stages=None):
    for tid, info in _cancel_store.items():
        if info.get("group_id") != group_id:
            continue
        if uid is not None and info.get("uid") != uid:
            continue
        if stages is not None and info.get("stage") not in stages:
            continue
        return tid
    return None
