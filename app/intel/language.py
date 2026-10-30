"""Lightweight language identification (script ranges + stop-word voting). Good enough to pick the answer language and to
tag documents; not a replacement for a trained model on short or mixed-language text."""
from __future__ import annotations

import re

SCRIPTS = [("hi", r"[ऀ-ॿ]"), ("bn", r"[ঀ-৿]"), ("ta", r"[஀-௿]"), ("te", r"[ఀ-౿]"), ("ar", r"[؀-ۿ]"),
           ("he", r"[֐-׿]"), ("ru", r"[Ѐ-ӿ]"), ("el", r"[Ͱ-Ͽ]"), ("th", r"[฀-๿]"), ("ja", r"[぀-ヿ]"),
           ("ko", r"[가-힯]"), ("zh", r"[一-鿿]")]
STOP = {
    "en": "the and of to in is that for with as on are this be by or from at an it was which have not",
    "es": "el la los las de que y en un una es por con para del se no su al lo como más pero sus",
    "fr": "le la les de des et en un une est que pour dans qui sur pas au avec ce il elle plus par",
    "de": "der die das und ist nicht ein eine zu den mit von für auf dem des sich auch es im",
    "pt": "o a os as de que e do da em um uma para com não é por mais os se na no das como",
    "it": "il lo la i gli le di che e un una è per con non del della in da sono più come",
}
NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian", "hi": "Hindi", "bn": "Bengali", "ta": "Tamil",
         "te": "Telugu", "ar": "Arabic", "he": "Hebrew", "ru": "Russian", "el": "Greek", "th": "Thai", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"}


def detect_language(text: str) -> str:
    sample = text[:4000]
    letters = [c for c in sample if c.isalpha()]
    if not letters:
        return "en"
    for code, pat in SCRIPTS:
        if len(re.findall(pat, sample)) > 0.3 * len(letters):
            return code
    words = re.findall(r"\w+", sample.lower())
    if not words:
        return "en"
    scores = {code: sum(1 for w in words if w in set(sw.split())) for code, sw in STOP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 or len(words) <= 4 and scores[best] >= 1 else "en"


def language_name(code: str) -> str:
    return NAMES.get(code, code)
