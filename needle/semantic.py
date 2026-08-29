from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

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
