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

* A Japanese sentence written entirely in kanji is indistinguishable from
  Chinese by script alone, and no amount of tuning fixes that: the characters
  really are the same. A caller that knows better -- a browser locale, an
  account setting -- can say so with `Agent.set_language`, which is the honest
  answer to an ambiguity rather than a heuristic dressed up as one.
* Script detection is by share of letters, so a short request mixing scripts
  can fall back to English. That is the intended direction of failure.
* The category lexicon is deliberately partial. A shopping noun it does not
  know resolves to nothing rather than to a wrong category.
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
# Two cues are required, so the sets need enough coverage that an ordinary short
# request reaches the threshold: "Busco unos cinturones de cuero" is
# unmistakably Spanish and was falling back to English on one cue. Every entry
# is a word that is not also ordinary English, for the same reason the category
# lexicon drops such terms.
_LATIN_CUES: Mapping[str, frozenset[str]] = {
    "es": frozenset({
        "busco", "buscando", "quiero", "necesito", "estoy", "para", "algo",
        "que", "con", "una", "unos", "unas", "los", "las", "pero", "del",
    }),
    "fr": frozenset({
        "je", "cherche", "recherche", "veux", "besoin", "pour", "avec", "une",
        "des", "mais", "quelque", "qui", "du", "aux",
    }),
    "de": frozenset({
        "ich", "suche", "moechte", "möchte", "brauche", "für", "fuer", "mit",
        "eine", "einen", "und", "aber", "aus", "noch",
    }),
    "pt": frozenset({
        "procuro", "quero", "preciso", "para", "algo", "com", "uma", "mas",
        "que", "dos", "das", "ainda",
    }),
    "it": frozenset({
        "cerco", "voglio", "per", "qualcosa", "con", "una", "ma", "che",
        "degli", "delle", "sto", "ancora",
    }),
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_MIN_LATIN_CUES = 2
# A non-Latin script must carry this share of the letters before it decides.
_MIN_SCRIPT_SHARE = 0.30
# Word boundaries for Latin lexicon terms, so "rock" does not match "rocket".
BOUNDARY = r"\b{term}\b"


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
        "style": "style", "use_case": "use", "size": "size", "budget": "budget", "items": "the catalog", "stop": ".",
        "brand": "brand", "category": "kind",
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
        "style": "estilo", "use_case": "uso", "size": "talla", "budget": "presupuesto", "items": "el catálogo", "stop": ".",
        "brand": "marca", "category": "tipo",
    },
    "fr": {
        "start": "On part de {category}. Dites-moi ce qui compte le plus.",
        "narrow": "Il reste {count} options dans {category}, d'après {values}.",
        "single": "Il reste une option dans {category} d'après {values}.",
        "ask": "Qu'est-ce qui compte d'autre ?",
        "choose": "{facet} ?",
        "or_other": "ou dites-moi autre chose qui compte",
        "ruled_out": "J'ai écarté {values}.",
        "and": "et",
        "going_on": "Je pars de {values} dans {category}.",
        "material": "Quelle matière", "color": "Quelle couleur",
        "style": "Quel style", "use_case": "Quel usage", "size": "Quelle taille", "budget": "Quel budget", "items": "notre catalogue", "stop": ".",
        "brand": "Quelle marque", "category": "Quel type",
    },
    "de": {
        "start": "Wir beginnen mit {category}. Sagen Sie mir, was am wichtigsten ist.",
        "narrow": "Noch {count} Optionen in {category}, nach {values}.",
        "single": "Eine Option bleibt in {category} nach {values}.",
        "ask": "Was ist Ihnen sonst wichtig?",
        "choose": "{facet}?",
        "or_other": "oder nennen Sie etwas anderes, das zählt",
        "ruled_out": "Ich habe {values} ausgeschlossen.",
        "and": "und",
        "going_on": "Ich gehe nach {values} in {category}.",
        "material": "Welches Material", "color": "Welche Farbe",
        "style": "Welcher Stil", "use_case": "Welcher Einsatz", "size": "Welche Größe", "budget": "Welches Budget", "items": "unserem Katalog", "stop": ".",
        "brand": "Welche Marke", "category": "Welche Art",
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
        "style": "स्टाइल", "use_case": "इस्तेमाल", "size": "साइज़", "budget": "बजट", "items": "कैटलॉग", "stop": "।",
        "brand": "ब्रांड", "category": "प्रकार",
    },
    "ja": {
        "start": "{category}から始めます。いちばん重視する点を教えてください。",
        "narrow": "{category}の候補は{count}件です（{values}による）。",
        "single": "{category} の候補は 1 件です（{values} による）。",
        "ask": "ほかに重視する点はありますか。",
        "choose": "{facet}はどれですか。",
        "or_other": "ほかに大事な点があれば教えてください",
        "ruled_out": "{values} は除外しました。",
        "and": "と",
        "going_on": "{category}で{values}を手がかりにしています。",
        "material": "素材", "color": "色",
        "style": "スタイル", "use_case": "用途", "size": "サイズ", "budget": "予算", "items": "カタログ", "stop": "。",
        "brand": "ブランド", "category": "種類",
    },
    "zh": {
        "start": "从{category}开始。请告诉我你最看重什么。",
        "narrow": "{category}还剩 {count} 个候选（依据 {values}）。",
        "single": "{category} 只剩 1 个候选（依据 {values}）。",
        "ask": "还有什么重要的吗？",
        "choose": "要哪种{facet}？",
        "or_other": "或者告诉我其他重要的条件",
        "ruled_out": "我已排除 {values}。",
        "and": "和",
        "going_on": "在{category}中依据 {values} 查找。",
        "material": "材质", "color": "颜色",
        "style": "款式", "use_case": "用途", "size": "尺码", "budget": "预算", "items": "商品目录", "stop": "。",
        "brand": "品牌", "category": "类型",
    },
}


# Shopping nouns to the English words the catalog's own coarse categories use.
#
# A term that is also an ordinary English word cannot be here. The lexicon is
# consulted whenever the opening pattern finds no category, including on English
# requests the pattern simply did not match, and "collar" (Spanish, necklace),
# "pull" (French, sweater), "hose" and "rock" (German, trousers and skirt) then
# read English text as a request for something else:
#
#   "For that, what matters is: Pull On closure."  -> sweaters
#   "a shirt with a button collar"                 -> necklaces
#
# which keys the disclosure bucket on a category the customer never asked for.
# The EXP-010 gates do not move either way -- they are identical to main with
# these terms in or out -- so this is a latent correctness fix, not a measured
# score or robustness one.
#
# They are dropped rather than gated behind language detection, because
# detection is deliberately conservative and a short request like "Busco unos
# cinturones" does not reach its two-cue threshold. Gating would lose the
# category for exactly the customers this exists for.
# Hand-checked, and deliberately partial: a term is here only when its English
# mapping is the word the marketplace actually files the product under, so a
# miss falls through to no category rather than to a wrong one.
#
# This exists because the category is the strongest single key the agent has --
# it qualifies the disclosure bucket, not just the sentence -- and a shopper
# writing in Spanish was losing it entirely.
_CATEGORY_TERMS: Mapping[str, str] = {
    # Spanish
    "cinturon": "belts", "cinturones": "belts", "zapatos": "shoes", "botas": "boots",
    "camisa": "shirts", "camisas": "shirts", "pantalones": "pants", "vaqueros": "jeans",
    "vestido": "dresses", "calcetines": "socks", "sombrero": "hats", "guantes": "gloves",
    "chaqueta": "jackets", "anillo": "rings",
    "pendientes": "earrings", "mochila": "backpacks",
    "sueter": "sweaters", "jersey": "sweaters", "reloj": "watches", "relojes": "watches",
    "bolso": "handbags", "falda": "skirts", "sandalias": "sandals", "bufanda": "scarves",
    # French
    "ceinture": "belts", "ceintures": "belts", "chaussures": "shoes", "bottes": "boots",
    "chemise": "shirts", "pantalon": "pants", "chaussettes": "socks",
    "gants": "gloves", "collier": "necklaces",
    "portefeuille": "wallets",
    "sandales": "sandals", "echarpe": "scarves",
    # German
    "gurtel": "belts", "schuhe": "shoes", "stiefel": "boots", "hemd": "shirts",
    "kleid": "dresses", "socken": "socks",
    "handschuhe": "gloves", "jacke": "jackets", "halskette": "necklaces",
    "ohrringe": "earrings", "sonnenbrille": "sunglasses", "geldborse": "wallets",
    "rucksack": "backpacks", "pullover": "sweaters",
    "handtasche": "handbags", "sandalen": "sandals",
    # Hindi
    "बेल्ट": "belts", "जूते": "shoes", "शर्ट": "shirts", "पैंट": "pants",
    "जींस": "jeans", "मोजे": "socks", "टोपी": "hats", "दस्ताने": "gloves",
    "जैकेट": "jackets", "हार": "necklaces", "अंगूठी": "rings", "चश्मा": "sunglasses",
    "बटुआ": "wallets", "घड़ी": "watches", "स्कर्ट": "skirts",
    # Japanese
    "ベルト": "belts", "靴": "shoes", "ブーツ": "boots", "シャツ": "shirts",
    "ズボン": "pants", "ジーンズ": "jeans", "ドレス": "dresses", "靴下": "socks",
    "帽子": "hats", "手袋": "gloves", "ジャケット": "jackets", "ネックレス": "necklaces",
    "指輪": "rings", "イヤリング": "earrings", "サングラス": "sunglasses",
    "財布": "wallets", "リュック": "backpacks", "セーター": "sweaters",
    "腕時計": "watches", "スカート": "skirts", "サンダル": "sandals",
    # Chinese
    "腰带": "belts", "鞋": "shoes", "靴子": "boots", "衬衫": "shirts", "裤子": "pants",
    "牛仔裤": "jeans", "连衣裙": "dresses", "袜子": "socks", "手套": "gloves",
    "夹克": "jackets", "项链": "necklaces", "戒指": "rings", "耳环": "earrings",
    "太阳镜": "sunglasses", "钱包": "wallets", "背包": "backpacks", "毛衣": "sweaters",
    "手表": "watches", "手提包": "handbags", "裙子": "skirts", "凉鞋": "sandals",
    "围巾": "scarves",
}


def category_mention(message: str) -> tuple[str, str]:
    """(English catalog words, the customer's own words) for what they asked for.

    Retrieval needs the English, because that is what the catalog is written in.
    The customer should be shown the term they typed, because being told
    "starting from belts" when you wrote "cinturones" is the assistant talking
    to itself.
    """
    english = category_terms(message)
    if not english:
        return "", ""
    wanted = set(english.split())
    source: list[str] = []
    folded = _fold(message)
    for term, mapped in _CATEGORY_TERMS.items():
        if mapped not in wanted or mapped in {value for value in source}:
            continue
        if term.isascii():
            if not re.search(BOUNDARY.format(term=re.escape(term)), folded):
                continue
            # Echo the customer's own spelling, not the fold used to match it:
            # someone who wrote "Gürtel" should not be answered about "gurtel".
            written = next(
                (word for word in _WORD_RE.findall(message) if _fold(word) == term),
                term,
            )
        elif term in message:
            written = term
        else:
            continue
        if written not in source:
            source.append(written)
    return english, " ".join(source[:2])


def _fold(message: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", message.casefold())
        if not unicodedata.combining(character)
    )


def category_terms(message: str) -> str:
    """English catalog words for the shopping nouns a request mentions.

    Scans for known terms rather than parsing a sentence, because the grammar
    differs per language while the noun does not: Hindi and Japanese put it
    before the verb, Spanish and German after it, and a lexicon needs neither.

    Returns "" when nothing is recognised, which is the same thing an
    unparseable English opening returns, so the caller has one case to handle.
    """
    if not isinstance(message, str) or not message.strip():
        return ""
    folded = _fold(message)
    found: list[str] = []
    for term, english in _CATEGORY_TERMS.items():
        # Latin terms need a word boundary; CJK and Devanagari do not word-break.
        if term.isascii():
            if re.search(BOUNDARY.format(term=re.escape(term)), folded) and english not in found:
                found.append(english)
        elif term in message and english not in found:
            found.append(english)
    return " ".join(found[:2])


def supported() -> tuple[str, ...]:
    return tuple(sorted(_PHRASES))


def phrases(language: str) -> Mapping[str, str]:
    """The phrase table for a language, or English if it has none."""
    return _PHRASES.get(language, _PHRASES[DEFAULT])


__all__ = [
    "DEFAULT", "category_mention", "category_terms", "detect", "phrases",
    "supported",
]
