"""Budget is a price the customer stated, not any number with a comparator.

Red-team finding, human-state pass. Two separate defects sat in the same few
lines. The pattern read catalog measurements as price caps, and the selection
took the first figure in a message rather than the one left standing after a
correction.

The first defect was live on the public set: three sessions carried a budget
constraint taken from size text. Score did not move when it was removed (the
three sessions are byte-identical before and after), but an active constraint
is not inert. It is counted by the slate-width gate and it is read back to the
customer as a preference they never gave.
"""

from __future__ import annotations

import unittest

from needle.state import Polarity, extract_constraints


def _budget(message: str) -> str | None:
    stated = [value for attribute, value, _ in extract_constraints(message) if attribute == "budget"]
    return stated[0] if stated else None


class MeasurementsAreNotPrices(unittest.TestCase):
    """Exact disclosure text from the three public sessions that misfired."""

    NOT_A_BUDGET = (
        "Gold-tone 18mm stainless steel expansion band fits up to 8-inch wrist circumference",
        "Fit for different sizes,Fit bands up to 30mm wide ,6 replacement pins",
        "Size: <1>Big handbag:26*15*18cm/10.2\"*7\"*5.9\"(Length*Width*Height)",
    )

    def test_no_budget_is_extracted(self) -> None:
        for message in self.NOT_A_BUDGET:
            with self.subTest(message=message[:40]):
                self.assertIsNone(_budget(message))

    def test_a_unit_does_not_backtrack_into_a_shorter_number(self) -> None:
        """"30mm" must yield nothing, not a budget of 3.

        The guard rejects a trailing digit as well as a trailing letter for
        exactly this reason: without it the engine retreats to "3", finds "0"
        acceptable and reports a price the customer never named.
        """
        self.assertIsNone(_budget("Fit bands up to 30mm wide"))
        self.assertIsNone(_budget("fits up to 8-inch wrist"))


class RealBudgetsStillParse(unittest.TestCase):
    STATED = (
        ("under $50", "50"),
        ("under $50.", "50"),
        ("below $45,", "45"),
        ("up to 200", "200"),
        ("less than $19.99", "19.99"),
        ("at most 75 dollars", "75"),
        ("I want it under 50", "50"),
        ("budget $120.", "120"),
        ("<= 60", "60"),
    )

    def test_amount_is_extracted(self) -> None:
        for message, expected in self.STATED:
            with self.subTest(message=message):
                self.assertEqual(_budget(message), expected)


class TheLastStandingFigureWins(unittest.TestCase):
    def test_an_in_message_correction_is_honoured(self) -> None:
        self.assertEqual(_budget("Under $50. Actually, up to $200."), "200")

    def test_a_corrected_opening_figure_is_not_kept(self) -> None:
        self.assertEqual(_budget("Not under $50, more like $200."), "200")

    def test_a_negated_figure_does_not_win(self) -> None:
        self.assertEqual(_budget("Budget is $200, definitely not $50."), "200")

    def test_budget_is_never_negative(self) -> None:
        """There is one cap or none. An excluded price is not a constraint."""
        for _, _, polarity in extract_constraints("Not under $50, more like $200."):
            self.assertIs(polarity, Polarity.POSITIVE)

    def test_a_declined_budget_stays_declined(self) -> None:
        self.assertIsNone(_budget("No preference for budget, maybe $90."))


if __name__ == "__main__":
    unittest.main()
