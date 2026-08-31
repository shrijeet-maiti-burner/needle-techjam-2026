"""Red team follow-ups: retraction object, negation surface, negation scope.

The two findings here were recorded as "not fixed" in
`docs/evidence/REDTEAM_HUMAN_STATE.md` when the earlier state fixes landed, so
the inputs are the exact ones that failed there. The third class guards a
false exclusion that appeared while fixing the second.
"""

from __future__ import annotations

import unittest

from needle.state import Polarity, extract_constraints, _override_match


def _polarity(message: str, value: str) -> Polarity | None:
    for _, found, polarity in extract_constraints(message):
        if found == value:
            return polarity
    return None


class ARetractionVerbNeedsARetractionObject(unittest.TestCase):
    """A bare pronoun is only anaphoric when it ends the clause.

    "Cancel that shipping upgrade" uses "that" as a determiner and "Drop it in
    my basket" uses "it" as the object of a preposition. Both fired a full
    session reset: `intent_version` bumped, every constraint superseded, the
    message history cleared.
    """

    NOT_RETRACTIONS = (
        "Drop it in my basket if it's under $50.",
        "Cancel that shipping upgrade, not my preference.",
        "Drop that jacket into my cart.",
        "Skip that page and show me the next one.",
    )

    def test_no_override(self) -> None:
        for message in self.NOT_RETRACTIONS:
            with self.subTest(message=message):
                self.assertIsNone(_override_match(message))

    RETRACTIONS = (
        "Ignore that.",
        "Ignore that too. I need wool socks.",
        "Forget it.",
        "Scrap that, I want boots.",
        "Drop it, let's start again.",
        "Disregard this; I need something formal.",
        "Ignore all of that. Start over.",
        "Forget what I said, I need wool.",
    )

    def test_override_still_fires(self) -> None:
        for message in self.RETRACTIONS:
            with self.subTest(message=message):
                self.assertIsNotNone(_override_match(message))

    def test_the_released_simulator_templates_still_override(self) -> None:
        """`local_evaluator` sends exactly these two. Non-negotiable."""
        for message in (
            "Actually, ignore my earlier preference. What I need is: Cotton.",
            "Actually, please ignore my earlier preference.",
        ):
            with self.subTest(message=message):
                self.assertIsNotNone(_override_match(message))


class NegationLivesOnTheAuxiliary(unittest.TestCase):
    """`don't want` hardcoded one verb; the negation is on the auxiliary."""

    EXCLUDED = (
        ("I don't like black.", "black"),
        ("I don't need leather.", "leather"),
        ("I dont like black.", "black"),
        ("I never wear black.", "black"),
        ("I won't wear black.", "black"),
    )

    def test_value_is_excluded(self) -> None:
        for message, value in self.EXCLUDED:
            with self.subTest(message=message):
                self.assertIs(_polarity(message, value), Polarity.NEGATIVE)

    STILL_MISSED = ("I hate black.", "black is out")

    def test_semantic_exclusions_are_still_missed(self) -> None:
        """Documented, not aspirational. Catching these needs a list of
        opinion verbs rather than a rule, so the test records the limit and
        will fail loudly if someone changes it without saying so."""
        for message in self.STILL_MISSED:
            with self.subTest(message=message):
                self.assertIs(_polarity(message, "black"), Polarity.POSITIVE)


class IndifferenceIsNotAConstraint(unittest.TestCase):
    """What makes the rule above safe to generalise.

    "I don't mind black" is neither a request for black nor a ban on it, and
    before this it was read as a request. It is the customer declining to
    constrain, so it belongs with the other no-preference phrasings and must
    yield nothing at all.
    """

    DECLINED = (
        "I don't mind black.",
        "I don't care about black.",
        "I'm not bothered about black.",
        "Either is fine.",
    )

    def test_nothing_is_extracted(self) -> None:
        for message in self.DECLINED:
            with self.subTest(message=message):
                self.assertEqual(extract_constraints(message), [])

    def test_a_declined_clause_does_not_swallow_the_rest(self) -> None:
        found = extract_constraints("I don't mind the colour, but cotton is required.")
        self.assertEqual(found, [("material", "cotton", Polarity.POSITIVE)])


class ASubordinatorEndsTheNegationScope(unittest.TestCase):
    """A negator in the main clause does not reach inside a subordinate one.

    Measured need, not hypothetical: generalising the negation rule above
    turned `public_0113` into a false exclusion, because the disclosure says
    the slippers "won't fly off when walking" and nothing punctuated the gap
    between "won't" and "walking". The negation is on "fly off".
    """

    def test_the_public_disclosure_that_regressed(self) -> None:
        message = (
            "For that, what matters is: CLOSED HEEL - These slippers hug your "
            "feet entirely so they won't fly off when walking, especially on "
            "stairs."
        )
        self.assertIs(_polarity(message, "walking"), Polarity.POSITIVE)

    def test_a_negation_before_a_subordinator_still_holds(self) -> None:
        self.assertIs(_polarity("I don't want black.", "black"), Polarity.NEGATIVE)

    def test_the_subordinate_clause_is_read_on_its_own(self) -> None:
        self.assertIs(_polarity("It won't slip when wet, and I want black.", "black"),
                      Polarity.POSITIVE)


if __name__ == "__main__":
    unittest.main()
