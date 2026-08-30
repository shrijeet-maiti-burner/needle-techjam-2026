"""Controlled, deterministic perturbations for the EXP-010 robustness harness.

Two families:

* **surface** perturbations rewrite the customer's phrasing without touching the
  underlying constraint set. They are ``MEANING_PRESERVING`` by construction: a
  robust agent must still find the target after any of them.
* **semantic** primitives (:func:`negate_value`, :func:`swap_value`) change one
  constraint. They are ``MEANING_CHANGING``: the harness checks that the agent
  reflects the change rather than silently treating the message as equivalent.

Every function takes an explicit ``random.Random`` so a ``(text, seed)`` pair is
fully reproducible. Nothing here reads the clock, the network, or global random
state. A non-empty input never becomes empty, and every result reports whether it
actually changed the text (``changed``) so the harness can drop vacuous cases
instead of counting them as slice coverage.

This module has no ``needle`` imports on purpose: it is a test fixture and must
stay stable regardless of churn elsewhere.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum


class Meaning(str, Enum):
    PRESERVING = "meaning_preserving"
    CHANGING = "meaning_changing"


@dataclass(frozen=True, slots=True)
class Perturbed:
    """Outcome of one or more perturbations applied to a string."""

    text: str
    changed: bool
    meaning: Meaning
    kind: str
    detail: str = ""


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #

_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)  # alphabetic runs, length >= 2
_NUMBER_GUARD_RE = re.compile(r"\d[.,]\d")  # decimal / thousands separators to protect

_STOPWORDS = frozenset(
    """
    a an and any are as at be been but by can could do does for from have i if in
    is it its me my need no not of on or please should some that the their them
    then there these this to want was were will with would you your looking
    something anything
    """.split()
)

# Genuine synonyms for the clothing/shoe/jewelry domain in US retail register.
# Bidirectional. Hand-verified; a wrong entry would turn a "meaning-preserving"
# slice into a silent meaning change, so near-neighbours are deliberately absent:
# a cap is a kind of hat and a loafer is a kind of slip-on, but neither pair is
# interchangeable, and gloves/mittens and sandals/flip-flops are simply
# different products.
#
# The table has to intersect the vocabulary the released set actually uses or
# the slice tests nothing. `initial_message` opens every session with
# `coarse_category(...)`, and the public set draws those from ~180 distinct
# category words. The original ten-word table met three of them (`pants`,
# `sneakers`, `sunglasses`) and fired on 15 of 1000 messages, so its clean result
# was vacuous rather than reassuring. The additions below are chosen from the
# category words the set does use, and take that to 11 words met.
_SYNONYMS: dict[str, str] = {
    "sneakers": "trainers",
    "trainers": "sneakers",
    "sneaker": "trainer",
    "trainer": "sneaker",
    "trousers": "pants",
    "pants": "trousers",
    "sunglasses": "shades",
    "shades": "sunglasses",
    "eyeglasses": "glasses",
    "glasses": "eyeglasses",
    # US/UK register pairs, fully interchangeable
    "sweaters": "jumpers",
    "jumpers": "sweaters",
    "sweater": "jumper",
    "jumper": "sweater",
    "panties": "knickers",
    "knickers": "panties",
    "backpacks": "rucksacks",
    "rucksacks": "backpacks",
    "backpack": "rucksack",
    "rucksack": "backpack",
    "vests": "waistcoats",
    "waistcoats": "vests",
    "vest": "waistcoat",
    "waistcoat": "vest",
    # same-register pairs
    "handbags": "purses",
    "purses": "handbags",
    "handbag": "purse",
    "purse": "handbag",
    "wallets": "billfolds",
    "billfolds": "wallets",
    "wallet": "billfold",
    "billfold": "wallet",
    "watches": "wristwatches",
    "wristwatches": "watches",
    "underwear": "undergarments",
    "undergarments": "underwear",
}

_CONTRACTIONS: dict[str, str] = {
    "i am": "i'm",
    "you are": "you're",
    "it is": "it's",
    "that is": "that's",
    "i will": "i'll",
    "i would": "i'd",
    "i have": "i've",
    "do not": "don't",
    "does not": "doesn't",
    "cannot": "can't",
    "will not": "won't",
    "would not": "wouldn't",
}
_EXPANSIONS: dict[str, str] = {value: key for key, value in _CONTRACTIONS.items()}

# Fillers that cannot trip the state machine: none contains an override phrase
# ("actually", "instead", "ignore", "changed my mind") or a negation token
# ("no", "not", "without", "non", "avoid", "skip", "dislike", "nothing").
_FILLERS: tuple[str, ...] = (
    "um",
    "uh",
    "like",
    "basically",
    "honestly",
    "you know",
    "i guess",
    "i think",
    "sort of",
    "kind of",
    "to be honest",
    "if that makes sense",
)

_POLITENESS: tuple[str, ...] = (
    "could you help me find {}",
    "i'm looking for {}",
    "i'd like {}",
    "do you have {}",
    "i want something that is {}",
    "show me {}",
    "any recommendations for {}",
)
_LEADING_INTENT_RE = re.compile(
    r"^\s*(?:i\s+(?:need|want|am\s+looking\s+for|'?m\s+looking\s+for)"
    r"|looking\s+for|show\s+me|find\s+me)\s+",
    re.IGNORECASE,
)

_ACCENTABLE = {
    "a": "á",
    "e": "é",
    "i": "í",
    "o": "ó",
    "u": "ú",
    "A": "Á",
    "E": "É",
    "I": "Í",
    "O": "Ó",
    "U": "Ú",
}

_NEGATION_MARKERS = ("no", "not", "non", "without", "avoid")
_BUDGET_HINT_RE = re.compile(r"\$|\d|\b(?:budget|price|dollar|dollars|bucks|usd)\b", re.IGNORECASE)

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _int_to_words(value: int) -> str | None:
    """Words for a non-negative integer below 10000, else ``None``."""
    if not 0 <= value < 10_000:
        return None
    if value < 20:
        return _ONES[value]
    if value < 100:
        tens = _TENS[value // 10]
        return tens if value % 10 == 0 else f"{tens}-{_ONES[value % 10]}"
    if value < 1_000:
        head = f"{_ONES[value // 100]} hundred"
        rest = value % 100
        return head if rest == 0 else f"{head} {_int_to_words(rest)}"
    head = f"{_ONES[value // 1_000]} thousand"
    rest = value % 1_000
    return head if rest == 0 else f"{head} {_int_to_words(rest)}"


def _content_words(text: str) -> list[str]:
    return [
        match.group(0)
        for match in _WORD_RE.finditer(text)
        if match.group(0).lower() not in _STOPWORDS
    ]


def _match_original_case(replacement: str, original: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _replace_first_word(text: str, word: str, replacement: str) -> str:
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)

    def _sub(match: re.Match[str]) -> str:
        return _match_original_case(replacement, match.group(0))

    return pattern.sub(_sub, text, count=1)


def _unchanged(text: str, kind: str, meaning: Meaning, detail: str) -> Perturbed:
    return Perturbed(text=text, changed=False, meaning=meaning, kind=kind, detail=detail)


def _result(original: str, new: str, kind: str, meaning: Meaning, detail: str) -> Perturbed:
    if not original.strip():
        # Never fabricate content from an empty message.
        return _unchanged(original, kind, meaning, "empty input")
    if not new.strip():
        return _unchanged(original, kind, meaning, "perturbation would empty the text")
    return Perturbed(text=new, changed=new != original, meaning=meaning, kind=kind, detail=detail)


# --------------------------------------------------------------------------- #
# surface perturbations (all MEANING_PRESERVING)
# --------------------------------------------------------------------------- #

def casing(text: str, rng: random.Random) -> Perturbed:
    """Flip the case of individual letters at random."""
    flipped = "".join(
        character.swapcase() if character.isalpha() and rng.random() < 0.5 else character
        for character in text
    )
    if flipped == text and any(character.isalpha() for character in text):
        flipped = text.upper() if not text.isupper() else text.lower()
    return _result(text, flipped, "casing", Meaning.PRESERVING, "letter case flipped")


def whitespace(text: str, rng: random.Random) -> Perturbed:
    """Add, collapse, or pad whitespace without merging adjacent words."""
    mode = rng.choice(("expand", "collapse", "edges", "tabs"))
    if mode == "collapse":
        new = re.sub(r"\s+", " ", text).strip()
    elif mode == "edges":
        pad = " " * rng.randint(1, 3)
        new = f"{pad}{text}{pad}"
    elif mode == "tabs":
        new = re.sub(r" ", lambda _match: rng.choice((" ", "\t", "  ")), text)
    else:  # expand one internal run
        spans = [match.start() for match in re.finditer(r"(?<=\S) (?=\S)", text)]
        if not spans:
            return _unchanged(text, "whitespace", Meaning.PRESERVING, "no internal space")
        index = spans[rng.randrange(len(spans))]
        new = text[:index] + "   " + text[index + 1 :]
    return _result(text, new, "whitespace", Meaning.PRESERVING, f"{mode} whitespace")


def punctuation(text: str, rng: random.Random) -> Perturbed:
    """Add/remove trailing punctuation or swap a hyphen for a space."""
    mode = rng.choice(("trailing_add", "trailing_drop", "hyphen"))
    if mode == "trailing_add":
        new = text.rstrip() + rng.choice((".", "!", " ...", "?", ","))
    elif mode == "trailing_drop":
        new = text.rstrip(" .!?,;:")
    else:
        candidates = [
            match.start(1)
            for match in re.finditer(r"\w(-)\w", text)
            if not _NUMBER_GUARD_RE.search(text[max(0, match.start() - 1) : match.end() + 1])
        ]
        if not candidates:
            return _unchanged(text, "punctuation", Meaning.PRESERVING, "no safe hyphen")
        index = candidates[rng.randrange(len(candidates))]
        new = text[:index] + " " + text[index + 1 :]
    return _result(text, new, "punctuation", Meaning.PRESERVING, f"{mode}")


def accents(text: str, rng: random.Random) -> Perturbed:
    """Add or strip vowel diacritics."""
    stripped = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    if rng.random() < 0.5 and stripped != text:
        return _result(text, stripped, "accents", Meaning.PRESERVING, "diacritics stripped")
    vowel_positions = [index for index, char in enumerate(text) if char in _ACCENTABLE]
    if not vowel_positions:
        return _unchanged(text, "accents", Meaning.PRESERVING, "no accentable vowel")
    chosen = rng.sample(vowel_positions, k=min(2, len(vowel_positions)))
    characters = list(text)
    for index in chosen:
        characters[index] = _ACCENTABLE[characters[index]]
    return _result(text, "".join(characters), "accents", Meaning.PRESERVING, "diacritics added")


def synonym(text: str, rng: random.Random) -> Perturbed:
    """Swap one word for a domain synonym (bidirectional, true equivalents)."""
    hits = [
        match.group(0)
        for match in re.finditer(r"[A-Za-z]+", text)
        if match.group(0).lower() in _SYNONYMS
    ]
    if not hits:
        return _unchanged(text, "synonym", Meaning.PRESERVING, "no known synonym")
    original = hits[rng.randrange(len(hits))]
    replacement = _SYNONYMS[original.lower()]
    new = _replace_first_word(text, original, replacement)
    return _result(text, new, "synonym", Meaning.PRESERVING, f"{original!r} -> {replacement!r}")


def word_order(text: str, rng: random.Random) -> Perturbed:
    """Shuffle comma/'and'/semicolon-separated phrases; within-phrase order is kept."""
    phrases = [phrase.strip() for phrase in re.split(r"\s*(?:,|;|\band\b)\s*", text) if phrase.strip()]
    if len(phrases) < 2:
        return _unchanged(text, "word_order", Meaning.PRESERVING, "single phrase")
    shuffled = phrases[:]
    for _ in range(8):
        rng.shuffle(shuffled)
        if shuffled != phrases:
            break
    else:
        shuffled = phrases[1:] + phrases[:1]
    return _result(text, ", ".join(shuffled), "word_order", Meaning.PRESERVING, "phrase order shuffled")


def filler(text: str, rng: random.Random) -> Perturbed:
    """Insert one semantically-null filler at a clause boundary."""
    if not text.strip():
        return _unchanged(text, "filler", Meaning.PRESERVING, "empty input")
    token = _FILLERS[rng.randrange(len(_FILLERS))]
    position = rng.choice(("start", "after_first", "end"))
    words = text.split()
    if position == "start":
        new = f"{token}, {text.lstrip()}"
    elif position == "end" or len(words) < 2:
        new = f"{text.rstrip()}, {token}"
    else:
        new = f"{words[0]} {token} " + " ".join(words[1:])
    return _result(text, new, "filler", Meaning.PRESERVING, f"{token!r} at {position}")


def politeness(text: str, rng: random.Random) -> Perturbed:
    """Rewrap the request in a different politeness frame."""
    if not text.strip():
        return _unchanged(text, "politeness", Meaning.PRESERVING, "empty input")
    core = _LEADING_INTENT_RE.sub("", text).strip()
    core = core[:1].lower() + core[1:] if core else text.strip()
    template = _POLITENESS[rng.randrange(len(_POLITENESS))]
    new = template.format(core)
    return _result(text, new, "politeness", Meaning.PRESERVING, "reframed request")


def contraction(text: str, rng: random.Random) -> Perturbed:
    """Contract or expand one auxiliary phrase; negation is preserved either way."""
    pairs = list(_CONTRACTIONS.items()) + list(_EXPANSIONS.items())
    rng.shuffle(pairs)
    for source, target in pairs:
        pattern = re.compile(rf"\b{re.escape(source)}\b", re.IGNORECASE)
        if pattern.search(text):
            new = pattern.sub(lambda match: _match_original_case(target, match.group(0)), text, count=1)
            return _result(text, new, "contraction", Meaning.PRESERVING, f"{source!r} -> {target!r}")
    return _unchanged(text, "contraction", Meaning.PRESERVING, "nothing contractable")


def number_format(text: str, rng: random.Random) -> Perturbed:
    """Re-express a currency amount or a budget comparator."""
    comparator = re.search(
        r"\b(under|below|less than|at most|up to)\b\s*\$?\s*\d",
        text,
        re.IGNORECASE,
    )
    if comparator:
        # None of these carry a token the belief state machine reads as negation
        # ("no more than" would, so it is deliberately excluded).
        phrase = rng.choice(("under", "below", "less than", "at most", "up to"))
        new = text[: comparator.start(1)] + phrase + text[comparator.end(1) :]
        return _result(text, new, "number_format", Meaning.PRESERVING, "comparator reworded")

    money = re.search(r"\$\s?(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s?(?:dollars|bucks|usd)\b", text, re.IGNORECASE)
    if not money:
        return _unchanged(text, "number_format", Meaning.PRESERVING, "no currency amount")
    if re.match(r"[.,]\d", text[money.end() : money.end() + 2]):
        # part of a larger number such as "$1,000" or "$29.999"; leave it alone
        return _unchanged(text, "number_format", Meaning.PRESERVING, "amount is part of a longer number")
    amount = money.group(1) or money.group(2)
    forms = [f"{amount} dollars", f"USD {amount}", f"{amount} bucks", f"${amount}"]
    if "." not in amount:
        words = _int_to_words(int(amount))
        if words:
            forms.append(f"{words} dollars")
    forms = [form for form in forms if form.lower() != money.group(0).lower().strip()]
    if not forms:
        return _unchanged(text, "number_format", Meaning.PRESERVING, "no alternate form")
    replacement = forms[rng.randrange(len(forms))]
    new = text[: money.start()] + replacement + text[money.end() :]
    return _result(text, new, "number_format", Meaning.PRESERVING, f"amount -> {replacement!r}")


def typo(
    text: str,
    rng: random.Random,
    *,
    avoid: Iterable[str] | None = None,
) -> Perturbed:
    """Introduce a single-character error in one content word (length >= 4).

    If ``avoid`` is given, an edit whose result is a *different* real word in
    that set is rejected and another edit is tried, so a "typo" cannot silently
    become a different valid term. Without it, best effort only.
    """
    avoid_set = {word.lower() for word in avoid} if avoid is not None else set()
    words = [word for word in _content_words(text) if len(word) >= 4]
    if not words:
        return _unchanged(text, "typo", Meaning.PRESERVING, "no word long enough")

    order = words[:]
    rng.shuffle(order)
    edits = ["transpose", "delete", "substitute", "insert"]
    for word in order:
        for _ in range(6):
            edit = edits[rng.randrange(len(edits))]
            characters = list(word)
            index = rng.randrange(1, len(characters) - 1) if len(characters) > 2 else 0
            if edit == "transpose" and index + 1 < len(characters):
                characters[index], characters[index + 1] = characters[index + 1], characters[index]
            elif edit == "delete" and len(characters) > 4:
                del characters[index]
            elif edit == "substitute":
                letter = rng.choice("abcdefghijklmnopqrstuvwxyz")
                characters[index] = letter if characters[index].islower() else letter.upper()
            else:  # insert (double a character)
                characters.insert(index, characters[index])
            typoed = "".join(characters)
            if typoed == word:
                continue
            if typoed.lower() in avoid_set and typoed.lower() != word.lower():
                continue
            new = _replace_first_word(text, word, typoed)
            return _result(text, new, "typo", Meaning.PRESERVING, f"{word!r} -> {typoed!r} ({edit})")
    return _unchanged(text, "typo", Meaning.PRESERVING, "no safe single-edit typo found")


SURFACE: dict[str, object] = {
    "casing": casing,
    "whitespace": whitespace,
    "punctuation": punctuation,
    "accents": accents,
    "synonym": synonym,
    "word_order": word_order,
    "filler": filler,
    "politeness": politeness,
    "contraction": contraction,
    "number_format": number_format,
    "typo": typo,
}
SURFACE_KINDS: tuple[str, ...] = tuple(SURFACE)


# --------------------------------------------------------------------------- #
# semantic primitives (MEANING_CHANGING)
# --------------------------------------------------------------------------- #

def _split_prefix(disclosure: str) -> tuple[str, str]:
    """Separate a leading ``"attribute: "`` label from its value."""
    head, separator, tail = disclosure.partition(":")
    if separator and tail.strip() and len(head.split()) <= 2:
        return head + ": ", tail.strip()
    return "", disclosure.strip()


def negate_value(disclosure: str, rng: random.Random) -> Perturbed:
    """Toggle negation on one disclosed value.

    ``"cotton"`` -> ``"not cotton"``; an already-negated value is un-negated, so
    the operation is its own inverse. Budget/price phrases are refused because a
    negated budget is not a constraint the simulator ever produces.
    """
    prefix, value = _split_prefix(disclosure)
    if not value:
        return _unchanged(disclosure, "negate_value", Meaning.CHANGING, "empty value")
    if _BUDGET_HINT_RE.search(value):
        return _unchanged(disclosure, "negate_value", Meaning.CHANGING, "budget not negatable")

    lowered = value.lower()
    first = lowered.split(" ", 1)[0].rstrip("-")
    if first in _NEGATION_MARKERS or lowered.startswith("non-"):
        without = re.sub(
            r"^(?:no|not|without|avoid)\s+|^non-?\s*",
            "",
            value,
            count=1,
            flags=re.IGNORECASE,
        )
        return _result(disclosure, prefix + without, "negate_value", Meaning.CHANGING, "negation removed")

    marker = rng.choice(("not ", "no ", "non-")) if " " not in value else rng.choice(("not ", "no "))
    return _result(disclosure, prefix + marker + value, "negate_value", Meaning.CHANGING, f"prefixed {marker!r}")


def swap_value(
    disclosure: str,
    rng: random.Random,
    *,
    alternatives: Sequence[str],
) -> Perturbed:
    """Replace the disclosed value with a different in-bucket value.

    ``alternatives`` is the caller's same-attribute vocabulary (for example the
    material list). A value equal to the current one, case-insensitively, is
    never chosen; if nothing else is available the disclosure is unchanged.
    """
    prefix, value = _split_prefix(disclosure)
    current = value.lower().strip()
    pool = sorted({option.strip() for option in alternatives if option.strip().lower() != current and option.strip()})
    if not current or not pool:
        return _unchanged(disclosure, "swap_value", Meaning.CHANGING, "no alternative value")
    replacement = pool[rng.randrange(len(pool))]
    return _result(disclosure, prefix + replacement, "swap_value", Meaning.CHANGING, f"{value!r} -> {replacement!r}")


SEMANTIC: dict[str, object] = {
    "negate_value": negate_value,
    "swap_value": swap_value,
}


# --------------------------------------------------------------------------- #
# dispatch and composition
# --------------------------------------------------------------------------- #

_DISPATCH: dict[str, object] = {**SURFACE, **SEMANTIC}
ALL_KINDS: tuple[str, ...] = tuple(_DISPATCH)


def apply(kind: str, text: str, rng: random.Random, **options: object) -> Perturbed:
    """Apply one named perturbation."""
    try:
        function = _DISPATCH[kind]
    except KeyError:
        raise ValueError(f"unknown perturbation kind: {kind!r}") from None
    return function(text, rng, **options)  # type: ignore[operator]


def compose(
    text: str,
    kinds: Sequence[str],
    rng: random.Random,
    *,
    options: Mapping[str, Mapping[str, object]] | None = None,
) -> Perturbed:
    """Apply perturbations in order, threading the text through each.

    ``changed`` is true if *any* stage changed the text. ``meaning`` is
    ``CHANGING`` if any stage was a semantic primitive, otherwise
    ``PRESERVING``.
    """
    per_kind = options or {}
    current = text
    changed_any = False
    meaning = Meaning.PRESERVING
    applied: list[str] = []
    details: list[str] = []
    for kind in kinds:
        result = apply(kind, current, rng, **dict(per_kind.get(kind, {})))
        current = result.text
        changed_any = changed_any or result.changed
        if result.meaning is Meaning.CHANGING:
            meaning = Meaning.CHANGING
        applied.append(kind)
        if result.detail:
            details.append(f"{kind}: {result.detail}")
    return Perturbed(
        text=current,
        changed=changed_any,
        meaning=meaning,
        kind="+".join(applied),
        detail="; ".join(details),
    )
