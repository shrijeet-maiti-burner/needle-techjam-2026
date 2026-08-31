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
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence

# Facet name -> the attribute word `local_evaluator.classify_constraint` would
# give the same value, so a question here is answerable in the same vocabulary
# the simulator and the belief state already speak.
# Ordered only for stable tie-breaking; the board ranks them by measured
# expected reduction, so a new facet has to earn its place on the numbers
# rather than on its position here. `brand`, `budget` and `category` come from
# catalog fields rather than prose, and they separate candidates the four
# vocabulary facets cannot tell apart.
FACETS: tuple[str, ...] = (
    "material", "color", "style", "use_case", "size", "brand", "budget", "category",
)
# `brand` and `category` are the highest-coverage facets in the catalog, 99% and
# 100% against 70% for the best prose-derived one, because they come from stated
# fields rather than from parsing a description. Two hiking boots can agree on
# material, colour, style and use and still differ by maker and by whether they
# are hiking boots or snow boots, which is exactly the case where the agent
# cannot tell candidates apart and should be asking.
#
# `budget` and `category` are only present when the bundled signature asset
# loaded: the FTS table has no price column and flattens the category path into
# text that cannot be split back. The board ranks whatever it is handed, so the
# source-only path asks a slightly worse question rather than a wrong one.


@dataclass(frozen=True, slots=True)
class QuestionDecision:
    """One catalog-grounded clarification decision and its stopping evidence.

    The score is deliberately interpretable.  Under a uniform candidate prior,
    ``expected_remaining`` is the expected residual set size after an answer.
    Coverage discounts facets most products cannot answer, and one turn of the
    remaining interaction horizon supplies the cost.  This is a bounded value-
    of-information controller, not a learned confidence number.
    """

    attribute: str = ""
    options: tuple[tuple[str, int], ...] = ()
    candidate_count: int = 0
    known_count: int = 0
    unknown_count: int = 0
    distinct_answer_groups: int = 0
    expected_remaining: float = 0.0
    expected_candidate_reduction: float = 0.0
    catalog_coverage: float = 0.0
    interaction_cost: float = 0.0
    net_value: float = 0.0
    sampled: bool = False
    reason: str = "no candidates"

    @property
    def asks(self) -> bool:
        return bool(self.attribute and self.options and self.net_value > 0.0)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["asks"] = self.asks
        return payload

def _groups(
    candidates: Sequence[str],
    facets: Mapping[str, Mapping[str, str]],
    attribute: str,
    excluded: frozenset[str],
) -> Counter:
    counts: Counter = Counter()
    for parent_asin in candidates:
        value = facets.get(parent_asin, {}).get(attribute, "")
        if value in excluded:
            value = ""
        counts[value or ""] += 1
    return counts


def _expected_remaining(counts: Counter, total: int) -> float:
    """Products still in play after the answer, in expectation."""
    if total <= 0:
        return 0.0
    return sum(size * size for size in counts.values()) / total


def clarification_board(
    candidates: Sequence[str],
    facets: Mapping[str, Mapping[str, str]],
    *,
    already_said: Iterable[str] = (),
    already_asked: Iterable[str] = (),
    max_options: int = 4,
    min_candidates: int = 2,
    turns_left: int = 9,
    sampled: bool = False,
    excluded_values: Iterable[str] = (),
) -> tuple[QuestionDecision, ...]:
    """Rank viable catalog facets by cost-adjusted expected set reduction.

    Unknown values remain an explicit answer group rather than disappearing
    from the denominator.  That prevents a sparse facet from looking valuable
    merely because most candidates cannot answer it.
    """
    total = len(candidates)
    if total < min_candidates:
        return ()
    spoken = " ".join(str(value).lower() for value in already_said)
    excluded = frozenset(str(value).lower() for value in excluded_values)
    interaction_cost = 1.0 / (max(0, int(turns_left)) + 1.0)
    asked = frozenset(str(name).lower() for name in already_asked)
    board: list[QuestionDecision] = []
    for name in FACETS:
        # A facet the customer has already been shown and did not answer is not
        # a better question the second time. The set shrinks between turns, so
        # the same facet keeps winning on fresh numbers and the conversation
        # stalls: asked four times running, it reads as an agent that is not
        # listening, which is worse than asking nothing.
        if name in asked:
            continue
        if re.search(rf"\b{re.escape(name)}\b", spoken):
            continue
        counts = _groups(candidates, facets, name, excluded)
        known = {value: size for value, size in counts.items() if value}
        # A facet nobody in the set has, or that everybody answers the same way,
        # cannot divide anything.
        if len(known) < 2:
            continue
        if any(value in spoken for value in known):
            continue
        known_count = sum(known.values())
        coverage = known_count / total
        options = tuple(
            sorted(known.items(), key=lambda item: (-item[1], item[0]))[:max_options]
        )
        # Score the question the customer is actually asked, not the facet.
        #
        # A facet is only worth its expected reduction if the customer can pick
        # one of the values on offer. `brand` divides a 400-product pool to 2.8
        # expected candidates, the best number any facet produces, and offers
        # four makers that between them cover 9% of the pool: nine times in ten
        # the honest answer is "none of those", the set does not shrink, and a
        # turn is gone. Ranking on the facet's full partition rewards exactly
        # that shape, because splitting into hundreds of singletons is what
        # minimises expected remaining.
        #
        # So the partition scored here is the one the question creates: one
        # group per offered value, and a single group for everything else,
        # which is what an unoffered value and an unknown value both mean to
        # the customer looking at the choices.
        offered = {value: size for value, size in options}
        offered_count = sum(offered.values())
        remainder = total - offered_count
        asked_counts = Counter(offered)
        if remainder:
            asked_counts[""] = remainder
        expected_remaining = _expected_remaining(asked_counts, total)
        expected_reduction = max(0.0, 1.0 - expected_remaining / total)
        offered_coverage = offered_count / total
        net_value = offered_coverage * expected_reduction - interaction_cost
        board.append(
            QuestionDecision(
                attribute=name,
                options=options,
                candidate_count=total,
                known_count=known_count,
                unknown_count=counts[""],
                distinct_answer_groups=len(known),
                expected_remaining=round(expected_remaining, 6),
                expected_candidate_reduction=round(expected_reduction, 6),
                catalog_coverage=round(coverage, 6),
                interaction_cost=round(interaction_cost, 6),
                net_value=round(net_value, 6),
                sampled=bool(sampled),
                reason=(
                    "positive cost-adjusted catalog value"
                    if net_value > 0.0
                    else "expected reduction does not repay another question"
                ),
            )
        )
    return tuple(
        sorted(
            board,
            key=lambda decision: (
                -decision.net_value,
                decision.expected_remaining,
                decision.attribute,
            ),
        )
    )


def choose_clarification(
    candidates: Sequence[str],
    facets: Mapping[str, Mapping[str, str]],
    *,
    already_said: Iterable[str] = (),
    already_asked: Iterable[str] = (),
    max_options: int = 4,
    min_candidates: int = 2,
    turns_left: int = 9,
    sampled: bool = False,
    excluded_values: Iterable[str] = (),
) -> QuestionDecision:
    """Choose a useful facet, or return an explicit stop decision."""

    board = clarification_board(
        candidates,
        facets,
        already_said=already_said,
        already_asked=already_asked,
        max_options=max_options,
        min_candidates=min_candidates,
        turns_left=turns_left,
        sampled=sampled,
        excluded_values=excluded_values,
    )
    if board and board[0].asks:
        return board[0]
    reason = board[0].reason if board else "no unanswered catalog facet divides the candidates"
    return QuestionDecision(
        candidate_count=len(candidates),
        sampled=bool(sampled),
        interaction_cost=round(1.0 / (max(0, int(turns_left)) + 1.0), 6),
        reason=reason,
    )


def clarifying_options(
    candidates: Sequence[str],
    facets: Mapping[str, Mapping[str, str]],
    *,
    already_said: Iterable[str] = (),
    max_options: int = 4,
    min_candidates: int = 2,
    excluded_values: Iterable[str] = (),
) -> tuple[str, tuple[tuple[str, int], ...]]:
    """Compatibility surface for callers that only render choices."""

    decision = choose_clarification(
        candidates,
        facets,
        already_said=already_said,
        max_options=max_options,
        min_candidates=min_candidates,
        excluded_values=excluded_values,
    )
    return decision.attribute, decision.options


__all__ = [
    "FACETS",
    "QuestionDecision",
    "clarification_board",
    "choose_clarification",
    "clarifying_options",
]
