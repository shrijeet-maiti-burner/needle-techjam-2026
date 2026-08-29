from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping


EXPLICIT_OVERRIDE_RE = re.compile(
    r"\b(?:ignore my earlier preference|ignore what i said|changed my mind|instead i need|actually,? instead)\b",
    re.IGNORECASE,
)

# The released Boundary reply is "I don't have a preference for <attribute>;
# please use your judgment." It must never become a negative constraint: the
# simulator is declining to constrain, not excluding a value.
#
# Scoped to its own clause rather than the whole message, so a mixed turn
# such as "no preference for color, but cotton is required" still yields the
# material constraint. Only the declined clause is suppressed.
NO_PREFERENCE_RE = re.compile(
    r"\b(?:no preference|don'?t have (?:a|an|any|an additional) preference|"
    r"use your judgment|whatever you recommend|not fussed|no strong feelings)\b",
    re.IGNORECASE,
)
# A clause ends at the next separator or the end of the message.
CLAUSE_END_RE = re.compile(r"[;,.]|\band\b|\bbut\b", re.IGNORECASE)

# Attribute names the customer can decline by name.
ATTRIBUTE_NAME_RE = re.compile(
    r"\b(material|colou?r|size|style|use[ _-]?case|budget|price|feature|brand|category)\b",
    re.IGNORECASE,
)
ATTRIBUTE_NAME_ALIASES = {
    "colour": "color",
    "price": "budget",
    "use case": "use_case",
    "use-case": "use_case",
}


def _declined_regions(message: str) -> list[tuple[int, int]]:
    """Character spans covering each no-preference clause."""
    regions: list[tuple[int, int]] = []
    for match in NO_PREFERENCE_RE.finditer(message):
        end_match = CLAUSE_END_RE.search(message, match.end())
        regions.append((match.start(), end_match.start() if end_match else len(message)))
    return regions


def _declined_attributes(message: str, regions: list[tuple[int, int]]) -> set[str]:
    """Attributes named inside a no-preference clause, normalized."""
    declined: set[str] = set()
    for start, end in regions:
        for name in ATTRIBUTE_NAME_RE.finditer(message, start, end):
            raw = name.group(1).lower().replace("_", " ").replace("-", " ")
            declined.add(ATTRIBUTE_NAME_ALIASES.get(raw, raw.replace(" ", "_")))
    return declined

# Negation is only trusted immediately before the matched value. Anything
# looser stays positive rather than silently creating an exclusion, because a
# wrong hard exclusion can remove the target for the rest of the session.
NEGATION_RE = re.compile(
    r"\b(?:no|not|without|non|avoid|skip|dislike|don'?t want|nothing)\b",
    re.IGNORECASE,
)
NEGATION_WINDOW = 24

MATERIALS = (
    "cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk",
    "rayon", "denim", "linen", "suede", "fleece", "cashmere", "canvas",
    "mesh", "velvet", "satin", "alloy", "stainless steel", "sterling silver",
    "gold plated", "titanium", "brass", "copper", "rhinestone", "crystal",
    "cubic zirconia", "pearl", "resin", "acrylic",
)
COLORS = (
    "black", "white", "blue", "red", "pink", "green", "brown", "gray",
    "grey", "purple", "yellow", "orange", "beige", "navy", "tan", "gold",
    "silver", "burgundy", "maroon", "khaki", "cream", "ivory",
)
SIZES = (
    "xs", "small", "medium", "large", "xl", "xxl", "petite", "plus size",
    "wide width", "narrow", "tall",
)
STYLES = (
    "casual", "formal", "athletic", "vintage", "classic", "bohemian",
    "minimalist", "sporty", "elegant", "slim fit", "loose fit", "oversized",
    "cropped", "sleeveless", "long sleeve", "short sleeve", "v-neck",
    "crew neck", "button down", "zip up",
)
USE_CASES = (
    "hiking", "running", "gym", "winter", "outdoor", "work", "wedding",
    "party", "beach", "travel", "yoga", "workout", "everyday", "summer",
    "office", "school", "rain", "cold weather",
)

# Ordered so that the most specific attributes are extracted first.
ATTRIBUTE_VOCABULARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("material", MATERIALS),
    ("color", COLORS),
    ("style", STYLES),
    ("use_case", USE_CASES),
    ("size", SIZES),
)

BUDGET_RE = re.compile(
    r"(?:under|below|less than|at most|up to|<=?)\s*\$?\s*(\d+(?:\.\d+)?)"
    r"|\$\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


class Polarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ConstraintStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class Constraint:
    """One explicit belief taken from a customer message.

    Immutable: correction and override replace a constraint by marking the
    old record superseded and appending a new one, so the event log stays
    replayable for diagnostics instead of being edited in place.
    """

    attribute: str
    value: str
    polarity: Polarity
    turn: int
    intent_version: int
    status: ConstraintStatus = ConstraintStatus.ACTIVE
    supersedes: str | None = None

    @property
    def key(self) -> str:
        return f"{self.attribute}:{self.value}:{self.polarity.value}"


def _find_values(message: str, vocabulary: tuple[str, ...]) -> list[tuple[str, int]]:
    """Every vocabulary hit with its start offset, longest match first so
    'stainless steel' is preferred over a bare substring."""
    found: list[tuple[str, int]] = []
    for phrase in sorted(vocabulary, key=len, reverse=True):
        for match in re.finditer(rf"\b{re.escape(phrase)}\b", message, re.IGNORECASE):
            if any(
                start <= match.start() < start + len(existing)
                for existing, start in found
            ):
                continue
            found.append((phrase, match.start()))
    return found


def _is_negated(message: str, offset: int) -> bool:
    window = message[max(0, offset - NEGATION_WINDOW):offset]
    return bool(NEGATION_RE.search(window))


def extract_constraints(message: str) -> list[tuple[str, str, Polarity]]:
    """Attribute, value, polarity triples stated in one message.

    A no-preference clause is suppressed rather than the whole turn. The
    customer is declining to constrain one attribute, not excluding a value,
    so turning it into negation would filter the catalog on a belief they
    never expressed. Suppression covers the declined attribute by name and
    any value stated inside that clause, while the rest of the message is
    extracted normally.
    """
    regions = _declined_regions(message)
    declined = _declined_attributes(message, regions)

    def inside_declined(offset: int) -> bool:
        return any(start <= offset < end for start, end in regions)

    found: list[tuple[str, str, Polarity]] = []
    for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
        if attribute in declined:
            continue
        for value, offset in _find_values(message, vocabulary):
            if inside_declined(offset):
                continue
            polarity = Polarity.NEGATIVE if _is_negated(message, offset) else Polarity.POSITIVE
            found.append((attribute, value.lower(), polarity))

    if "budget" not in declined:
        budget = BUDGET_RE.search(message)
        if budget and not inside_declined(budget.start()):
            amount = next((group for group in budget.groups() if group), None)
            if amount:
                found.append(("budget", amount, Polarity.POSITIVE))
    return found


@dataclass(slots=True)
class SessionState:
    session_id: str
    user_profile: dict[str, object]
    messages: list[str] = field(default_factory=list)
    intent_version: int = 1
    last_turn: int = 0
    constraints: list[Constraint] = field(default_factory=list)

    def observe(self, user_message: str, turn: int) -> None:
        if not 1 <= turn <= 10:
            raise ValueError(f"turn must be in 1..10, received {turn}")
        if turn <= self.last_turn:
            raise ValueError(f"turn must increase for session {self.session_id}")

        if EXPLICIT_OVERRIDE_RE.search(user_message):
            self.intent_version += 1
            self.messages.clear()
            self._supersede_all()

        self._merge(extract_constraints(user_message), turn)
        self.messages.append(user_message)
        self.last_turn = turn

    # -- constraint bookkeeping ----------------------------------------- #

    def _supersede_all(self) -> None:
        """Targeted invalidation is an open question (EXP-006). Until that
        evidence exists this mirrors the previous full-reset behavior so the
        override path stays unchanged, while recording the superseded events
        rather than discarding them."""
        self.constraints = [
            replace(constraint, status=ConstraintStatus.SUPERSEDED)
            if constraint.status is ConstraintStatus.ACTIVE
            else constraint
            for constraint in self.constraints
        ]

    def _merge(self, extracted: list[tuple[str, str, Polarity]], turn: int) -> None:
        for attribute, value, polarity in extracted:
            current = self._active_for(attribute, polarity, value)
            if current is not None and current.value == value:
                continue  # restated, not a new belief
            if current is not None:
                self._supersede(current)
            self.constraints.append(
                Constraint(
                    attribute=attribute,
                    value=value,
                    polarity=polarity,
                    turn=turn,
                    intent_version=self.intent_version,
                    supersedes=current.key if current is not None else None,
                )
            )

    def _active_for(
        self, attribute: str, polarity: Polarity, value: str
    ) -> Constraint | None:
        """The active constraint a new one would replace, if any.

        Positive constraints supersede by attribute: a new colour replaces the
        previous colour. Negatives do not, because "not black" and "not red"
        are two independent exclusions that must accumulate. A negative
        therefore matches only its own exact value, which makes restating the
        same exclusion idempotent instead of appending a duplicate.
        """
        for constraint in reversed(self.constraints):
            if (
                constraint.status is not ConstraintStatus.ACTIVE
                or constraint.intent_version != self.intent_version
                or constraint.attribute != attribute
                or constraint.polarity is not polarity
            ):
                continue
            if polarity is Polarity.NEGATIVE and constraint.value != value:
                continue
            return constraint
        return None

    def _supersede(self, target: Constraint) -> None:
        self.constraints = [
            replace(constraint, status=ConstraintStatus.SUPERSEDED)
            if constraint is target
            else constraint
            for constraint in self.constraints
        ]

    # -- read API for downstream owners --------------------------------- #

    def active_constraints(self) -> tuple[Constraint, ...]:
        return tuple(
            constraint
            for constraint in self.constraints
            if constraint.status is ConstraintStatus.ACTIVE
            and constraint.intent_version == self.intent_version
        )

    def excluded_values(self, attribute: str) -> tuple[str, ...]:
        return tuple(
            constraint.value
            for constraint in self.active_constraints()
            if constraint.attribute == attribute
            and constraint.polarity is Polarity.NEGATIVE
        )

    @property
    def retrieval_text(self) -> str:
        """Message history for the current intent version. Deliberately
        unchanged from the previous implementation, so this branch is a pure
        structural refactor with no retrieval effect.

        Appending active constraint values here was tried and removed: every
        active constraint is extracted from a message still in `self.messages`
        (an override clears messages and supersedes constraints together), and
        `catalog.query_terms` deduplicates, so the appended values were always
        redundant. Measured: byte-identical results across all 200 public
        sessions. Dead code was not worth shipping.

        This changes once targeted invalidation lands (EXP-006), because
        constraints will then survive an override that clears messages. At
        that point surviving values must be injected here, and negatives must
        still be withheld: adding an excluded term to a bag-of-words query
        retrieves exactly what the customer rejected. Filtering on negatives
        belongs to retrieval, which reads `excluded_values`.
        """
        return " ".join(self.messages).strip()


class StateStore:
    """Session lifecycle boundary. Owns belief state; never ranks or filters."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def reset(self, session_id: str, user_profile: Mapping[str, object]) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty")
        self._sessions[session_id] = SessionState(session_id, dict(user_profile))

    def observe(self, session_id: str, user_message: str, turn: int) -> SessionState:
        try:
            state = self._sessions[session_id]
        except KeyError as error:
            raise RuntimeError("reset must be called before respond") from error
        state.observe(user_message, turn)
        return state
