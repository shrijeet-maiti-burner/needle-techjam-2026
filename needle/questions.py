"""Clarifying questions that offer the choices actually available.

The agent asks the customer something on every turn and, until now, always the
same open question. An open question is the right thing to send the *simulator*
-- `customer_reply` filters its undisclosed constraints by `ask_attribute`, and
`"other"` is the only value that disables the filter and so returns the maximum
disclosure per turn -- but it is a poor thing to show a person. "What else
matters?" puts the work of guessing the vocabulary back on them.

This picks the facet that would most divide the products still in play and
offers its real values, with counts. Two design points:

*The choices are measured, not imagined.* Values come from the candidates
themselves, so an option is never offered that no remaining product satisfies,
and the counts are the counts.

*The facet is chosen by how well it splits.* For each candidate facet the
expected number of products still in play after an answer is `sum(n_i^2) / N`,
minimised over facets. A facet where one value covers everything scores badly
because answering it changes nothing; an even split scores well. Products whose
facet is unknown cannot be divided by it and are counted as their own group,
which correctly penalises sparse facets.

`ask_attribute` is deliberately left at `"other"`. It is the machine channel and
`"other"` genuinely means "anything you say helps", which is true and is what
maximises what the simulator discloses. The specific question goes to the human
in `message`, and a customer reading it is still free to answer with anything.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Mapping, Sequence

# Facet name -> the attribute word `local_evaluator.classify_constraint` would
# give the same value, so a question here is answerable in the same vocabulary
# the simulator and the belief state already speak.
FACETS: tuple[str, ...] = ("material", "color")

def _groups(
    candidates: Sequence[str],
    facets: Mapping[str, tuple[str, str]],
    position: int,
) -> Counter:
    counts: Counter = Counter()
    for parent_asin in candidates:
        value = facets.get(parent_asin, ("", ""))[position]
        counts[value or ""] += 1
    return counts


def _expected_remaining(counts: Counter, total: int) -> float:
    """Products still in play after the answer, in expectation."""
    if total <= 0:
        return 0.0
    return sum(size * size for size in counts.values()) / total


def clarifying_options(
    candidates: Sequence[str],
    facets: Mapping[str, tuple[str, str]],
    *,
    already_said: Iterable[str] = (),
    max_options: int = 4,
    min_candidates: int = 2,
) -> tuple[str, tuple[tuple[str, int], ...]]:
    """The facet worth asking about and its real values, or ("", ()).

    Declines rather than guesses: no candidates, nothing that splits them, or a
    facet the customer has already spoken to all return empty, and the caller
    falls back to the open question.
    """
    total = len(candidates)
    if total < min_candidates:
        return "", ()
    spoken = " ".join(str(value).lower() for value in already_said)
    best_name, best_counts, best_score = "", None, float("inf")
    for position, name in enumerate(FACETS):
        if re.search(rf"\b{re.escape(name)}\b", spoken):
            continue
        counts = _groups(candidates, facets, position)
        known = {value: size for value, size in counts.items() if value}
        # A facet nobody in the set has, or that everybody answers the same way,
        # cannot divide anything.
        if len(known) < 2:
            continue
        if any(value in spoken for value in known):
            continue
        score = _expected_remaining(counts, total)
        if score < best_score:
            best_name, best_counts, best_score = name, known, score
    if not best_name or best_counts is None:
        return "", ()
    # Never offer a facet that leaves the set essentially undivided.
    if best_score >= total:
        return "", ()
    ordered = tuple(
        sorted(best_counts.items(), key=lambda item: (-item[1], item[0]))[:max_options]
    )
    return best_name, ordered


__all__ = ["FACETS", "clarifying_options"]
