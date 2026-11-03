import logging
import os

log = logging.getLogger("ocr")


def build(name=None):
    name = (name or os.environ.get("OCR_MODEL", "medium")).lower()
    if name != "old":
        try:
            from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

            size = getattr(ModelType, name.upper(), name)
            ver = getattr(OCRVersion, "PPOCRV6", "PP-OCRv6")
            params = {}
            for part in ("Det", "Rec"):
                params[f"{part}.engine_type"] = EngineType.ONNXRUNTIME
                params[f"{part}.ocr_version"] = ver
                params[f"{part}.model_type"] = size
            engine = RapidOCR(params=params)
            log.info("OCR model: PP-OCRv6 %s", name)
            return engine, "new"
        except Exception as e:
            log.warning("PP-OCRv6 %s failed (%s), trying the default model", name, e)
        try:
            from rapidocr import RapidOCR

            engine = RapidOCR()
            log.info("OCR model: rapidocr default")
            return engine, "new"
        except Exception as e:
            log.warning("rapidocr failed (%s), using the old model", e)
    from rapidocr_onnxruntime import RapidOCR

    log.info("OCR model: PP-OCRv4 (old)")
    return RapidOCR(), "old"
