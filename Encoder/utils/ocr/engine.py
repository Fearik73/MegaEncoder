import asyncio
import logging

from Encoder.utils.database.access_db import db
from Encoder.utils.ocr import config, ocr

log = logging.getLogger("ocr")

ready = asyncio.Event()
state = {"started": False, "error": None}


async def load_models():
    state["started"] = True
    try:
        config.apply(await db.get_ocr_config())
        await asyncio.to_thread(ocr.load)
        ready.set()
        print("✅ OCR ready")
        try:
            await asyncio.to_thread(ocr.start_pool, config.OCR_WORKERS)
            if config.OCR_WORKERS > 1:
                print(f"✅ OCR workers: {config.OCR_WORKERS}")
        except Exception as e:
            print(f"⚠️ OCR workers failed, scanning with one process: {e}")
    except Exception as e:
        state["error"] = str(e)
        print(f"⚠️ OCR load failed: {e}")
