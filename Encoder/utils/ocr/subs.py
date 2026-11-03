import re
import textwrap

MIN_DUR = 0.8

ZH_PUNCT = "，。！？、：；…—～·“”‘’《》（）【】「」『』"
EN_PUNCT = " .,!?'\"-:;()&%$#@/"


def clean(text: str, lang: str) -> str:
    if lang == "en":
        out = "".join(c for c in text if (c.isascii() and c.isalnum()) or c in EN_PUNCT)
        return " ".join(out.split())
    out = "".join(c for c in text if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" or c in ZH_PUNCT)
    return re.sub("一{2,}", "一", out)


def core_len(text: str) -> int:
    return sum(1 for c in text if not c.isspace() and c not in ZH_PUNCT and c not in EN_PUNCT)


def srt_time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def tidy(items: list):
    for i, it in enumerate(items):
        if i and it["start"] < items[i - 1]["start"]:
            it["start"] = items[i - 1]["start"]
        it["end"] = max(it["end"], it["start"] + MIN_DUR)
        if i + 1 < len(items):
            nxt = items[i + 1]["start"]
            if it["end"] > nxt:
                it["end"] = max(it["start"] + 0.1, nxt)


def srt_block(i: int, it: dict, key: str = "en") -> str:
    text = it[key]
    if key == "en":
        text = textwrap.fill(text, 42)
    return f"{i}\n{srt_time(it['start'])} --> {srt_time(it['end'])}\n{text}\n"


def build_srt(items: list, key: str) -> str:
    return "\n".join(srt_block(i, it, key) for i, it in enumerate(items, 1))
