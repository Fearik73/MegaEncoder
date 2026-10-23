import asyncio
from collections import defaultdict


# Per-group queue state
_queues:            dict[int, asyncio.Queue] = {}
_workers_started:   dict[int, bool]          = {}
_group_pending:     dict[int, int]           = defaultdict(int)
_active_group_uid:  dict[int, int]           = {}


def _get_queue(group_id: int) -> asyncio.Queue:
    if group_id not in _queues:
        _queues[group_id] = asyncio.Queue()
    return _queues[group_id]


async def enqueue(group_id: int, job: dict) -> int:
    _group_pending[group_id] += 1
    q = _get_queue(group_id)
    await q.put(job)
    active = 1 if group_id in _active_group_uid else 0
    return q.qsize() + active


def group_queue_size(group_id: int) -> int:
    return _queues[group_id].qsize() if group_id in _queues else 0


def group_pending(group_id: int) -> int:
    return _group_pending.get(group_id, 0)


def is_group_active(group_id: int) -> bool:
    return group_id in _active_group_uid


def get_active_uid(group_id: int) -> int | None:
    return _active_group_uid.get(group_id)


def get_all_active_groups() -> list[int]:
    return list(_active_group_uid.keys())


def is_worker_running(group_id: int) -> bool:
    return _workers_started.get(group_id, False)


def clear_queue(group_id: int) -> int:
    q = _queues.get(group_id)
    if not q:
        return 0
    cleared = 0
    while not q.empty():
        try:
            q.get_nowait()
            cleared += 1
        except asyncio.QueueEmpty:
            break
    _group_pending[group_id] = 0
    return cleared


async def group_queue_worker(client, group_id: int):
    from Encoder.utils.tasks.encode_job import run_encode_job
    from Encoder.utils.tasks.sub_jobs import run_addsub_job, run_extractsub_job
    _workers_started[group_id] = True
    q = _get_queue(group_id)
    try:
        while True:
            job = await q.get()
            uid = job.get("uid") or job["msg"].from_user.id
            _active_group_uid[group_id] = uid
            _group_pending[group_id] = max(0, _group_pending.get(group_id, 0) - 1)
            try:
                kind = job.get("kind", "encode")
                if kind == "addsub":
                    await run_addsub_job(client, job, group_id)
                elif kind == "extractsub":
                    await run_extractsub_job(client, job, group_id)
                else:
                    await run_encode_job(client, job, group_id)
            except Exception as e:
                from Encoder.utils.helpers import log_error
                log_error(f"group_queue_worker (group={group_id}, uid={uid})", e)
                target = job.get("msg") or job.get("src_msg")
                try:
                    sent_log = False
                    if target and job.get("_task_id") is not None:
                        from Encoder.utils.logs.tasklog import tfail, send_failure_log
                        tfail(job["_task_id"], "worker", "Unexpected error", e)
                        sent_log = await send_failure_log(
                            target, job["_task_id"], "Unexpected error",
                            job.get("_status"), "❌ Unexpected error occurred",
                        )
                    if target and not sent_log and not job.get("_status"):
                        await target.reply(f"❌ Unexpected error occurred")
                except Exception as e2:
                    log_error("group_queue_worker: failed to notify user", e2)
            finally:
                _active_group_uid.pop(group_id, None)
                q.task_done()
    finally:
        _workers_started[group_id] = False
