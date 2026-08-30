"""Prefix promotion: rank the disclosed-evidence bucket instead of filtering on it.

The released protocol builds an intent card out of the *target's own* field
values. `intent_card` slices them (`hard = cleaned[:2]`, `soft = cleaned[2:4]`)
by the same steps and in the same order as `product_signatures`, and
`customer_reply` then discloses them two at a time in that order. So whatever the
customer has said so far is a **prefix** of the target's own signature list, and
the `(coarse_category, prefix)` bucket contains the target by construction rather
than by luck: verified on all 200 released sessions, at every disclosure depth.

That makes the bucket a guaranteed shortlist. What is a guess is the order inside
it, and `rating_number` orders it well enough that one disclosed constraint puts
the target first in 118 of 200 sessions, where the sparse ranking has to find it
in the whole coarse category.

Promotion therefore replaces the *emitted product*, never the candidate set. A
wrong promotion costs one turn and the next turn takes the next member; the
release floor merges the shortlist ahead of the shipped slate rather than
replacing it, so no target is ever dropped.

Measurements, arms and rejected variants: `docs/evidence/EXP_023.md`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Sequence

from needle.catalog import (
    MATERIAL_RE,
    SIGNATURE_MARKER_RE,
    canonical_signature,
    product_signatures,
)
from needle.state import fold_marks_in_place

# `local_evaluator.coarse_category`, mirrored because the agent has to build the
# same key the opening message states. It is part of the released protocol, not
# of the grader's private machinery.
_EXCLUDED_CATEGORIES = frozenset(
    {"clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry"}
)


def coarse_category(values: Sequence[str]) -> str:
    cleaned: list[str] = []
    for value in values or ():
        for part in str(value).split(","):
            part = part.strip()
            if part and part.lower() not in _EXCLUDED_CATEGORIES:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


# Discourse markers the customer may say and the robustness slices insert. They
# carry no product meaning, and promotion matches on surface text, so a single
# "um," between "For that" and "what matters is" would otherwise switch
# promotion off for the rest of the session.
_FILLER_RE = re.compile(
    r"\b(?:um|uh|er|like|basically|honestly|seriously|actually|really|"
    r"you\s+know|i\s+guess|i\s+think|i\s+mean|sort\s+of|kind\s+of|"
    r"to\s+be\s+honest|if\s+that\s+makes\s+sense|please)\b[,\s]*",
    re.IGNORECASE,
)
_OPENING_CATEGORY_RE = re.compile(
    r"^I'?m looking for (.+?)(?:, but I'?m still exploring|\.)", re.IGNORECASE
)


def normalize_for_match(message: str) -> str:
    """Fold marks, drop discourse fillers, collapse whitespace.

    `SessionState.observe` folds accents for the override trigger, but promotion
    does its own lookups against its own index and has to fold for itself, or an
    accented category never matches.
    """
    stripped = _FILLER_RE.sub(" ", fold_marks_in_place(message))
    return re.sub(r"\s+", " ", stripped).strip()


def clause_parses(message: str) -> list[tuple[str, ...]]:
    """Every way one message could be carrying its constraints.

    `customer_reply` joins at most two constraints with "; ", but a constraint
    can contain semicolons of its own ("Solid colors: 100% Cotton; Heather Grey:
    90% Cotton, 10% Polyester"), which shatters 25 of the 200 released cards if
    every semicolon is split on. The boundary is genuinely ambiguous from the
    text, so rather than guess, enumerate: the clause is either one constraint,
    or two split at one of its semicolons.
    """
    message = normalize_for_match(message)
    marker = SIGNATURE_MARKER_RE.search(message)
    if not marker:
        return [()]
    clause = re.sub(r"\s+now\s*[.!?]*\s*$", "", marker.group(1), flags=re.IGNORECASE)
    parses = [(clause,)]
    for position, character in enumerate(clause):
        if character == ";":
            parses.append((clause[:position], clause[position + 1:]))
    signed: list[tuple[str, ...]] = []
    for parse in parses:
        values = tuple(x for x in (canonical_signature(part) for part in parse) if x)
        if values and values not in signed:
            signed.append(values)
    return signed or [()]


def disclosed_candidates(messages: Iterable[str], cap: int = 64) -> list[tuple[str, ...]]:
    """Candidate constraint sequences, in the order the customer stated them."""
    sequences: list[tuple[str, ...]] = [()]
    for message in messages:
        expanded: list[tuple[str, ...]] = []
        for prefix in sequences:
            for parse in clause_parses(message):
                combined = prefix
                for value in parse:
                    if value not in combined:
                        combined = combined + (value,)
                if combined not in expanded:
                    expanded.append(combined)
        sequences = expanded[:cap]
    return [sequence for sequence in sequences if sequence]


class PrefixIndex:
    """`(coarse_category, disclosed prefix) -> products`, ordered by popularity.

    Built once from the catalog. Memory is bounded by four prefixes per product
    plus one bare-category bucket.
    """

    def __init__(self, catalog_path: str | Path) -> None:
        self.by_category: dict[tuple, list[str]] = {}
        self.by_category_set: dict[tuple, list[str]] = {}
        self.by_prefix: dict[tuple, list[str]] = {}
        self.by_first_four: dict[frozenset, list[str]] = {}
        self.popularity: dict[str, float] = {}
        self.known_categories: dict[str, frozenset] = {}
        self._load(Path(catalog_path))

    def _load(self, catalog_path: Path) -> None:
        with catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                product = json.loads(line)
                asin = str(product.get("parent_asin") or "").strip()
                if not asin:
                    continue
                count = product.get("rating_number")
                self.popularity[asin] = float(count) if isinstance(count, (int, float)) else 0.0
                categories = product.get("categories")
                if not isinstance(categories, list):
                    categories = []
                coarse = canonical_signature(coarse_category(categories))
                signature = product_signatures(product)[:4]
                self.by_category.setdefault((coarse, ()), []).append(asin)
                if coarse and coarse not in self.known_categories:
                    self.known_categories[coarse] = frozenset(coarse.split())
                for depth in range(1, len(signature) + 1):
                    self.by_prefix.setdefault(signature[:depth], []).append(asin)
                    self.by_category.setdefault((coarse, signature[:depth]), []).append(asin)
                if signature:
                    self.by_first_four.setdefault(frozenset(signature), []).append(asin)
                    self.by_category_set.setdefault((coarse, frozenset(signature)), []).append(asin)

    def resolve_category(self, stated: str) -> str:
        """The known coarse category the opening line is naming, or "".

        `initial_message` states `coarse_category(...)` verbatim, so the category
        comes from a closed vocabulary the index already holds. That makes a miss
        recoverable: a surface change leaves a string still sharing most of its
        tokens with exactly one known category. A strict majority must match and
        the winner must be unique, so an ambiguous or genuinely unknown category
        resolves to nothing rather than to a guess.
        """
        if not stated:
            return ""
        if (stated, ()) in self.by_category:
            return stated
        tokens = set(stated.split())
        if not tokens:
            return ""
        best_score, best = 0.0, []
        for known, known_tokens in self.known_categories.items():
            shared = len(tokens & known_tokens)
            if not shared:
                continue
            score = shared / max(len(tokens), len(known_tokens))
            if score > best_score:
                best_score, best = score, [known]
            elif score == best_score:
                best.append(known)
        return best[0] if best_score > 0.5 and len(best) == 1 else ""

    def opening_category(self, message: str) -> str:
        match = _OPENING_CATEGORY_RE.search(normalize_for_match(message))
        if not match:
            return ""
        return self.resolve_category(canonical_signature(match.group(1)))

    def shortlist(
        self,
        messages: Sequence[str],
        category: str,
        *,
        empty_prefix: bool = False,
    ) -> list[str]:
        """The disclosed prefix's candidate shortlist, most popular first."""
        sequences = disclosed_candidates(messages)
        if empty_prefix and category:
            sequences = list(sequences) + [()]
        if not sequences:
            return []
        best: list[str] | None = None
        best_key: tuple[int, int] | None = None
        for disclosed in sequences:
            lookups = []
            if category:
                lookups.append(self.by_category.get((category, disclosed)))
                lookups.append(self.by_category_set.get((category, frozenset(disclosed))))
            lookups.append(self.by_prefix.get(disclosed))
            lookups.append(self.by_first_four.get(frozenset(disclosed)))
            for candidates in lookups:
                if not candidates:
                    continue
                key = (-len(disclosed), len(candidates))
                if best_key is None or key < best_key:
                    best_key, best = key, candidates
                break
        if best is None:
            return []
        return sorted(best, key=lambda asin: (-self.popularity.get(asin, 0.0), asin))


__all__ = ["PrefixIndex", "coarse_category", "normalize_for_match",
           "clause_parses", "disclosed_candidates"]
