"""Degenerate overrides: the retracted preference equals its replacement.

`intent_card` sets `soft_preferences = cleaned[2:4] or cleaned[:1]`, so when a
product yields fewer than three usable constraint strings the last soft
preference is the first hard constraint. `behavior_for` then draws
`old_value = soft[-1]` and `new_value = hard[0]` from that card, and the
customer retracts a preference by restating it.

No public session has this shape; 1.5% of the 50,000-product catalog does
(docs/evidence/EXP_006_SHAPES.md). These pin that `retract_stated` handles it
without dropping the value or leaving a stale duplicate, because the shape is
plausible on private and untested by the public set.
"""
from __future__ import annotations

import unittest

from needle.state import StateStore


VALUE = "soft cotton blend"
OVERRIDE = f"Actually, ignore my earlier preference. What I need is: {VALUE}."


class DegenerateOverrideTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = StateStore(override_policy="retract_stated")
        self.store.reset("degenerate", {})

    def _run(self) -> object:
        self.store.observe("degenerate", f"I'm looking for casual shirt. {VALUE}", 1)
        return self.store.observe("degenerate", OVERRIDE, 2)

    def test_the_value_survives_the_override_that_restates_it(self) -> None:
        # The opening preference clause is dropped, so the value must be
        # carried by the override message itself or it is lost entirely.
        self.assertIn(VALUE, self._run().retrieval_text)

    def test_the_subject_anchor_survives(self) -> None:
        self.assertIn("casual shirt", self._run().retrieval_text)

    def test_the_stated_preference_clause_is_still_retracted(self) -> None:
        # `retract_stated` must not keep the opening message intact just
        # because the replacement happens to match it.
        state = self._run()
        self.assertEqual(state.messages[0], "I'm looking for casual shirt.")
        self.assertEqual(len(state.messages), 2)

    def test_the_override_still_opens_a_new_intent_version(self) -> None:
        self.assertEqual(self._run().intent_version, 2)

    def test_the_restated_value_is_not_left_superseded(self) -> None:
        # Superseding every constraint at the override and then re-extracting
        # from the override message must leave the value active, not dropped.
        active = self._run().active_constraints()
        self.assertTrue(
            any(constraint.value in VALUE for constraint in active),
            f"no active constraint from {VALUE!r}: {[c.value for c in active]}",
        )


if __name__ == "__main__":
    unittest.main()
