"""A negator must not govern past a scope terminator.

Red-team finding, human-state pass. Every case below is a *correction*: the
customer excludes one value and names the replacement in the same breath. A
fixed-width lookbehind cannot tell that apart from a coordinated exclusion,
because the distance is identical and only the punctuation differs, so the
belief state recorded the replacement as an exclusion too.

That is not a cosmetic mislabel. `active_constraints` feeds the customer-facing
turn record, where a NEGATIVE constraint becomes a "ruled out" line, so the
agent told the customer it had ruled out the thing they had just asked for.

The second class guards the other direction: coordination is not a terminator,
so genuinely accumulating exclusions must survive unchanged.
"""

from __future__ import annotations

import unittest

from needle.state import Polarity, extract_constraints


def _polarities(message: str) -> dict[tuple[str, str], Polarity]:
    return {(attribute, value): polarity for attribute, value, polarity in extract_constraints(message)}


class NegationStopsAtScopeTerminator(unittest.TestCase):
    """The value that corrects an exclusion is positive, not excluded."""

    CORRECTIONS = (
        ("I want not black but red.", ("color", "black"), ("color", "red")),
        ("Not leather, cotton.", ("material", "leather"), ("material", "cotton")),
        ("I don't want polyester. Cotton is fine.", ("material", "polyester"), ("material", "cotton")),
        ("Avoid wool; silk works.", ("material", "wool"), ("material", "silk")),
        ("No black, red instead.", ("color", "black"), ("color", "red")),
        ("not black, not navy, but green", ("color", "navy"), ("color", "green")),
    )

    def test_replacement_is_positive(self) -> None:
        for message, excluded, replacement in self.CORRECTIONS:
            with self.subTest(message=message):
                found = _polarities(message)
                self.assertEqual(found.get(excluded), Polarity.NEGATIVE, "exclusion lost")
                self.assertEqual(
                    found.get(replacement),
                    Polarity.POSITIVE,
                    "negation leaked past the terminator onto the correcting value",
                )


class CoordinationIsNotATerminator(unittest.TestCase):
    """"and"/"or" continue a negated list; both values stay excluded."""

    COORDINATED = (
        ("A dress. No black and no navy.", ("color", "black"), ("color", "navy")),
        ("I don't want black or navy", ("color", "black"), ("color", "navy")),
        ("no leather and no suede", ("material", "leather"), ("material", "suede")),
    )

    def test_both_values_stay_excluded(self) -> None:
        for message, first, second in self.COORDINATED:
            with self.subTest(message=message):
                found = _polarities(message)
                self.assertEqual(found.get(first), Polarity.NEGATIVE)
                self.assertEqual(found.get(second), Polarity.NEGATIVE)


class SimulatorSeparatorIsATerminator(unittest.TestCase):
    """`customer_reply` joins two constraints with "; ".

    So whenever the first disclosure carries a negation token, the second is
    within the lookbehind width of it. Measured on the 200 public cards under
    the `negate_value` perturbation: 50 of 400 two-span disclosures excluded a
    value that appeared only in the second span, before this rule existed.
    """

    def test_second_span_is_independent(self) -> None:
        found = _polarities("For that, what matters is: no leather; color: red.")
        self.assertEqual(found.get(("material", "leather")), Polarity.NEGATIVE)
        self.assertEqual(found.get(("color", "red")), Polarity.POSITIVE)

    def test_second_span_across_attributes(self) -> None:
        found = _polarities("For that, what matters is: no cotton; color: grey.")
        self.assertEqual(found.get(("material", "cotton")), Polarity.NEGATIVE)
        self.assertEqual(found.get(("color", "grey")), Polarity.POSITIVE)

    def test_within_span_comma_also_terminates(self) -> None:
        """A material list is comma separated, so only the negated head is
        excluded and the rest of the list is not swept up with it."""
        found = _polarities("For that, what matters is: no nylon; 4% Spandex.")
        self.assertEqual(found.get(("material", "nylon")), Polarity.NEGATIVE)
        self.assertEqual(found.get(("material", "spandex")), Polarity.POSITIVE)


class RuledOutLineNamesOnlyExclusions(unittest.TestCase):
    """The customer-visible consequence, asserted end to end through the state
    store rather than the extractor, so a regression in either is caught."""

    def test_corrected_value_is_not_reported_as_ruled_out(self) -> None:
        from needle.state import StateStore

        store = StateStore()
        store.reset("redteam", {})
        state = store.observe("redteam", "I need a jacket. Not black but red.", 1)
        unwanted = [
            constraint.value
            for constraint in state.active_constraints()
            if constraint.polarity is Polarity.NEGATIVE
        ]
        self.assertIn("black", unwanted)
        self.assertNotIn("red", unwanted)


if __name__ == "__main__":
    unittest.main()
