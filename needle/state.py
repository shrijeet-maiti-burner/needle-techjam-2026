from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping

from needle.semantic import fold_diacritics, repair_trigger_text, trigger_keywords


# Retraction verbs, and the things a customer can retract. Split apart so the
# trigger is a rule about English rather than a list of released templates:
# a retraction verb aimed at some prior belief, or one of a few standalone
# idioms that mean the same thing on their own.
#
# Deliberately excluded: bare "actually", bare "instead", bare "no". An earlier
# revision matched bare "instead" and ordinary corrections then fired a full
# override. A false override is expensive, it bumps intent_version, clears the
# shown-candidate set, and discards belief, so this errs toward missing an
# override rather than inventing one.
_RETRACT = r"(?:ignore|disregard|forget|scratch|scrap|cancel|undo|drop)"
_PRIOR = (
    r"(?:"
    r"that|it|this"
    r"|(?:the\s+)?last\s+(?:thing|one|bit|request|message)?"
    r"|what\s+i\s+(?:said|told\s+you|asked\s+for)"
    r"|my\s+(?:earlier\s+|previous\s+|prior\s+|old\s+|last\s+|initial\s+|first\s+)?"
    r"(?:preference|request|requirement|requirements|criteria|answer|note)"
    r"|(?:my\s+)?(?:earlier|previous|prior|old)\s+"
    r"(?:preference|request|requirement|requirements|criteria)"
    r")"
)
EXPLICIT_OVERRIDE_RE = re.compile(
    r"(?:"
    rf"\b{_RETRACT}\s+(?:about\s+|all\s+of\s+)?(?:my\s+)?{_PRIOR}\b"
    r"|\bchanged?\s+my\s+mind\b"
    r"|\bnever\s?mind\b"
    r"|\bstart(?:ing)?\s+(?:over|fresh|again)\b"
    r"|\bon\s+second\s+thoughts?\b"
    r"|\bchange\s+of\s+plans?\b"
    r"|\binstead\s+i\s+need\b"
    r"|\bactually\s*,?\s*instead\b"
    r")",
    re.IGNORECASE,
)
# A preference retraction specifically, which is what licenses keeping the
# answers the customer already gave. Narrower than the trigger above: "start
# over" is an override but says nothing about which belief is being dropped.
# A retraction verb under a negated auxiliary is not a retraction. "Don't
# forget that I need cotton" is the customer holding a requirement in place,
# and reading it as an override does the exact opposite of what they asked:
# `observe` bumps `intent_version`, supersedes every active constraint and
# clears the message history, so the session is discarded at the moment the
# customer was most explicit about keeping it.
#
# This is a rule about English auxiliaries rather than a list of phrases, and
# it is the same primitive `_is_negated` applies to values: look at what
# governs the match, not just at the match. The negator must sit within two
# words of the trigger and inside the same clause, which is what the trailing
# anchor enforces, because `\w+` cannot cross the punctuation that would end
# the clause. So "I'm not sure, forget what I said" still overrides.
NEGATED_TRIGGER_RE = re.compile(
    r"(?:"
    r"\bcannot\b"
    r"|\b(?:do|does|did|ca|wo|sha|is|are|was|were|has|have|had"
    r"|could|would|should|must|need|dare)\s?n[’']?t\b"
    r"|\bnot\b|\bnever\b"
    r")(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)
PREFERENCE_OVERRIDE_RE = re.compile(
    r"(?:"
    rf"\b{_RETRACT}\s+(?:about\s+|all\s+of\s+)?(?:my\s+)?{_PRIOR}\b"
    r"|\bchanged?\s+my\s+mind\s+about\s+(?:that|the|my)\s+(?:earlier\s+)?"
    r"(?:preference|request|requirement)\b"
    r")",
    re.IGNORECASE,
)
SUBJECT_ANCHOR_RE = re.compile(
    r"\b(?:i\s*['’]?\s*m|i am)\s+(?:looking for|after)\s+(.+?)(?=[.;])"
    r"|\bi\s+(?:need|want)\s+(.+?)(?=[.;])",
    re.IGNORECASE,
)
OVERRIDE_POLICIES = frozenset(
    {"full_reset", "preserve_subject", "retract_stated", "no_reset"}
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


# Derived from the patterns themselves, so a pattern that gains a phrase
# cannot silently fall out of surface-repair coverage.
_TRIGGER_KEYWORDS = trigger_keywords(EXPLICIT_OVERRIDE_RE, PREFERENCE_OVERRIDE_RE)


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
# Where a negator stops governing. A fixed-width lookbehind alone cannot tell
# "not black but red" from "not black or navy": in the first the negator is
# corrected away before "red" is reached, in the second it still applies. The
# distance is the same, so only the punctuation between them carries the
# difference.
#
# Terminators and contrast end the scope; coordination does not. "and" is
# deliberately absent: it continues the negated list rather than separating
# from it, so "no black and navy" must keep both exclusions. This is why the
# rule is not `CLAUSE_END_RE`, which answers a different question (where a
# no-preference clause stops) and does treat "and" as a boundary.
NEGATION_SCOPE_END_RE = re.compile(r"[;,.]|\bbut\b", re.IGNORECASE)

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
    """Whether a negator still governs the value at ``offset``.

    The lookbehind is truncated at the last scope terminator, so a negator on
    the far side of one is not read as applying here. Without this the window
    leaks a correction's negation onto the value that corrects it, which is
    the exact opposite of what the customer said and reaches them as a
    "ruled out" line naming the thing they just asked for.

    The width cap is kept as well. It is what bounds a negator that governs
    nothing in particular when there is no punctuation to stop it.
    """
    window = message[max(0, offset - NEGATION_WINDOW):offset]
    last_boundary = None
    for boundary in NEGATION_SCOPE_END_RE.finditer(window):
        last_boundary = boundary
    if last_boundary is not None:
        window = window[last_boundary.end():]
    return bool(NEGATION_RE.search(window))


def fold_marks_in_place(message: str) -> str:
    """Strip combining marks without moving a single character offset.

    `ATTRIBUTE_VOCABULARY` is ASCII, so `_find_values` matches nothing at all
    against an accented value: "cótton" yields no constraint where "cotton"
    yields one, and the belief state simply loses the disclosure. That is the
    `needle/state.py` half of the accents gate, raised by Aryaman on #13.

    The obvious fix, folding the whole message with NFKD and dropping combining
    characters, is not safe here. It is not length-preserving, and
    `_declined_regions`, `inside_declined` and `_is_negated` all address this
    message by offset, so every offset past an accent would be wrong by one.

    Folding one character at a time keeps the mapping 1:1. A character is
    replaced only when its own decomposition is a single ASCII base plus
    combining marks, which is exactly the accented-Latin case; anything else,
    including ligatures like "fi" that decompose to two letters, is left alone.
    That matches `remove_diacritics 2` in the FTS5 tokenizer rather than
    exceeding it, so the two sides agree on what a term is.

    Deliberately not `needle.catalog.fold_marks`: that one is free to change
    length because it feeds a tokenizer, and importing it here would silently
    reintroduce the offset bug the moment it is used on a message.
    """
    if message.isascii():
        return message
    folded: list[str] = []
    for character in message:
        decomposed = unicodedata.normalize("NFKD", character)
        base = decomposed[0]
        if (
            len(decomposed) > 1
            and base.isascii()
            and all(unicodedata.combining(mark) for mark in decomposed[1:])
        ):
            folded.append(base)
        else:
            folded.append(character)
    return "".join(folded)


def extract_constraints(message: str) -> list[tuple[str, str, Polarity]]:
    """Attribute, value, polarity triples stated in one message.

    A no-preference clause is suppressed rather than the whole turn. The
    customer is declining to constrain one attribute, not excluding a value,
    so turning it into negation would filter the catalog on a belief they
    never expressed. Suppression covers the declined attribute by name and
    any value stated inside that clause, while the rest of the message is
    extracted normally.

    Accents are folded first, offsets intact, so a disclosure survives being
    written with them. The values appended below are vocabulary phrases rather
    than slices of the message, so nothing accented reaches the belief state.
    """
    message = fold_marks_in_place(message)
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


def _override_match(message: str) -> re.Match[str] | None:
    """The first retraction trigger that is not itself negated.

    Scanning rather than taking the first hit matters: a message can hold a
    negated trigger and a real one at once, and stopping at the negated one
    would drop an override the customer did state.
    """
    for match in EXPLICIT_OVERRIDE_RE.finditer(message):
        if not NEGATED_TRIGGER_RE.search(message[: match.start()]):
            return match
    return None


def extract_subject_anchor(message: str) -> str | None:
    """Return a sentence-bounded shopping subject.

    A terminator is mandatory. Without one, a preference that followed a
    stripped full stop would be indistinguishable from the shopping subject;
    preserving that text across an override would violate the correction.
    """
    message = fold_diacritics(message)
    match = SUBJECT_ANCHOR_RE.search(message)
    if match is None:
        return None
    subject = next((group for group in match.groups() if group), "").strip()
    return match.group(0).strip() + "." if subject else None


@dataclass(slots=True)
class SessionState:
    session_id: str
    user_profile: dict[str, object]
    override_policy: str = "full_reset"
    messages: list[str] = field(default_factory=list)
    intent_version: int = 1
    last_turn: int = 0
    constraints: list[Constraint] = field(default_factory=list)
    subject_anchor: str | None = None

    def observe(self, user_message: str, turn: int) -> None:
        if not 1 <= turn <= 10:
            raise ValueError(f"turn must be in 1..10, received {turn}")
        if turn <= self.last_turn:
            raise ValueError(f"turn must increase for session {self.session_id}")

        # Both triggers are consumed as booleans, never for their spans, so a
        # surface-repaired copy is safe to match against here. `subject_anchor`
        # and the no-preference clause logic keep using the raw message,
        # because those do depend on offsets.
        # Accents are handled structurally, before the trigger runs, because
        # edit-distance repair cannot reach them: the perturbation corrupts two
        # vowels in a word, which is two edits, and `repair_trigger_text` is
        # deliberately bounded at one. `fold_marks_in_place` is length
        # preserving, so `_declined_regions`, `inside_declined` and
        # `_is_negated` keep working on the offsets they already rely on, and
        # the folded text is what reaches `self.messages`, so retrieval and
        # signature extraction see the same normalization the belief state did.
        user_message = fold_marks_in_place(user_message)

        override_match = _override_match(user_message)
        preference_override = bool(PREFERENCE_OVERRIDE_RE.search(user_message))
        if not override_match:
            probe = repair_trigger_text(user_message, _TRIGGER_KEYWORDS)
            override_match = _override_match(probe)
            if override_match:
                preference_override = bool(PREFERENCE_OVERRIDE_RE.search(probe))
        if override_match:
            prior_subject = self.subject_anchor
            self.intent_version += 1
            self._supersede_all()
            if self.override_policy == "full_reset":
                self.messages.clear()
            elif self.override_policy == "preserve_subject":
                self.messages[:] = [prior_subject] if preference_override and prior_subject else []
            elif self.override_policy == "retract_stated":
                # The customer retracted the preference they stated up front,
                # not the answers they gave to our questions. Drop the opening
                # message's trailing preference clause by replacing it with its
                # own subject anchor, and keep every later reply.
                if preference_override:
                    preserved_subject = [prior_subject] if prior_subject else []
                    self.messages[:] = [*preserved_subject, *self.messages[1:]]
                else:
                    self.messages.clear()

        subject_anchor = extract_subject_anchor(user_message)
        if subject_anchor is not None and not (override_match and preference_override):
            self.subject_anchor = subject_anchor

        self._merge(extract_constraints(user_message), turn)
        self.messages.append(user_message)
        self.last_turn = turn

    # -- constraint bookkeeping ----------------------------------------- #

    def _supersede_all(self) -> None:
        """Supersede every active constraint at an override, recording the
        events rather than discarding them.

        EXP-006 asked whether targeted invalidation beats this. It is closed as
        not actionable (docs/evidence/EXP_006_SHAPES.md): across 45 well-formed
        override sessions, 30 public and 15 held out on card shapes the public
        set omits, `retract_stated` hits 100%, so there is no session a targeted
        policy could rescue. The remaining misses are on degenerate cards where
        `old_value` and `new_value` are the same string and there is nothing to
        invalidate selectively. Reopen only if a well-formed override misses."""
        self.constraints = [
            replace(constraint, status=ConstraintStatus.SUPERSEDED)
            if constraint.status is ConstraintStatus.ACTIVE
            else constraint
            for constraint in self.constraints
        ]

    def _merge(self, extracted: list[tuple[str, str, Polarity]], turn: int) -> None:
        for attribute, value, polarity in extracted:
            for contradicted in self._contradicted(attribute, value, polarity):
                self._supersede(contradicted)
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

    def _contradicted(
        self, attribute: str, value: str, polarity: Polarity
    ) -> list[Constraint]:
        """Active constraints the incoming one directly negates.

        A value and its own exclusion cannot both hold: "no leather" retracts
        an earlier "leather", and restating "leather" retracts an earlier
        "no leather". `_active_for` cannot see these because it filters to the
        same polarity, so without this both stayed ACTIVE at once and the
        belief state asserted and denied the same value.

        Matching is on attribute AND value, so unrelated exclusions still
        accumulate: "no black" does not retract "no red", and neither is
        touched by a positive on some other colour.
        """
        return [
            constraint
            for constraint in self.constraints
            if constraint.status is ConstraintStatus.ACTIVE
            and constraint.intent_version == self.intent_version
            and constraint.attribute == attribute
            and constraint.value == value
            and constraint.polarity is not polarity
        ]

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

    def __init__(self, override_policy: str = "full_reset") -> None:
        if override_policy not in OVERRIDE_POLICIES:
            raise ValueError(f"unsupported override policy: {override_policy}")
        self.override_policy = override_policy
        self._sessions: dict[str, SessionState] = {}

    def reset(self, session_id: str, user_profile: Mapping[str, object]) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty")
        self._sessions[session_id] = SessionState(
            session_id,
            dict(user_profile),
            override_policy=self.override_policy,
        )

    def observe(self, session_id: str, user_message: str, turn: int) -> SessionState:
        try:
            state = self._sessions[session_id]
        except KeyError as error:
            raise RuntimeError("reset must be called before respond") from error
        state.observe(user_message, turn)
        return state
