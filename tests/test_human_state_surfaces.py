"""Red team follow-ups: verb sense, negation surface, and conjunction.

Each class covers one finding from `docs/evidence/REDTEAM_HUMAN_STATE.md` that
was recorded before it was fixed, so the inputs here are the exact ones that
failed.
"""

from __future__ import annotations

import unittest

from needle.state import Polarity, StateStore, _override_match, extract_constraints


def _active(messages: list[str], policy: str = "full_reset") -> list[tuple[str, str, str]]:
    store = StateStore(override_policy=policy)
    store.reset("probe", {})
    state = None
    for turn, message in enumerate(messages, 1):
        state = store.observe("probe", message, turn)
    assert state is not None
    return [(c.attribute, c.value, c.polarity.value) for c in state.active_constraints()]


class ARetractionVerbNeedsARetractionObject(unittest.TestCase):
    """A bare pronoun is only anaphoric when it ends the clause.

    "Cancel that shipping upgrade" uses "that" as a determiner and "Drop it in
    my basket" uses "it" as the object of a preposition. Both fired a full
    session reset.
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
        "I don't like black.",
        "I don't need leather.",
        "I dont like black.",
        "I never wear black.",
        "anything except black",
    )

    def test_value_is_excluded(self) -> None:
        for message in self.EXCLUDED:
            with self.subTest(message=message):
                polarities = [p for _, _, p in extract_constraints(message)]
                self.assertTrue(polarities, "nothing was extracted at all")
                self.assertIn(Polarity.NEGATIVE, polarities)


class IndifferenceIsNotAnExclusion(unittest.TestCase):
    """What makes the rule above safe to generalise.

    "I don't mind black" is neither a request for black nor a ban on it. It is
    the customer declining to constrain, so it belongs with the other
    no-preference phrasings and must yield nothing at all.
    """

    DECLINED = (
        "I don't mind black.",
        "I don't care about the colour.",
        "Either is fine.",
        "I'm not bothered about material.",
    )

    def test_nothing_is_extracted(self) -> None:
        for message in self.DECLINED:
            with self.subTest(message=message):
                self.assertEqual(extract_constraints(message), [])

    def test_a_declined_clause_does_not_swallow_the_rest(self) -> None:
        found = extract_constraints("I don't mind the colour, but cotton is required.")
        self.assertEqual(found, [("material", "cotton", Polarity.POSITIVE)])


class DisclosuresMergeInReadingOrder(unittest.TestCase):
    """`_find_values` walks the vocabulary longest phrase first, which leaves
    results in an order unrelated to what the customer said.

    A later positive replaces the earlier one, so that order decides which
    value survives a correction, and it was deciding it by phrase length. The
    two cases below are the same sentence with the materials swapped: before
    the sort, both kept "cotton", because "cotton" is the longer word.
    """

    def test_the_later_value_wins_whichever_word_is_longer(self) -> None:
        self.assertEqual(_active(["I want linen, actually cotton."]),
                         [("material", "cotton", "positive")])
        self.assertEqual(_active(["I want cotton, actually linen."]),
                         [("material", "linen", "positive")])

    def test_a_multiword_value_still_beats_its_own_substring(self) -> None:
        """Sorting by offset must not undo longest-match extraction."""
        self.assertEqual(_active(["A leather and stainless steel watch."]),
                         [("material", "stainless steel", "positive")])


if __name__ == "__main__":
    unittest.main()
