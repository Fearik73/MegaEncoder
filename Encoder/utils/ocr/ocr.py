import difflib
import io
import json
import multiprocessing as mp
import os
import queue
import subprocess
import threading
from concurrent.futures import ProcessPoolExecutor, wait
from collections import Counter

import numpy as np

from Encoder.utils.ocr import config
from Encoder.utils.ocr.subs import clean, core_len

_engine = None
_kind = "new"
_lock = threading.Lock()
LANG = "zh"


def set_lang(lang: str):
    global LANG
    LANG = lang


def load():
    global _engine, _kind
    with _lock:
        if _engine is None:
            from Encoder.utils.ocr.ocr_model import build

            _engine, _kind = build(config.OCR_MODEL)
    return _engine


def _run(img):
    eng = load()
    if _kind == "old":
        result, _ = eng(img)
        return result or []
    try:
        out = eng(img, use_cls=False)
    except TypeError:
        out = eng(img)
    if out is None or getattr(out, "txts", None) is None:
        return []
    return list(zip(out.boxes, out.txts, out.scores))


def probe(path: str):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", path,
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("No video track found.")
    dur = float((data.get("format") or {}).get("duration") or 0)
    return int(streams[0]["width"]), int(streams[0]["height"]), dur


def _even(x: int) -> int:
    return x - x % 2


def region(W: int, H: int):
    ow = _even(min(W, 1920))
    oh = _even(round(H * ow / W))
    sh = _even(max(32, int(oh * config.OCR_STRIP)))
    cw = _even(int(ow * (1 - 2 * config.OCR_MARGIN)))
    x0 = _even(int(ow * config.OCR_MARGIN))
    return ow, oh, sh, oh - sh, cw, x0


def _enh(g: np.ndarray):
    try:
        import cv2

        return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(2, 8)).apply(g)
    except Exception:
        return g


_K = {}
OUT_DARK = 110
OUT_R = 3
_OK = {}


def _clean(g: np.ndarray):
    if config.OCR_LIFT <= 0:
        return g
    try:
        import cv2

        k = _K.get("k")
        if k is None:
            n = max(3, config.OCR_STROKE)
            k = _K["k"] = cv2.getStructuringElement(cv2.MORPH_RECT, (n, n))
        th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, k)
        return np.where(th >= config.OCR_LIFT, g, 0).astype(np.uint8)
    except Exception:
        return g


def _outline(g: np.ndarray, c: np.ndarray):
    if not config.OCR_OUTLINE:
        return c
    try:
        import cv2

        k = _OK.get("k")
        if k is None:
            k = _OK["k"] = np.ones((2 * OUT_R + 1, 2 * OUT_R + 1), np.uint8)
        near = cv2.dilate((g < OUT_DARK).astype(np.uint8), k) > 0
        return np.where(near, c, 0).astype(np.uint8)
    except Exception:
        return c


def _persist_k() -> int:
    return (config.OCR_PERSIST - 1) // 2 if config.OCR_PERSIST >= 3 else 0


def _focus(p: np.ndarray):
    import cv2

    n, lab, st, _ = cv2.connectedComponentsWithStats(p, connectivity=8)
    if n <= 1:
        return p
    w, h, a = st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT], st[:, cv2.CC_STAT_AREA]
    fill = a / np.maximum(w * h, 1)
    ok = (a >= 5) & (h <= config.OCR_CHAR) & (w <= int(config.OCR_CHAR * 1.3)) & ~((h >= 14) & (fill > 0.8))
    ok[0] = False
    keep = ok[lab]
    rows = keep.sum(1)
    idx = np.flatnonzero(rows >= 2)
    if not len(idx):
        return np.zeros_like(p)
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 14) + 1)
    cw = p.shape[1]
    cols = np.arange(cw)
    wts = []
    for r in runs:
        blk = keep[r[0] : r[-1] + 1]
        wt = float(blk.sum())
        cx = float((blk.sum(0) * cols).sum() / max(wt, 1))
        wts.append(wt * (1.0 if abs(cx - cw / 2) <= cw * 0.25 else 0.6))
    top = max(wts)
    out = np.zeros_like(p)
    for r, wt in zip(runs, wts):
        if wt < 0.3 * top:
            continue
        blk = keep[r[0] : r[-1] + 1]
        cs = np.flatnonzero(blk.sum(0) >= 1)
        groups = np.split(cs, np.flatnonzero(np.diff(cs) > config.OCR_GAP) + 1)
        gw = [
            float(blk[:, g[0] : g[-1] + 1].sum()) * (1.0 if abs((g[0] + g[-1]) / 2 - cw / 2) <= cw * 0.25 else 0.6)
            for g in groups
        ]
        gt = max(gw)
        for g, w2 in zip(groups, gw):
            if w2 >= 0.4 * gt:
                out[r[0] : r[-1] + 1, g[0] : g[-1] + 1] = blk[:, g[0] : g[-1] + 1]
    return out


def _refine(c: np.ndarray, pm: np.ndarray):
    if not pm.any():
        return np.zeros_like(c)
    try:
        import cv2

        p = _focus(pm.astype(np.uint8)) if config.OCR_FOCUS else pm.astype(np.uint8)
        if not p.any():
            return np.zeros_like(c)
        region = cv2.dilate(p, np.ones((3, 3), np.uint8), iterations=2) > 0
        return np.where(region, c, 0).astype(np.uint8)
    except Exception:
        return np.where(pm, c, 0).astype(np.uint8)


def _stream(proc, rsize, rgb, sh, cw):
    k = _persist_k()
    buf, base, nxt = [], 0, 0

    def make(n):
        i = n - base
        b = buf[i]
        m = b
        for j in range(max(0, i - k), min(len(buf), i + k + 1)):
            if j != i:
                m = np.minimum(m, buf[j])
        return _refine(b, m >= config.OCR_WHITE).tobytes()

    while True:
        raw = proc.stdout.read(rsize)
        if len(raw) < rsize:
            break
        g = np.frombuffer(raw, np.uint8)
        if rgb:
            g = g.reshape(-1, 3).min(1)
        g = np.ascontiguousarray(g.reshape(sh, cw))
        buf.append(_outline(g, _clean(g)))
        total = base + len(buf)
        while nxt <= total - 1 - k:
            yield make(nxt)
            nxt += 1
        drop = nxt - k - base
        if drop > 0:
            del buf[:drop]
            base += drop
    total = base + len(buf)
    while nxt < total:
        yield make(nxt)
        nxt += 1


def _prep(fr: np.ndarray, mode: str = "raw"):
    mask = fr >= config.OCR_WHITE
    rows = np.flatnonzero(mask.sum(1) >= 3)
    cols = np.flatnonzero(mask.sum(0) >= 2)
    if not len(rows) or not len(cols):
        return None
    pad = 20
    y0, y1 = max(rows[0] - pad, 0), min(rows[-1] + pad + 1, fr.shape[0])
    x0, x1 = max(cols[0] - pad, 0), min(cols[-1] + pad + 1, fr.shape[1])
    crop = np.ascontiguousarray(fr[y0:y1, x0:x1])
    if mode == "enh":
        crop = _enh(crop)
    elif mode == "thick":
        try:
            import cv2

            crop = cv2.dilate(crop, np.ones((2, 2), np.uint8))
        except Exception:
            pass
    elif mode == "bin":
        crop = np.where(crop >= config.OCR_WHITE, 0, 255).astype(np.uint8)
        try:
            import cv2

            crop = cv2.erode(crop, np.ones((2, 2), np.uint8))
        except Exception:
            pass
    if crop.shape[0] < 80:
        try:
            import cv2

            crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        except Exception:
            crop = np.repeat(np.repeat(crop, 2, 0), 2, 1)
    return np.ascontiguousarray(np.stack([crop] * 3, -1)), y0, crop.shape[0] / (y1 - y0)


def _overlap(a, b):
    ox = min(a[7], b[7]) - max(a[2], b[2])
    oy = min(a[6], b[6]) - max(a[5], b[5])
    return ox > 0.5 * min(a[7] - a[2], b[7] - b[2]) and oy > 0.5 * min(a[6] - a[5], b[6] - b[5])


def _dedupe(boxes):
    keep = []
    for b in sorted(boxes, key=lambda b: (-len(b[3]), -b[4])):
        if not any(_overlap(b, k) for k in keep):
            keep.append(b)
    return keep


def _read(img):
    result = _run(img)
    if not result:
        return None
    boxes = []
    for box, txt, score in result:
        if float(score) < 0.5:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append((sum(ys) / 4, max(ys) - min(ys), min(xs), txt.strip(), float(score), min(ys), max(ys), max(xs)))
    if not boxes:
        return None
    boxes = _dedupe(boxes)
    boxes.sort()
    h = sorted(b[1] for b in boxes)[len(boxes) // 2] or 1
    rows, cy = [], None
    for b in sorted(boxes, key=lambda b: (b[0], b[2])):
        if cy is None or abs(b[0] - cy) > 0.6 * h:
            rows.append([])
            cy = b[0]
        rows[-1].append(b)
    joiner = " " if LANG == "en" else ""
    text = " ".join(joiner.join(x[3] for x in sorted(r, key=lambda b: b[2])) for r in rows)
    text = clean(text, LANG)
    if not text:
        return None
    first = rows[0]
    geom = (min(b[5] for b in first), max(b[6] for b in first), len(rows))
    return text, sum(b[4] for b in boxes) / len(boxes), geom


def _ocr_one(fr: np.ndarray, mode: str = "raw"):
    p = _prep(fr, mode)
    if p is None:
        return None
    img, y0, scale = p
    r = _read(img)
    if r is None:
        return None
    g = r[2]
    return r[0], r[1], (y0 + g[0] / scale, y0 + g[1] / scale, g[2])


def _glare_ok(r):
    text, conf = r[0], r[1]
    if LANG == "en":
        return conf >= 0.6 and sum(c.isalnum() for c in text) >= 3
    return conf >= 0.6 and (len(text) >= 2 or conf >= 0.9)


def _ocr_strip(fr: np.ndarray):
    for enh in (False, True):
        g = _enh(fr) if enh else fr
        r = _read(np.ascontiguousarray(np.stack([g] * 3, -1)))
        if r and _glare_ok(r):
            return r[:2]
    return None


def _cjk(t: str) -> int:
    return sum(1 for c in t if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf")


def _expected(fr: np.ndarray) -> float:
    m = fr >= min(250, config.OCR_WHITE + 20)
    rows = np.flatnonzero(m.sum(1) >= 3)
    if not len(rows):
        return 0.0
    bands, a, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > 6:
            bands.append((a, prev))
            a = r
        prev = r
    bands.append((a, prev))
    total = 0.0
    for top, bot in bands:
        h = bot - top + 1
        cols = np.flatnonzero(m[top : bot + 1].sum(0) >= 2)
        if h >= 12 and len(cols):
            total += (cols[-1] - cols[0] + 1) / h
    return total


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if min(len(a), len(b)) >= 3 and (a in b or b in a):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def _vote(got):
    votes = Counter(t for t, _ in got)
    top = max(votes.values())
    best = max((r for r in got if votes[r[0]] == top), key=lambda r: r[1])[0]
    confs = [c for t, c in got if t == best]
    return best, sum(confs) / len(confs)


def _best(frames, shape):
    n = len(frames)

    def arr(i):
        return np.frombuffer(frames[i], np.uint8).reshape(shape)

    def read(i, mode="raw"):
        r = _ocr_one(arr(i), mode)
        return (*r, i) if r else None

    got = []
    bright, med = [], 0
    a = read(n // 2)
    if a:
        got.append(a)
        if a[1] >= 0.92:
            return a
    if n < 3:
        for i in range(n):
            if i != n // 2 and (r := read(i)):
                got.append(r)
    else:
        bright = [int(np.count_nonzero(arr(i) >= config.OCR_WHITE)) for i in range(n)]
        med = sorted(bright)[n // 2]
        order = sorted((i for i in range(n) if bright[i] >= 0.7 * med), key=lambda i: bright[i]) or list(range(n))
        order = order + order[:1]
        tried = {n // 2}
        for i in (order[0], n // 4, (3 * n) // 4, order[1], 1, n - 2):
            if i in tried or not 0 <= i < n:
                continue
            tried.add(i)
            r = read(i)
            if r:
                got.append(r)
                if r[1] >= 0.92:
                    break
            if len(tried) >= 3:
                break
    if not got or max(r[1] for r in got) < config.OCR_FLAG_CONF:
        pick = sorted(range(n), key=lambda i: abs(bright[i] - med))[:2] if n >= 3 else list(range(n))
        for mode in ("enh", "thick", "bin"):
            for i in pick:
                r = read(i, mode)
                if r:
                    got.append(r)
    if not got:
        return None
    return max(got, key=lambda r: (sum(1 for g in got if g[0] == r[0]), r[1], len(r[0])))


def _groups(hits, step):
    groups = []
    for t, text, conf in hits:
        g = groups[-1] if groups else None
        if g and t - g["t1"] <= 3 * step and _sim(g["hits"][0][0], text) >= 0.7:
            g["t1"] = t
            g["hits"].append((text, conf))
        else:
            groups.append({"t0": t, "t1": t, "hits": [(text, conf)]})
    for g in groups:
        g["text"], g["conf"] = _vote(g["hits"])
    return groups


SIMPLE = set("一二三十丨口日")


def _only_simple(text: str) -> bool:
    chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    return bool(chars) and all(c in SIMPLE for c in chars)


def _confirm(frames, shape, text, skip):
    n = len(frames)
    agree = seen = 0
    for i in sorted({n // 5, (2 * n) // 5, (3 * n) // 5, (4 * n) // 5}):
        if i == skip or not 0 <= i < n:
            continue
        r = _ocr_one(np.frombuffer(frames[i], np.uint8).reshape(shape))
        seen += 1
        if r and _sim(r[0], text) >= 0.8:
            agree += 1
    return agree, seen


def _short_ok(frames, shape, text, conf, idx, meta, ref):
    simple = _only_simple(text)
    aligned = None
    if len(ref) >= 3 and meta["bands"] == 1:
        mid = sorted(ref)[len(ref) // 2]
        aligned = abs(meta["top"] + meta["h1"] / 2 - mid) <= 0.02
        if not aligned:
            return False
    strict = simple and aligned is not True
    if strict and conf < 0.95:
        return False
    agree, seen = _confirm(frames, shape, text, idx)
    if seen == 0:
        return conf >= 0.9 and not simple
    return agree >= min(2 if strict else 1, seen)


def _events(path, is_cancelled, start, end):
    W, H, dur = probe(path)
    if dur and start >= dur:
        raise RuntimeError("Start time is beyond the end of the video.")
    stop = min(end, dur) if (end and dur) else (end or dur)
    span = (stop - start) if stop else 0
    ow, oh, sh, y, cw, x0 = region(W, H)
    fps = config.OCR_FPS
    half = 0.5 / fps
    fsize = cw * sh
    rgb = config.OCR_COLOR != "any"
    rsize = fsize * 3 if rgb else fsize
    lo = int(fsize * config.OCR_MIN_FRAC)
    hi = int(fsize * config.OCR_MAX_FRAC)
    min_n = max(2, round(config.OCR_MIN_LINE * fps))
    gstep = max(1, round(fps / 4))
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if end:
        cmd += ["-t", f"{max(end - start, 0.1):.3f}"]
    cmd += [
        "-an", "-sn",
        "-vf", f"fps={fps}:start_time=0,scale={ow}:{oh},crop={cw}:{sh}:{x0}:{y},format={'rgb24' if rgb else 'gray'}",
        "-f", "rawvideo", "-pix_fmt", "rgb24" if rgb else "gray", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=rsize * 2)
    cur = [start]
    ref = []

    def frac(t):
        return min(1.0, max(0.0, (t - start) / span)) if span else 0.0

    def measure(buf, geom):
        f = np.frombuffer(buf, np.uint8).reshape(sh, cw)
        t0, t1 = max(0, int(geom[0]) - 6), min(sh, int(geom[1]) + 7)
        win = f[t0:t1, int(cw * 0.2) : int(cw * 0.8)] >= config.OCR_WHITE
        rows = np.flatnonzero(win.sum(1) >= 8)
        if len(rows):
            top, bot = t0 + rows[0], t0 + rows[-1]
        else:
            top, bot = geom[0], geom[1]
        return {"top": (y + top) / oh, "h1": (bot - top + 1) / oh, "bands": geom[2]}

    def finish(line):
        n = line["n"]
        if n < 2:
            return None
        shift = _persist_k() / fps
        s, e = max(start, line["start"] - shift), line["last"] + half + shift
        res = _best(line["frames"], (sh, cw))
        if res is None:
            return ("unread", s, e, frac(cur[0])) if e - s >= 0.8 else None
        text, conf, geom, idx = res
        if core_len(text) < config.OCR_MIN_CHARS:
            return None
        flags = set()
        if n < min_n:
            if conf < config.OCR_FLAG_CONF or len(text) < 2:
                return None
            flags.add("short")
        if conf < config.OCR_FLAG_CONF:
            flags.add("low")
        meta = measure(line["frames"][idx], geom)
        meta["conf"] = conf
        if core_len(text) <= 2:
            if not _short_ok(line["frames"], (sh, cw), text, conf, idx, meta, ref):
                return None
        elif conf >= 0.9 and meta["bands"] == 1 and n >= min_n:
            ref.append(meta["top"] + meta["h1"] / 2)
        return ("line", {"start": s, "end": e, "text": text, "conf": conf, "flags": flags, "meta": meta})

    def glare(run):
        frames = run["frames"]
        if run["last"][0] != frames[-1][0]:
            frames = frames + [run["last"]]
        if len(frames) > 60:
            frames = frames[:: -(-len(frames) // 60)]
        hits = []
        for t, buf in frames:
            if is_cancelled():
                break
            r = _ocr_strip(np.frombuffer(buf, np.uint8).reshape(sh, cw))
            if r:
                hits.append((t, r[0], r[1]))
        return ("glare", {
            "start": max(start, run["t0"] - half), "end": run["t1"] + half,
            "hits": hits, "step": gstep / fps,
        })

    try:
        idx, prev, line, run, tick = 0, None, None, None, start
        pcnt, miss = 0, False
        frames = _stream(proc, rsize, rgb, sh, cw)
        while True:
            if is_cancelled():
                return
            buf = next(frames, None)
            if buf is None:
                break
            t = start + idx / fps
            cur[0] = t
            idx += 1
            mask = np.frombuffer(buf, np.uint8) >= config.OCR_WHITE
            cnt = int(np.count_nonzero(mask))
            if cnt > hi:
                miss = False
                if line:
                    ev = finish(line)
                    line = None
                    if ev:
                        yield ev
                prev = None
                if run is None:
                    run = {"t0": t, "frames": [(t, buf)], "n": 0}
                run["t1"] = t
                run["last"] = (t, buf)
                run["n"] += 1
                if run["n"] % gstep == 0 and len(run["frames"]) < 240:
                    run["frames"].append((t, buf))
                continue
            if run is not None:
                yield glare(run)
                run = None
            ok = cnt >= (lo // 2 if line is not None else lo)
            same = False
            if ok and line is not None and prev is not None:
                union = int(np.count_nonzero(mask | prev))
                inter = int(np.count_nonzero(mask & prev))
                small, big = min(cnt, pcnt), max(cnt, pcnt)
                same = union > 0 and (
                    inter / union >= config.OCR_SIM or (small >= 0.2 * big and inter / max(small, 1) >= 0.9)
                )
            if same:
                miss = False
                line["last"] = t
                line["n"] += 1
                if len(line["frames"]) < 160:
                    line["frames"].append(buf)
            elif ok and line is not None and not miss:
                miss = True
                continue
            else:
                miss = False
                if line:
                    ev = finish(line)
                    line = None
                    if ev:
                        yield ev
                if ok:
                    line = {"start": max(start, t - half), "last": t, "n": 1, "frames": [buf]}
            prev = mask if ok else None
            pcnt = cnt
            if t - tick >= 0.5:
                tick = t
                yield ("tick", t, frac(t), line["start"] if line else None)
        if run is not None and not is_cancelled():
            yield glare(run)
        if line and not is_cancelled():
            ev = finish(line)
            if ev:
                yield ev
    finally:
        proc.kill()
        proc.stdout.close()
        proc.wait()


def scan(path: str, is_cancelled, start: float = 0.0, end=None, lang: str = "zh"):
    set_lang(lang)
    held, fr, beat = None, 0.0, start

    def out(L):
        return (L["start"], L["end"], L["text"], fr, ",".join(sorted(L["flags"])), L.get("meta"))

    for ev in _events(path, is_cancelled, start, end):
        kind = ev[0]
        if kind == "tick":
            fr = ev[2]
            if held and ev[1] - held["end"] > 1.2 and (ev[3] is None or ev[3] - held["end"] > 1.0):
                yield out(held)
                held = None
            if ev[1] - beat >= 20:
                beat = ev[1]
                yield (None, None, None, fr, "beat", None)
        elif kind == "unread":
            if held:
                yield out(held)
                held = None
            yield (ev[1], ev[2], None, ev[3], "unread", None)
        elif kind == "line":
            L = ev[1]
            if held:
                gl = "glare" in held["flags"]
                same_short = held["text"] == L["text"] and len(L["text"]) <= 2
                if L["start"] - held["end"] <= (1.0 if (gl or same_short) else 0.35) and _sim(held["text"], L["text"]) >= (0.7 if gl else 0.85):
                    if gl:
                        held["text"], held["conf"] = L["text"], L["conf"]
                    held["meta"] = held.get("meta") or L.get("meta")
                    held["end"] = max(held["end"], L["end"])
                    held["flags"] |= L["flags"]
                    continue
                yield out(held)
            held = L
        elif kind == "glare":
            G = ev[1]
            groups = _groups(G["hits"], G["step"])
            if not groups:
                if G["end"] - G["start"] >= 0.5:
                    if held:
                        yield out(held)
                        held = None
                    yield (G["start"], G["end"], None, fr, "unread", None)
                continue
            for g in groups:
                if core_len(g["text"]) < config.OCR_MIN_CHARS:
                    continue
                if core_len(g["text"]) <= 2:
                    if _only_simple(g["text"]) or len(g["hits"]) < 2 or sum(1 for t, _ in g["hits"] if t == g["text"]) < 2:
                        continue
                gs = max(G["start"], g["t0"] - G["step"] / 2)
                ge = min(G["end"], g["t1"] + G["step"] / 2)
                if held and gs - held["end"] <= 1.0 and _sim(held["text"], g["text"]) >= 0.7:
                    held["end"] = max(held["end"], ge)
                    held["flags"].add("glare")
                    continue
                if held:
                    yield out(held)
                held = {"start": gs, "end": ge, "text": g["text"], "conf": g["conf"], "flags": {"glare"}}
    if held:
        yield out(held)


def video_size(path: str):
    W, H, _ = probe(path)
    return W, H


def test_image(data: bytes, lang: str = "zh"):
    set_lang(lang)
    from PIL import Image, ImageDraw

    im = Image.open(io.BytesIO(data)).convert("RGB")
    W, H = im.size
    ow, oh, sh, y, cw, x0 = region(W, H)
    small = im.resize((ow, oh))
    gray = np.asarray(small).min(2) if config.OCR_COLOR != "any" else np.asarray(small.convert("L"))
    raw = np.ascontiguousarray(gray[y : y + sh, x0 : x0 + cw])
    gray = _outline(raw, _clean(raw))
    gray = _refine(gray, gray >= config.OCR_WHITE)
    cnt = int(np.count_nonzero(gray >= config.OCR_WHITE))
    area = gray.size
    lo, hi = int(area * config.OCR_MIN_FRAC), int(area * config.OCR_MAX_FRAC)
    state = "none" if cnt < lo else ("glare" if cnt > hi else "ok")
    r = _ocr_one(gray) if state != "glare" else _ocr_strip(gray)
    sx, sy = W / ow, H / oh
    d = ImageDraw.Draw(im)
    d.rectangle((x0 * sx, y * sy, (x0 + cw) * sx, (y + sh) * sy), outline=(0, 255, 0), width=max(3, W // 400))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    info = {
        "strip": config.OCR_STRIP * 100,
        "margin": config.OCR_MARGIN * 100,
        "white": cnt * 100 / area,
        "min": config.OCR_MIN_FRAC * 100,
        "max": config.OCR_MAX_FRAC * 100,
        "limit": config.OCR_WHITE,
        "state": state,
        "text": r[0] if r else None,
        "conf": r[1] * 100 if r else None,
        "chars": (_cjk(r[0]), _expected(gray)) if (r and lang == "zh") else None,
    }
    return buf.getvalue(), info


_CTX = "spawn"
_pool = None
_q = None
_cancel = None
_nworkers = 1
_W = {}


def _init(q, cancel, threads, cfg):
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(threads)
    _W["q"], _W["cancel"] = q, cancel
    config.apply(cfg)
    load()


def _warm():
    return True


def _part(idx, path, a, b, lo, hi, lang, cfg):
    q, cancel = _W["q"], _W["cancel"]
    config.apply(cfg)
    try:
        for s, e, text, fr, flag, meta in scan(path, cancel.is_set, a, b, lang):
            if flag == "beat":
                q.put(("beat", idx, fr))
            elif (text is not None or flag == "unread") and lo <= s < hi:
                q.put(("line", idx, s, e, text, fr, flag, meta))
        q.put(("done", idx))
    except Exception as ex:
        q.put(("error", idx, str(ex)))


def start_pool(workers: int):
    global _pool, _q, _cancel, _nworkers
    if workers < 2:
        return
    ctx = mp.get_context(_CTX)
    _q, _cancel = ctx.Queue(), ctx.Event()
    threads = max(1, (os.cpu_count() or workers) // workers)
    _pool = ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init, initargs=(_q, _cancel, threads, config.snapshot()))
    _nworkers = workers
    done, _ = wait([_pool.submit(_warm) for _ in range(workers)])
    if any(f.exception() for f in done):
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
        raise RuntimeError("OCR workers could not start")


def scan_auto(path: str, is_cancelled, start: float = 0.0, end=None, lang: str = "zh"):
    W, H, dur = probe(path)
    stop = min(end, dur) if (end and dur) else (end or dur)
    span = (stop - start) if stop else 0
    if _pool is None or span < config.OCR_PARALLEL_MIN:
        yield from scan(path, is_cancelled, start, end, lang)
        return
    n, ov = _nworkers, 10.0
    bounds = [start + span * i / n for i in range(n + 1)]
    _cancel.clear()
    futs = []
    try:
        for i in range(n):
            lo = -1.0 if i == 0 else bounds[i]
            hi = 1e12 if i == n - 1 else bounds[i + 1]
            a = max(start, bounds[i] - ov)
            b = end if i == n - 1 else bounds[i + 1] + ov
            futs.append(_pool.submit(_part, i, path, a, b, lo, hi, lang, config.snapshot()))
    except Exception:
        globals()["_pool"] = None
        yield from scan(path, is_cancelled, start, end, lang)
        return
    done, frac = set(), [0.0] * n
    try:
        while len(done) < n:
            if is_cancelled():
                return
            try:
                msg = _q.get(timeout=0.5)
            except queue.Empty:
                for f in futs:
                    if f.done() and f.exception():
                        raise RuntimeError(f"OCR worker failed: {f.exception()}")
                if all(f.done() for f in futs):
                    raise RuntimeError("OCR workers stopped unexpectedly")
                continue
            kind, idx = msg[0], msg[1]
            if kind == "line":
                frac[idx] = msg[5]
                yield (msg[2], msg[3], msg[4], sum(frac) / n, msg[6], msg[7])
            elif kind == "beat":
                frac[idx] = msg[2]
                yield (None, None, None, sum(frac) / n, "beat", None)
            elif kind == "done":
                done.add(idx)
                frac[idx] = 1.0
            elif kind == "error":
                raise RuntimeError(msg[2])
    finally:
        _cancel.set()
        wait(futs, timeout=60)
        while True:
            try:
                _q.get_nowait()
            except queue.Empty:
                break
        _cancel.clear()


def merge(items: list, gap: float = 0.4):
    out = []
    for it in items:
        if out and out[-1]["zh"] == it["zh"] and it["start"] - out[-1]["end"] <= gap:
            out[-1]["end"] = it["end"]
            fl = set(filter(None, (out[-1].get("flag", "") + "," + it.get("flag", "")).split(",")))
            out[-1]["flag"] = ",".join(sorted(fl))
        else:
            out.append(it)
    return out
        
