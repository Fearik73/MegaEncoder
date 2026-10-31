import asyncio
import time

import psutil

_SKIP = ("lo", "docker", "veth", "br-")


def read() -> tuple[int, int]:
    rx = tx = 0
    for name, n in psutil.net_io_counters(pernic=True).items():
        if name.startswith(_SKIP):
            continue
        rx += n.bytes_recv
        tx += n.bytes_sent
    return rx, tx


_base = read()


def session_totals() -> tuple[int, int]:
    rx, tx = read()
    return max(0, rx - _base[0]), max(0, tx - _base[1])


def month_key() -> str:
    return time.strftime("%Y-%m", time.gmtime())


async def speed() -> tuple[int, int]:
    a = read()
    await asyncio.sleep(1)
    b = read()
    return max(0, b[0] - a[0]), max(0, b[1] - a[1])


async def tracker():
    from Encoder.utils.database.access_db import db
    last = read()
    while True:
        await asyncio.sleep(60)
        try:
            cur = read()
            drx = cur[0] - last[0] if cur[0] >= last[0] else cur[0]
            dtx = cur[1] - last[1] if cur[1] >= last[1] else cur[1]
            last = cur
            if drx or dtx:
                await db.add_bandwidth(month_key(), drx, dtx)
        except Exception as e:
            print(f"[bandwidth] tracker error: {e!r}")
  
