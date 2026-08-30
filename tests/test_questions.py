"""Clarifying questions offer real choices, or none at all.

The value of asking "which colour: black, white, blue" instead of "what else
matters?" is entirely in the options being true of the products still in play.
An invented option, or a count of something other than what is on screen, is
worse than the open question it replaced.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.explain import message_for, turn_record  # noqa: E402
from needle.questions import clarifying_options  # noqa: E402

FACETS = {
    "a": ("leather", "black"),
    "b": ("leather", "brown"),
    "c": ("nylon", "black"),
    "d": ("canvas", ""),
    "e": ("nylon", "black"),
}
ALL = ["a", "b", "c", "d", "e"]


class SelectionTest(unittest.TestCase):
    def test_the_facet_that_splits_best_is_chosen(self) -> None:
        facet, options = clarifying_options(ALL, FACETS)
        # material splits 2/2/1; colour splits 3/1 with one unknown.
        self.assertEqual(facet, "material")
        self.assertEqual(options, (("leather", 2), ("nylon", 2), ("canvas", 1)))

    def test_a_facet_the_customer_already_spoke_to_is_skipped(self) -> None:
        facet, _ = clarifying_options(ALL, FACETS, already_said=["leather"])
        self.assertEqual(facet, "color")

    def test_a_facet_that_cannot_divide_anything_is_declined(self) -> None:
        uniform = {key: ("leather", "") for key in ALL}
        self.assertEqual(clarifying_options(ALL, uniform), ("", ()))

    def test_one_candidate_is_not_worth_a_question(self) -> None:
        self.assertEqual(clarifying_options(["a"], FACETS), ("", ()))

    def test_no_candidates_declines_rather_than_raising(self) -> None:
        self.assertEqual(clarifying_options([], FACETS), ("", ()))

    def test_unknown_products_are_never_offered_as_a_choice(self) -> None:
        # "d" has no colour. The empty string must not become an option.
        _, options = clarifying_options(ALL, FACETS, already_said=["leather"])
        self.assertTrue(all(value for value, _ in options))

    def test_counts_are_counts_of_the_candidates_given(self) -> None:
        _, options = clarifying_options(ALL, FACETS)
        self.assertEqual(sum(count for _, count in options), len(ALL))


class RenderingTest(unittest.TestCase):
    def _message(self, sampled: bool) -> str:
        record = turn_record(
            turn=2, category="belts", wanted=["leather"], unwanted=[],
            candidates=82, identified=False, emitted=["x"], withheld=True,
            sampled=sampled,
        )
        record["options"] = ("color", (("black", 7), ("white", 3)))
        return message_for(record, asking=True)

    def test_exact_counts_are_shown_when_the_set_was_counted_whole(self) -> None:
        self.assertIn("black (7)", self._message(sampled=False))

    def test_counts_are_withheld_when_the_set_was_sampled(self) -> None:
        """A count of 400 sampled products printed beside "1034 candidates"
        would be quoting a number of a different thing."""
        message = self._message(sampled=True)
        self.assertIn("black", message)
        self.assertNotIn("(7)", message)

    def test_the_customer_is_never_boxed_into_the_options(self) -> None:
        self.assertIn("anything else", self._message(sampled=False))

    def test_no_options_falls_back_to_the_open_question(self) -> None:
        record = turn_record(
            turn=2, category="belts", wanted=["leather"], unwanted=[],
            candidates=5, identified=False, emitted=["x"], withheld=True,
        )
        self.assertIn("What else matters?", message_for(record, asking=True))


if __name__ == "__main__":
    unittest.main()
