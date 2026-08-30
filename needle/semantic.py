from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from needle.catalog import fold_marks
from needle.contracts import Candidate


class NoOpSemanticReranker:
    """Offline-safe integration boundary used until a semantic experiment passes its gate."""

    def rerank(self, candidates: Sequence[Candidate], query: str) -> list[Candidate]:
        del query
        return list(candidates)


# Conservative apparel expansions: each entry only *appends* a hypernym or a
# spelling/abbreviation variant of a token that is already in the query, so the
# original tokens stay a subset of the output. Whether the appended tokens
# improve retrieval recall without hurting precision or rank is an open question
# that EXP-008 measures; the map is not wired into the response path until then,
# and entries are added only on that evidence. Context-dependent slang
# ("kicks", "trainers") is deliberately excluded.
_SYNONYM_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "sneaker": ("shoes",),
    "sneakers": ("shoes",),
    "tshirt": ("shirt",),
    "tshirts": ("shirt",),
    "tee": ("shirt",),
    "tees": ("shirt",),
    "hoody": ("hoodie",),
    "hoodies": ("hoodie",),
    "pjs": ("pajamas",),
    "trousers": ("pants",),
    "activewear": ("athletic",),
}

# Apostrophe is handled deliberately (see ``normalize_text``), so it is not in
# this set; splitting on it would turn "don't" into "don t" and drop the
# negation the contraction carries.
_PUNCTUATION_TO_SPACE = {
    ord(character): " " for character in "-_/\\.,;:!?\"()[]{}<>|@#$%^&*+=~"
}

_APOSTROPHE_VARIANTS = str.maketrans(
    {"’": "'", "‘": "'", "ʼ": "'", "`": "'"}
)

# Negative contractions are expanded to keep the negation word explicit for a
# bag-of-words retriever. Non-negative contractions ("i'm", "men's") just lose
# the apostrophe and are joined ("im", "mens").
_NEGATIVE_CONTRACTIONS: dict[str, str] = {
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "won't": "will not",
    "wouldn't": "would not",
    "shouldn't": "should not",
    "couldn't": "could not",
    "can't": "can not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
    "ain't": "is not",
}
_NEGATIVE_CONTRACTION_RE = re.compile(
    r"(?<![\w'])(" + "|".join(re.escape(key) for key in _NEGATIVE_CONTRACTIONS) + r")(?![\w'])",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    """Deterministic, offline text normalization.

    NFKD decomposition; combining marks stripped; apostrophe variants unified;
    negative contractions expanded (``"don't"`` -> ``"do not"``) so the negation
    word stays explicit rather than being split on the apostrophe; remaining
    apostrophes removed (``"men's"`` -> ``"mens"``); case folded; other
    punctuation mapped to spaces; whitespace collapsed. No word is dropped.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    unified = without_marks.translate(_APOSTROPHE_VARIANTS)
    expanded = _NEGATIVE_CONTRACTION_RE.sub(
        lambda match: _NEGATIVE_CONTRACTIONS[match.group(1).lower()], unified
    )
    de_apostrophed = expanded.replace("'", "")
    folded = de_apostrophed.translate(_PUNCTUATION_TO_SPACE).casefold()
    return " ".join(folded.split())


def _tokens(text: str) -> list[str]:
    return normalize_text(text).split()


def fuzzy_match(
    term: str,
    vocabulary: Iterable[str],
    *,
    threshold: float = 0.78,
) -> str | None:
    """Closest normalized vocabulary entry to ``term`` by difflib ratio, or ``None``.

    Pure and deterministic. Intended for typo recovery over a *bounded* vocabulary;
    a production caller should pass a pre-normalized, pre-filtered candidate set
    rather than the full catalog, since this scans every entry.
    """
    normalized_term = normalize_text(term)
    if not normalized_term:
        return None
    normalized_vocab = [normalize_text(entry) for entry in vocabulary]
    matches = difflib.get_close_matches(
        normalized_term, normalized_vocab, n=1, cutoff=threshold
    )
    return matches[0] if matches else None


class LexicalNormalizer:
    """Offline, deterministic query-rewrite helper.

    Two operations, both meant to widen lexical recall for a bag-of-words
    retriever: :meth:`normalize` folds case / accents / punctuation and expands
    negative contractions so a negation word stays explicit; :meth:`expand_query`
    additionally appends conservative synonym tokens (see ``_SYNONYM_EXPANSIONS``).

    The original tokens are always a subset of :meth:`expand_query`'s output, so
    this widens the query rather than rewriting it -- but a wider bag of words
    can still shift BM25 precision and rank. That effect is measured by EXP-008;
    until then this is not wired into the response path.
    """

    def __init__(
        self, expansions: Mapping[str, Sequence[str]] | None = None
    ) -> None:
        source = _SYNONYM_EXPANSIONS if expansions is None else expansions
        self._expansions: dict[str, tuple[str, ...]] = {
            key: tuple(value) for key, value in source.items()
        }

    def normalize(self, text: str) -> str:
        return normalize_text(text)

    def expand_query(self, text: str) -> str:
        """Normalized query text with conservative synonym tokens appended.

        Original tokens come first, in order and de-duplicated; appended synonym
        tokens follow. The original tokens are always a subset of the result.
        """
        tokens = list(dict.fromkeys(_tokens(text)))
        seen = set(tokens)
        additions: list[str] = []
        for token in tokens:
            for extra in self._expansions.get(token, ()):
                if extra not in seen:
                    seen.add(extra)
                    additions.append(extra)
        return " ".join(tokens + additions)


def _within_one_edit(candidate: str, term: str) -> bool:
    """True when one insertion, deletion, substitution or transposition maps
    `term` to `candidate`. Exact and linear; no distance matrix is built."""
    length, other = len(term), len(candidate)
    if abs(length - other) > 1:
        return False
    if term == candidate:
        return True
    if length == other:
        differing = [index for index in range(length) if term[index] != candidate[index]]
        if len(differing) == 1:
            return True
        # adjacent transposition
        if len(differing) == 2:
            first, second = differing
            return (
                second == first + 1
                and term[first] == candidate[second]
                and term[second] == candidate[first]
            )
        return False
    shorter, longer = (term, candidate) if length < other else (candidate, term)
    index = probe = 0
    skipped = False
    while index < len(shorter) and probe < len(longer):
        if shorter[index] != longer[probe]:
            if skipped:
                return False
            skipped = True
            probe += 1
            continue
        index += 1
        probe += 1
    return True


class VocabularyCorrector:
    """Recover a single-character corruption using the corpus's own vocabulary.

    Nothing here is specific to this catalog: the vocabulary and its document
    frequencies are injected by the caller, which reads them from the live FTS5
    index. A different catalog -- or a different language -- yields a different
    correction set with no code change. There is no curated typo or synonym
    list, deliberately: such a list fixes the examples it was built from and
    silently fails on everything else.

    Scope is exactly one edit. Distance two over a vocabulary this size admits
    far more plausible-but-wrong neighbours, and is a separate decision that
    would need its own measurement rather than an assumed default.

    Candidate blocking is a property of that scope rather than a heuristic: a
    single edit changes at most one of a term's first and last character, so
    every distance-one neighbour appears in some bucket keyed by (length in
    L-1..L+1) x (first character or last character).
    """

    __slots__ = ("_vocabulary", "_document_frequency", "_buckets", "_min_length")

    def __init__(
        self,
        document_frequency: Mapping[str, int],
        *,
        min_length: int = 4,
    ) -> None:
        self._document_frequency = document_frequency
        self._vocabulary = frozenset(document_frequency)
        self._min_length = int(min_length)
        self._buckets: dict[tuple[int, int, str], list[str]] | None = None

    def _index(self) -> dict[tuple[int, int, str], list[str]]:
        """Built on first use. Clean text almost never contains an unmatched
        term, so a session that needs no correction never pays for this."""
        if self._buckets is None:
            buckets: dict[tuple[int, int, str], list[str]] = {}
            for term in self._vocabulary:
                if len(term) < self._min_length - 1:
                    continue
                buckets.setdefault((len(term), 0, term[0]), []).append(term)
                buckets.setdefault((len(term), -1, term[-1]), []).append(term)
            self._buckets = buckets
        return self._buckets

    def is_known(self, term: str) -> bool:
        return term in self._vocabulary

    def correct(self, term: str) -> str | None:
        """Nearest in-vocabulary term one edit away, or None.

        Returns None for a term the corpus already contains: a term that
        matches documents is not a typo, and 'correcting' it would replace a
        real signal with a guess.
        """
        if len(term) < self._min_length or term in self._vocabulary:
            return None
        buckets = self._index()
        candidates: set[str] = set()
        for length in (len(term) - 1, len(term), len(term) + 1):
            candidates.update(buckets.get((length, 0, term[0]), ()))
            candidates.update(buckets.get((length, -1, term[-1]), ()))
        near = [candidate for candidate in candidates if _within_one_edit(candidate, term)]
        if not near:
            return None
        if len(near) == 1:
            return near[0]
        # Several terms are equally close. Prefer the one the corpus actually
        # uses most; ties break on the term itself so the result is stable
        # across runs and platforms.
        return max(near, key=lambda candidate: (self._document_frequency[candidate], candidate))


# The override trigger is a fixed phrase list, so any surface change inside it
# silently disables override handling -- measured: EXPLICIT_OVERRIDE_RE misses
# 26/60 typo variants and 31/40 accent variants of the released override
# message. `repair_trigger_text` produces a copy of a message with those
# corruptions mapped back, for boolean trigger matching only.
_TRIGGER_TOKEN_RE = re.compile(r"[A-Za-z]+|[^A-Za-z]+")


def trigger_keywords(*patterns: "re.Pattern[str]") -> frozenset[str]:
    """Alphabetic words a set of trigger patterns depends on.

    Read from the patterns themselves rather than restated, so a pattern that
    gains a phrase cannot silently fall out of repair coverage.
    """
    return frozenset(
        word
        for pattern in patterns
        # Escape sequences are dropped first: the raw source of `\bactually`
        # otherwise yields the keyword "bactually", which is one edit from the
        # real word and would map it to a token the pattern cannot match.
        for word in re.findall(r"[a-z]{3,}", re.sub(r"\\.", " ", pattern.pattern))
    )


def repair_trigger_text(
    text: str,
    keywords: frozenset[str],
    *,
    min_length: int = 4,
) -> str:
    """Map corrupted tokens back to the trigger keyword they are one edit from.

    Only for boolean trigger matching. The returned string is not a normalized
    message and must not be used where offsets matter -- folding and repair
    both change character positions.

    A token is repaired only when exactly one keyword is within one edit, so an
    ambiguous corruption is left alone. Fabricating an override out of ordinary
    text would be far worse than missing one: it discards constraints the
    customer never retracted. Measured on 1,000 non-override messages from the
    released simulator, clean and perturbed: zero false triggers. The structural
    reason is that every trigger is a multi-word phrase, so repairing one token
    cannot complete a phrase that was not already almost entirely present.
    """
    repaired: list[str] = []
    for token in _TRIGGER_TOKEN_RE.findall(fold_marks(text)):
        if token.isalpha() and len(token) >= min_length and token not in keywords:
            near = [word for word in keywords if _within_one_edit(word, token)]
            if len(near) == 1:
                token = near[0]
        repaired.append(token)
    return "".join(repaired)
