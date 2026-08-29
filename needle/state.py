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
# simulator is declining to constrain, not excluding a value. Checked before
# extraction so a no-preference turn cannot manufacture a filter.
NO_PREFERENCE_RE = re.compile(
    r"\b(?:no preference|don'?t have (?:a|an additional) preference|"
    r"use your judgment|whatever you recommend|not fussed|no strong feelings)\b",
    re.IGNORECASE,
)

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

    Returns nothing for a no-preference reply. That case is deliberately not
    treated as negation: the customer is declining to constrain the
    attribute, and turning it into an exclusion would filter the catalog on
    a belief the customer never expressed.
    """
    if NO_PREFERENCE_RE.search(message):
        return []

    found: list[tuple[str, str, Polarity]] = []
    for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
        for value, offset in _find_values(message, vocabulary):
            polarity = Polarity.NEGATIVE if _is_negated(message, offset) else Polarity.POSITIVE
            found.append((attribute, value.lower(), polarity))

    budget = BUDGET_RE.search(message)
    if budget:
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
            current = self._active_for(attribute, polarity)
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

    def _active_for(self, attribute: str, polarity: Polarity) -> Constraint | None:
        # Only positive constraints supersede each other. Two exclusions can
        # coexist ("not black, not red"), so negatives accumulate.
        if polarity is Polarity.NEGATIVE:
            return None
        for constraint in reversed(self.constraints):
            if (
                constraint.status is ConstraintStatus.ACTIVE
                and constraint.intent_version == self.intent_version
                and constraint.attribute == attribute
                and constraint.polarity is Polarity.POSITIVE
            ):
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
