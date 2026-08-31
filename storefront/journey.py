"""Catalog-grounded state for non-linear, multi-item shopping journeys.

The competition agent deliberately owns one hidden target per session.  A real
shopping conversation does not: a customer can assemble an outfit, move from a
suit to shoes, express alternatives, or ask for inspiration without retracting
the earlier item.  This module adds that product-facing state without changing
``starter.agent:Agent`` or its measured retrieval policy.

There are no product identifiers, outfit pairs, or demo sentences in the
planner.  Product nouns come from the active catalog, constraints come from the
same parser as the scored agent, and the small language rules below describe
conversation operations rather than desired answers.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Callable, Iterable, Mapping, Sequence

from needle.catalog import query_terms
from needle.state import PREFERENCE_OVERRIDE_RE, Polarity, _override_match, extract_constraints


class ConstraintOperator(str, Enum):
    """How the values in a constraint group combine."""

    ALL = "all"
    ANY = "any"
    NOT = "not"


class ConstraintStrength(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class JourneyAction(str, Enum):
    UPDATE = "update_item"
    CREATE = "create_item"
    ACTIVATE = "activate_item"
    EXPLORE = "explore"
    COMPARE = "compare"


@dataclass(slots=True)
class ConstraintGroup:
    attribute: str
    operator: ConstraintOperator
    values: tuple[str, ...]
    strength: ConstraintStrength
    turn: int
    source: str
    prefer_all: bool = False

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["operator"] = self.operator.value
        payload["strength"] = self.strength.value
        return payload


@dataclass(slots=True)
class LineItem:
    item_id: str
    category: str
    label: str
    created_turn: int
    agent_session_id: str
    constraints: list[ConstraintGroup] = field(default_factory=list)
    superseded: list[ConstraintGroup] = field(default_factory=list)
    relation: str | None = None
    related_item_id: str | None = None
    local_turn: int = 0
    selected_id: str | None = None
    last_ids: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    audience: str | None = None

    def positive_groups(self) -> tuple[ConstraintGroup, ...]:
        return tuple(
            group for group in self.constraints
            if group.operator is not ConstraintOperator.NOT
        )

    def negative_groups(self) -> tuple[ConstraintGroup, ...]:
        return tuple(
            group for group in self.constraints
            if group.operator is ConstraintOperator.NOT
        )

    def as_dict(self, *, active: bool = False) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "category": self.category,
            "label": self.label,
            "created_turn": self.created_turn,
            "active": active,
            "constraints": [group.as_dict() for group in self.constraints],
            "superseded": [group.as_dict() for group in self.superseded],
            "relation": self.relation,
            "related_item_id": self.related_item_id,
            "selected_id": self.selected_id,
            "last_ids": list(self.last_ids),
            "audience": self.audience,
        }


@dataclass(slots=True)
class ShoppingPlan:
    session_id: str
    items: list[LineItem] = field(default_factory=list)
    active_item_id: str | None = None
    global_context: list[str] = field(default_factory=list)
    # value -> the turn it was first stated, so the belief rail can attribute
    # shared context to a turn instead of inventing one.
    context_turns: dict[str, int] = field(default_factory=dict)
    last_action: JourneyAction = JourneyAction.UPDATE
    exploration: bool = False
    comparison: bool = False
    language: str = "en"

    @property
    def active_item(self) -> LineItem | None:
        return next(
            (item for item in self.items if item.item_id == self.active_item_id),
            None,
        )

    def item(self, item_id: str | None) -> LineItem | None:
        return next((item for item in self.items if item.item_id == item_id), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "journey",
            "active_item_id": self.active_item_id,
            "global_context": list(self.global_context),
            "last_action": self.last_action.value,
            "exploration": self.exploration,
            "comparison": self.comparison,
            "language": self.language,
            "items": [
                item.as_dict(active=item.item_id == self.active_item_id)
                for item in self.items
            ],
        }


@dataclass(frozen=True, slots=True)
class PlanDecision:
    action: JourneyAction
    active_item_id: str | None
    created_item_ids: tuple[str, ...] = ()
    category_mentions: tuple[str, ...] = ()
    exploration: bool = False
    comparison: bool = False


_RELATION_RE = re.compile(
    r"\b(?:go(?:es)?\s+with|match(?:es|ing)?|pair(?:s|ed|ing)?\s+with|"
    r"along\s+with|complement(?:s|ary)?|complete\s+(?:the|my|this)\s+look)\b",
    re.IGNORECASE,
)
_ADD_RE = re.compile(
    r"\b(?:add|also|another|next|need|want|looking\s+for|find|show\s+me)\b",
    re.IGNORECASE,
)
_EXPLORE_RE = re.compile(
    r"\b(?:suggest(?:ion|ions)?|ideas?|inspir(?:e|ation)|surprise\s+me|"
    r"don['’]?t\s+know|not\s+sure|open\s+to\s+anything|you\s+choose)\b",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|difference|which\s+(?:one|is)|"
    r"why\s+(?:is|are|did|does))\b",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    r"\b(?:actually|instead|rather|make\s+it|change|replace|no\s*,|not\s+.+?\bbut\b)\b",
    re.IGNORECASE,
)
_SOFT_RE = re.compile(
    r"\b(?:maybe|perhaps|prefer|would\s+(?:like|be\s+nice)|ideally|if\s+possible)\b",
    re.IGNORECASE,
)
_ANY_RE = re.compile(r"\b(?:or|either)\b", re.IGNORECASE)
_BOTH_RE = re.compile(r"\b(?:both|and)\b", re.IGNORECASE)
_CONTEXT_EQUIVALENTS: Mapping[str, re.Pattern[str]] = {
    # Irregular language equivalents cannot be recovered by stemming.  This is
    # a meaning-preserving normalization over an existing use-case facet, not a
    # product or ranking rule.
    "wedding": re.compile(r"\b(?:marry|married|marriage|nuptials?)\b", re.IGNORECASE),
}


def _stable_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip().lower() for value in values if str(value).strip()))


def _same_category(left: str, right: str) -> bool:
    """Loose singular equivalence for catalog-derived category mentions."""

    def stem(value: str) -> str:
        text = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        words = []
        for word in text.split():
            if word.endswith("ies") and len(word) > 4:
                word = f"{word[:-3]}y"
            elif word.endswith("es") and len(word) > 4:
                word = word[:-2]
            elif word.endswith("s") and len(word) > 3:
                word = word[:-1]
            words.append(word)
        return " ".join(words)

    a, b = stem(left), stem(right)
    return bool(a and b and (a == b or a in b.split() or b in a.split()))


class DeterministicJourneyPlanner:
    """Interpret shopping operations while leaving retrieval to Needle.

    ``category_mentions`` is supplied by :class:`CatalogView`; this is the
    boundary that prevents the planner from carrying a private product taxonomy.
    """

    def __init__(
        self,
        category_mentions: Callable[[str], Sequence[str]],
        audience_mentions: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        self._category_mentions = category_mentions
        self._audience_mentions = audience_mentions or (lambda _text: ())

    def observe(self, plan: ShoppingPlan, message: str, turn: int) -> PlanDecision:
        text = str(message).strip()
        comparison = bool(_COMPARE_RE.search(text))
        exploration = bool(_EXPLORE_RE.search(text))
        override = _override_match(text)
        if override is not None:
            if PREFERENCE_OVERRIDE_RE.search(text) and plan.active_item is not None:
                active = plan.active_item
                active.superseded.extend(active.constraints)
                active.constraints = []
            else:
                plan.items.clear()
                plan.active_item_id = None
                plan.global_context.clear()
                plan.context_turns.clear()
        categories = tuple(dict.fromkeys(self._category_mentions(text)))
        audiences = tuple(dict.fromkeys(self._audience_mentions(text)))
        stated_audience = audiences[0] if len(audiences) == 1 else None
        previous = plan.active_item
        created: list[str] = []

        # A message can introduce more than one line item.  Most turns route to
        # the final mention because English places the requested complement at
        # the end ("a suit and shoes"), while every item remains in the plan.
        for category in categories:
            existing = next(
                (item for item in plan.items if _same_category(item.category, category)),
                None,
            )
            if existing is not None:
                plan.active_item_id = existing.item_id
                continue
            # A vague opening needs a retrieval surface before the shopper has
            # named a product type. Once they do, promote that placeholder in
            # place. Keeping it as a separate "Current item" creates a phantom
            # plan node and makes the real item appear to complement nothing.
            if (
                previous is not None
                and previous.category == "item"
                and previous.label == "Current item"
                and previous.selected_id is None
            ):
                previous.category = category.lower()
                previous.label = category.strip().title()
                plan.active_item_id = previous.item_id
                created.append(previous.item_id)
                continue
            # A new product type inside a continuing session is a separate line
            # item, not an implicit replacement.  Explicit restart language was
            # handled above, so linking it to the prior active item is the
            # conservative representation and never copies item constraints.
            related = previous
            item_id = f"item-{uuid.uuid4().hex[:8]}"
            item = LineItem(
                item_id=item_id,
                category=category.lower(),
                label=category.strip().title(),
                created_turn=int(turn),
                agent_session_id=f"{plan.session_id}:{item_id}",
                relation=(
                    "complements"
                    if related is not None
                    and (_RELATION_RE.search(text) or _ADD_RE.search(text) or len(categories) > 1)
                    else "same_journey" if related is not None else None
                ),
                related_item_id=related.item_id if related is not None else None,
                audience=stated_audience or (related.audience if related is not None else None),
            )
            plan.items.append(item)
            plan.active_item_id = item.item_id
            previous = item
            created.append(item.item_id)

        if plan.active_item is None:
            item_id = f"item-{uuid.uuid4().hex[:8]}"
            item = LineItem(
                item_id=item_id,
                category="item",
                label="Current item",
                created_turn=int(turn),
                agent_session_id=f"{plan.session_id}:{item_id}",
            )
            plan.items.append(item)
            plan.active_item_id = item.item_id
            created.append(item.item_id)

        active = plan.active_item
        assert active is not None
        if stated_audience is not None:
            active.audience = stated_audience
        active.messages.append(text[:500])
        # Values named in "why is black above brown?" identify comparison
        # operands; treating them as new preferences corrupts the plan.
        if not comparison:
            self._apply_constraints(plan, active, text, int(turn))

        plan.exploration = exploration
        plan.comparison = comparison
        if plan.exploration:
            action = JourneyAction.EXPLORE
        elif plan.comparison:
            action = JourneyAction.COMPARE
        elif created:
            action = JourneyAction.CREATE
        elif categories:
            action = JourneyAction.ACTIVATE
        else:
            action = JourneyAction.UPDATE
        plan.last_action = action
        return PlanDecision(
            action=action,
            active_item_id=plan.active_item_id,
            created_item_ids=tuple(created),
            category_mentions=categories,
            exploration=plan.exploration,
            comparison=plan.comparison,
        )

    def _apply_constraints(
        self,
        plan: ShoppingPlan,
        item: LineItem,
        message: str,
        turn: int,
    ) -> None:
        parsed = extract_constraints(message)
        by_attribute: dict[tuple[str, Polarity], list[str]] = {}
        for attribute, value, polarity in parsed:
            if attribute == "use_case" and polarity is Polarity.POSITIVE:
                if value not in plan.global_context:
                    plan.global_context.append(value)
                    plan.context_turns.setdefault(value, int(turn))
                continue
            by_attribute.setdefault((attribute, polarity), []).append(value)
        for value, pattern in _CONTEXT_EQUIVALENTS.items():
            if pattern.search(message) and value not in plan.global_context:
                plan.global_context.append(value)
                plan.context_turns.setdefault(value, int(turn))

        correcting = bool(_CORRECTION_RE.search(message))
        soft = bool(_SOFT_RE.search(message))
        for (attribute, polarity), raw_values in by_attribute.items():
            values = _stable_values(raw_values)
            if not values:
                continue
            if polarity is Polarity.NEGATIVE:
                operator = ConstraintOperator.NOT
                strength = ConstraintStrength.HARD
                # A correction explicitly rejects the old value.  Preserve the
                # audit row, but remove it from every live positive group.
                if correcting:
                    self._supersede_values(item, attribute, set(values))
            else:
                if len(values) > 1 and _ANY_RE.search(message):
                    operator = ConstraintOperator.ANY
                elif len(values) > 1 and _BOTH_RE.search(message):
                    operator = ConstraintOperator.ALL
                else:
                    operator = ConstraintOperator.ALL
                strength = ConstraintStrength.SOFT if soft else ConstraintStrength.HARD
                if correcting or len(values) == 1:
                    self._supersede_attribute(item, attribute)

            group = ConstraintGroup(
                attribute=attribute,
                operator=operator,
                values=values,
                strength=strength,
                turn=turn,
                source=message[:240],
                prefer_all=(operator is ConstraintOperator.ANY and bool(_BOTH_RE.search(message))),
            )
            if not any(
                existing.attribute == group.attribute
                and existing.operator is group.operator
                and existing.values == group.values
                for existing in item.constraints
            ):
                item.constraints.append(group)

    @staticmethod
    def _supersede_attribute(item: LineItem, attribute: str) -> None:
        kept: list[ConstraintGroup] = []
        for group in item.constraints:
            if group.attribute == attribute and group.operator is not ConstraintOperator.NOT:
                item.superseded.append(group)
            else:
                kept.append(group)
        item.constraints = kept

    @staticmethod
    def _supersede_values(item: LineItem, attribute: str, values: set[str]) -> None:
        kept: list[ConstraintGroup] = []
        for group in item.constraints:
            if group.attribute != attribute or group.operator is ConstraintOperator.NOT:
                kept.append(group)
                continue
            remaining = tuple(value for value in group.values if value not in values)
            if remaining == group.values:
                kept.append(group)
            else:
                item.superseded.append(group)
                if remaining:
                    kept.append(
                        ConstraintGroup(
                            attribute=group.attribute,
                            operator=group.operator,
                            values=remaining,
                            strength=group.strength,
                            turn=group.turn,
                            source=group.source,
                            prefer_all=group.prefer_all,
                        )
                    )
        item.constraints = kept


def journey_beliefs(plan: ShoppingPlan) -> dict[str, object]:
    """Everything the plan has understood, not just the item in focus.

    The rail is headed "what I have understood", so scoping it to the active
    line item made it contradict the panel beside it: after "wedding", "a navy
    suit", "now matching shoes" the plan showed the occasion and the colour
    while the rail said "nothing disclosed yet", because navy belongs to the
    suit and the active item had become the shoes.

    Every entry therefore carries the label of the item it constrains, so a
    plan-wide view stays unambiguous: the colour reads as the suit's colour and
    not the shoes'. Shared journey context, which belongs to no single item,
    is attributed to the journey.
    """

    wanted: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    superseded: list[dict[str, object]] = []

    def entry(group: ConstraintGroup, value: str, owner: str) -> dict[str, object]:
        return {
            "attribute": group.attribute,
            "value": value,
            "turn": group.turn,
            "operator": group.operator.value,
            "strength": group.strength.value,
            "item": owner,
        }

    for value in plan.global_context:
        wanted.append(
            {
                "attribute": "occasion",
                "value": value,
                "turn": plan.context_turns.get(value, 1),
                "operator": "all",
                "strength": "hard",
                "item": "shared",
            }
        )

    # Active item first: it is the one the next answer will change.
    active = plan.active_item
    ordered = [item for item in plan.items if item is active]
    ordered += [item for item in plan.items if item is not active]
    for item in ordered:
        for group in item.constraints:
            destination = (
                excluded if group.operator is ConstraintOperator.NOT else wanted
            )
            for value in group.values:
                destination.append(entry(group, value, item.label))
        for group in item.superseded:
            for value in group.values:
                superseded.append(entry(group, value, item.label))

    return {
        "wanted": wanted,
        "excluded": excluded,
        "superseded": superseded,
        "intent_version": 1 + sum(len(item.superseded) for item in plan.items),
    }


def query_for(plan: ShoppingPlan, item: LineItem) -> str:
    """Stable retrieval text containing only interpreted shopping evidence."""

    terms: list[str] = [item.category, *(item.audience or "",), *plan.global_context]
    for group in item.positive_groups():
        terms.extend(group.values)
    # Retain bounded free-text evidence such as "garden" or "daytime" that is
    # useful to sparse retrieval but is not one of the scorer's compact facets.
    # This is the shopper's language, not a generated expansion.
    terms.extend(query_terms(" ".join(item.messages[-2:]), limit=30))
    return " ".join(dict.fromkeys(term for term in terms if term)).strip()


def alternative_queries(plan: ShoppingPlan, item: LineItem) -> tuple[str, ...]:
    """One query per disjunct, used to avoid collapsing ``blue or white``."""

    any_groups = [group for group in item.positive_groups() if group.operator is ConstraintOperator.ANY]
    if not any_groups:
        return (query_for(plan, item),)
    base = [item.category, *(item.audience or "",), *plan.global_context]
    fixed = [
        value
        for group in item.positive_groups()
        if group.operator is not ConstraintOperator.ANY
        for value in group.values
    ]
    queries = [
        " ".join(dict.fromkeys([*base, *fixed, value]))
        for group in any_groups
        for value in group.values
    ]
    return tuple(dict.fromkeys(query.strip() for query in queries if query.strip()))


__all__ = [
    "ConstraintGroup",
    "ConstraintOperator",
    "ConstraintStrength",
    "DeterministicJourneyPlanner",
    "JourneyAction",
    "LineItem",
    "PlanDecision",
    "ShoppingPlan",
    "alternative_queries",
    "journey_beliefs",
    "query_for",
]
