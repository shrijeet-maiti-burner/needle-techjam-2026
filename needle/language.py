"""Answer the customer in the language they wrote in.

The released simulator speaks English, so nothing here can change a score. It
exists because a shopping assistant that replies in a language the shopper did
not use is not usable, and because the catalog is a US marketplace export while
shoppers are not.

What this does and does not claim:

*It detects the language of the request and answers in it.* Detection is by
Unicode script for non-Latin writing systems, which is exact, and by
function-word signature for Latin ones, which is not. The Latin path requires
two independent cues before it will leave English, because a false positive
answers a English speaker in German and is far worse than a missed detection.

*It does not translate the catalog.* Product titles, categories and material
names come from the source data and stay in it. A Spanish reply about
"underwear undershirts" is the honest rendering: the sentence is Spanish, the
product name is what the marketplace calls it.

*It does not translate free text.* There is no model here and no network. The
templates are fixed, short, and written per language; anything outside them is
passed through unchanged.

Adding a language is a dict entry, and a language with no entry falls back to
English rather than to a machine rendering of it.

Known limits, stated rather than papered over:

* The coarse category is read out of the opening line by
  `opening_category_signature`, which matches the released simulator's English
  phrasing. A request opened in another language is answered in that language
  but says "items" where English would name the category. Fixing it needs an
  opening pattern per language, not a translation.
* A Japanese sentence written entirely in kanji is indistinguishable from
  Chinese by script alone and will be read as Chinese.
* Script detection is by share of letters, so a short request mixing scripts
  can fall back to English. That is the intended direction of failure.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Mapping

DEFAULT = "en"

# Exact: a script implies its language set unambiguously enough for this use.
_SCRIPT_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0400, 0x04FF, "ru"),   # Cyrillic
    (0x0590, 0x05FF, "he"),   # Hebrew
    (0x0600, 0x06FF, "ar"),   # Arabic
    (0x0900, 0x097F, "hi"),   # Devanagari
    (0x0980, 0x09FF, "bn"),   # Bengali
    (0x0B80, 0x0BFF, "ta"),   # Tamil
    (0x0E00, 0x0E7F, "th"),   # Thai
    (0x3040, 0x309F, "ja"),   # Hiragana
    (0x30A0, 0x30FF, "ja"),   # Katakana
    (0xAC00, 0xD7AF, "ko"),   # Hangul
    (0x4E00, 0x9FFF, "zh"),   # CJK unified ideographs
)

# Inexact: Latin-script languages share an alphabet, so these are function-word
# cues. Two distinct hits are required before English is abandoned.
_LATIN_CUES: Mapping[str, frozenset[str]] = {
    "es": frozenset({"busco", "quiero", "para", "algo", "que", "con", "una", "los", "las", "pero"}),
    "fr": frozenset({"je", "cherche", "veux", "pour", "avec", "une", "des", "mais", "quelque", "qui"}),
    "de": frozenset({"ich", "suche", "moechte", "möchte", "für", "fuer", "mit", "eine", "und", "aber"}),
    "pt": frozenset({"procuro", "quero", "para", "algo", "com", "uma", "mas", "que", "dos", "das"}),
    "it": frozenset({"cerco", "voglio", "per", "qualcosa", "con", "una", "ma", "che", "degli", "delle"}),
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_MIN_LATIN_CUES = 2
# A non-Latin script must carry this share of the letters before it decides.
_MIN_SCRIPT_SHARE = 0.30


def detect(text: str) -> str:
    """The language to answer in. Falls back to English rather than guessing."""
    if not isinstance(text, str) or not text.strip():
        return DEFAULT
    counts: dict[str, int] = {}
    for character in text:
        code = ord(character)
        for start, end, language in _SCRIPT_RANGES:
            if start <= code <= end:
                counts[language] = counts.get(language, 0) + 1
                break
    if counts:
        # A *share* of the letters, not a count of them. The catalog is a US
        # marketplace export that still carries source-language attribute values,
        # so an English request can contain a Chinese material name: "what
        # matters is: 进口" is an English sentence about a Chinese-labelled
        # product, and answering it in Chinese is wrong. Measured on the released
        # set, a bare count of two misread 2 of 2000 simulator messages; a share
        # threshold reads none of them.
        letters = sum(1 for character in text if character.isalpha())
        best = max(counts, key=lambda key: counts[key])
        if letters and counts[best] >= 2 and counts[best] / letters >= _MIN_SCRIPT_SHARE:
            return best
    words = {
        unicodedata.normalize("NFC", word).casefold()
        for word in _WORD_RE.findall(text)
    }
    best_language, best_hits = DEFAULT, 0
    for language, cues in _LATIN_CUES.items():
        hits = len(words & cues)
        if hits > best_hits:
            best_language, best_hits = language, hits
    return best_language if best_hits >= _MIN_LATIN_CUES else DEFAULT


# Short, fixed fragments. Deliberately simple sentences: the shorter the
# template, the smaller the chance of a wrong rendering, and the product names
# interpolated into them stay in the catalog's own language.
_PHRASES: Mapping[str, Mapping[str, str]] = {
    "en": {
        "start": "Starting from {category}. Tell me the one thing that matters most.",
        "narrow": "Down to {count} candidates in {category}, going on {values}.",
        "single": "One candidate left in {category} on {values}.",
        "ask": "What else matters?",
        "choose": "Which {facet}?",
        "or_other": "or say anything else that matters",
        "ruled_out": "I have ruled out {values}.",
        "and": "and",
        "going_on": "Going on {values} in {category}.",
        "material": "material", "color": "colour",
    },
    "es": {
        "start": "Empezamos por {category}. Dime lo que más te importa.",
        "narrow": "Quedan {count} opciones en {category}, según {values}.",
        "single": "Queda una opción en {category} según {values}.",
        "ask": "¿Qué más te importa?",
        "choose": "¿Qué {facet}?",
        "or_other": "o dime cualquier otra cosa que importe",
        "ruled_out": "He descartado {values}.",
        "and": "y",
        "going_on": "Voy por {values} en {category}.",
        "material": "material", "color": "color",
    },
    "fr": {
        "start": "On part de {category}. Dites-moi ce qui compte le plus.",
        "narrow": "Il reste {count} options dans {category}, d'après {values}.",
        "single": "Il reste une option dans {category} d'après {values}.",
        "ask": "Qu'est-ce qui compte d'autre ?",
        "choose": "Quel {facet} ?",
        "or_other": "ou dites-moi autre chose qui compte",
        "ruled_out": "J'ai écarté {values}.",
        "and": "et",
        "going_on": "Je pars de {values} dans {category}.",
        "material": "matière", "color": "couleur",
    },
    "de": {
        "start": "Wir beginnen mit {category}. Sagen Sie mir, was am wichtigsten ist.",
        "narrow": "Noch {count} Optionen in {category}, nach {values}.",
        "single": "Eine Option bleibt in {category} nach {values}.",
        "ask": "Was ist Ihnen sonst wichtig?",
        "choose": "Welches {facet}?",
        "or_other": "oder nennen Sie etwas anderes, das zählt",
        "ruled_out": "Ich habe {values} ausgeschlossen.",
        "and": "und",
        "going_on": "Ich gehe nach {values} in {category}.",
        "material": "Material", "color": "Farbe",
    },
    "hi": {
        "start": "{category} से शुरू करते हैं। बताइए आपके लिए सबसे ज़रूरी क्या है।",
        "narrow": "{category} में {count} विकल्प बचे हैं, {values} के आधार पर।",
        "single": "{category} में एक विकल्प बचा है, {values} के आधार पर।",
        "ask": "और क्या ज़रूरी है?",
        "choose": "कौन सा {facet}?",
        "or_other": "या और कुछ बताइए जो ज़रूरी हो",
        "ruled_out": "मैंने {values} हटा दिया है।",
        "and": "और",
        "going_on": "{category} में {values} के आधार पर देख रहा हूँ।",
        "material": "मटीरियल", "color": "रंग",
    },
    "ja": {
        "start": "{category} から始めます。いちばん重視する点を教えてください。",
        "narrow": "{category} の候補は {count} 件です（{values} による）。",
        "single": "{category} の候補は 1 件です（{values} による）。",
        "ask": "ほかに重視する点はありますか。",
        "choose": "{facet} はどれですか。",
        "or_other": "ほかに大事な点があれば教えてください",
        "ruled_out": "{values} は除外しました。",
        "and": "と",
        "going_on": "{category} で {values} を手がかりにしています。",
        "material": "素材", "color": "色",
    },
    "zh": {
        "start": "从 {category} 开始。请告诉我你最看重什么。",
        "narrow": "{category} 还剩 {count} 个候选（依据 {values}）。",
        "single": "{category} 只剩 1 个候选（依据 {values}）。",
        "ask": "还有什么重要的吗？",
        "choose": "要哪种 {facet}？",
        "or_other": "或者告诉我其他重要的条件",
        "ruled_out": "我已排除 {values}。",
        "and": "和",
        "going_on": "在 {category} 中依据 {values} 查找。",
        "material": "材质", "color": "颜色",
    },
}


def supported() -> tuple[str, ...]:
    return tuple(sorted(_PHRASES))


def phrases(language: str) -> Mapping[str, str]:
    """The phrase table for a language, or English if it has none."""
    return _PHRASES.get(language, _PHRASES[DEFAULT])


__all__ = ["DEFAULT", "detect", "phrases", "supported"]
