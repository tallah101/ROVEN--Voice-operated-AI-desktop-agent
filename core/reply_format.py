"""Parse the model's final reply: [lang=xx] tag, display text, optional <speak> block for TTS."""
from __future__ import annotations

import re
from dataclasses import dataclass

LANG_RE = re.compile(r"^\s*\[lang=([A-Za-z]{2,3}(?:-[A-Za-z]{4})?)\]\s*", re.I)
SPEAK_RE = re.compile(r"<speak>(.*?)</speak>", re.S | re.I)


@dataclass
class Reply:
    display: str
    speech: str
    lang: str


def base_lang(tag: str | None) -> str:
    return (tag or "en").split("-")[0].lower()


def guess_lang_from_script(text: str, fallback: str = "en") -> str:
    counts = {"arabic": 0, "deva": 0, "guru": 0, "cjk": 0, "kana": 0}
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
            counts["arabic"] += 1
        elif 0x0900 <= o <= 0x097F:
            counts["deva"] += 1
        elif 0x0A00 <= o <= 0x0A7F:
            counts["guru"] += 1
        elif 0x3040 <= o <= 0x30FF:
            counts["kana"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["cjk"] += 1
    script, n = max(counts.items(), key=lambda kv: kv[1])
    if n < 3:
        return fallback
    if script == "arabic":
        return "ar" if base_lang(fallback) == "ar" else "ur"
    if counts["kana"] > 0:
        return "ja"
    return {"deva": "hi", "guru": "pa", "cjk": "zh"}.get(script, fallback)


def parse_reply(raw: str, fallback_lang: str = "en") -> Reply:
    text = (raw or "").strip()
    lang = None
    m = LANG_RE.match(text)
    if m:
        lang = m.group(1)
        text = text[m.end():]
    speech = None
    sm = SPEAK_RE.search(text)
    if sm:
        speech = sm.group(1).strip()
        text = SPEAK_RE.sub("", text).strip()
    if lang is None:
        lang = guess_lang_from_script(text, fallback_lang)
    text = text.strip()
    return Reply(display=text, speech=speech or text, lang=lang)
