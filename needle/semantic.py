from __future__ import annotations

import difflib
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from needle.contracts import Candidate


class NoOpSemanticReranker:
    """Offline-safe integration boundary used until a semantic experiment passes its gate."""

    def rerank(self, candidates: Sequence[Candidate], query: str) -> list[Candidate]:
        del query
        return list(candidates)


# Conservative, hand-verified apparel term expansions. Every entry only *adds*
# canonical tokens; nothing is replaced or removed, so an expansion can widen
# lexical recall but can never silently change query meaning. This map is small on
# purpose: it is grown only with EXP-008 evidence, never by guessing.
_SYNONYM_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "sneaker": ("shoes",),
    "sneakers": ("shoes",),
    "trainers": ("shoes",),
    "kicks": ("shoes",),
    "tshirt": ("shirt",),
    "tshirts": ("shirt",),
    "tee": ("shirt",),
    "tees": ("shirt",),
    "hoody": ("hoodie",),
    "hoodies": ("hoodie",),
    "pjs": ("pajamas",),
    "sweatpants": ("joggers",),
    "trousers": ("pants",),
    "activewear": ("athletic",),
}

_PUNCTUATION_TO_SPACE = {
    ord(character): " " for character in "-_/\\.,;:!?\"'`()[]{}<>|@#$%^&*+=~"
}


def normalize_text(text: str) -> str:
    """Deterministic, offline text normalization.

    Applies NFKD decomposition, strips combining marks, folds case, maps
    punctuation to spaces, and collapses whitespace. It never drops a word, so
    negation and other meaning-carrying tokens survive unchanged.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    folded = without_marks.translate(_PUNCTUATION_TO_SPACE).casefold()
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

    Widens lexical recall through normalization and conservative *additive*
    synonym expansion. It never removes a token and never alters negation, so it
    cannot silently change query meaning. This is not a semantic model and is not
    wired into the response path; a retriever may call :meth:`expand_query` to
    build its match expression.
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
        """Return normalized query text with conservative synonym tokens appended.

        Original tokens come first, in order and de-duplicated; novel expansion
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
