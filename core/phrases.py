"""Multilingual yes/no and end-of-conversation detection for voice confirmations."""
from __future__ import annotations

import re

YES = ["yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "do it", "go ahead", "proceed",
       "haan", "han", "haa", "ji", "jee", "ji haan", "theek hai", "thik hai", "kar do", "karo",
       "ہاں", "جی", "جی ہاں", "ٹھیک ہے", "کر دو", "हाँ", "हां", "जी", "ठीक है", "कर दो",
       "sí", "si", "oui", "ja", "نعم", "是", "好", "はい", "ええ"]
NO = ["no", "nope", "cancel", "stop", "don't", "do not", "dont", "abort",
      "nahi", "nahin", "nai", "na", "mat", "mat karo", "rehne do", "ruko",
      "نہیں", "مت", "رہنے دو", "नहीं", "मत", "रहने दो", "non", "nein", "لا", "不", "不要", "いいえ"]
DISMISS = ["that's all", "thats all", "that is all", "nothing", "thank you", "thanks", "goodbye", "bye",
           "bas", "bas karo", "shukriya", "kuch nahi", "theek hai bas",
           "بس", "شکریہ", "کچھ نہیں", "बस", "धन्यवाद", "शुक्रिया", "कुछ नहीं", "gracias", "merci", "danke"]

_WORD = re.compile(r"[\w']+", re.UNICODE)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _contains(text: str, words: list[str], phrase: str) -> bool:
    p = phrase.lower()
    if not p.isascii() and " " not in p and len(p) <= 2:
        return p in text            # CJK / short scripts without spaces
    pw = _words(p)
    n = len(pw)
    return any(words[i:i + n] == pw for i in range(len(words) - n + 1))


def parse_yes_no(text: str) -> bool | None:
    """True / False, or None if unclear. 'No' wins over 'yes' so ambiguous answers fail safe."""
    t = text.lower()
    w = _words(t)
    if any(_contains(t, w, p) for p in NO):
        return False
    if any(_contains(t, w, p) for p in YES):
        return True
    return None


def is_dismissal(text: str) -> bool:
    t = text.lower()
    w = _words(t)
    return 0 < len(w) <= 4 and any(_contains(t, w, p) for p in DISMISS)
