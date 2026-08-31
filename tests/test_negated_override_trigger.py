"""A retraction verb under a negated auxiliary is not a retraction.

Red-team finding, human-state pass. `EXPLICIT_OVERRIDE_RE` matched the verb
without looking at what governed it, so "Don't forget that I need cotton"
fired a full override: `intent_version` bumped, every active constraint
superseded, message history cleared. The customer was holding a requirement in
place and the agent discarded the session for saying so.

The guard is deliberately narrow. It suppresses a trigger only when a negated
auxiliary sits within two words of it and inside the same clause, and
`_override_match` keeps scanning afterwards, so a message that contains both a
negated trigger and a real one still overrides.
"""

from __future__ import annotations

import unittest

from needle.state import Polarity, StateStore, _override_match


class NegatedTriggerIsNotAnOverride(unittest.TestCase):
    HELD = (
        "Don't forget that I need cotton.",
        "I can't forget the last pair I bought, they were great.",
        "Please do not forget my earlier preference.",
        "I won't forget what I said.",
    )

    def test_no_override_fires(self) -> None:
        for message in self.HELD:
            with self.subTest(message=message):
                self.assertIsNone(_override_match(message))

    def test_belief_survives_a_negated_trigger(self) -> None:
        store = StateStore(override_policy="retract_stated")
        store.reset("held", {})
        store.observe("held", "I am looking for boots. In leather.", 1)
        state = store.observe("held", "Don't forget that I need cotton.", 2)
        self.assertEqual(state.intent_version, 1, "a held requirement reset the session")
        self.assertIn(
            "I am looking for boots. In leather.",
            state.messages,
            "the opening message was cleared by a requirement the customer was holding",
        )
        values = {constraint.value for constraint in state.active_constraints()}
        self.assertIn("cotton", values, "the new requirement was not recorded")
        # "leather" is not asserted active here. It is superseded, but by the
        # ordinary same-attribute rule rather than by the override: a later
        # material replaces an earlier one. That is a separate decision from
        # the one under test, which is only that the session survived.


class RealOverridesStillFire(unittest.TestCase):
    """The guard must not cost a single genuine retraction."""

    RETRACTIONS = (
        "Never mind, forget what I said.",
        "Forget what I said, I need wool.",
        "I'm not sure, forget what I said.",
        "That's not right. Ignore my earlier preference.",
        "Changed my mind, I want canvas.",
        "Ignore that.",
        "I do not want leather; forget my earlier preference.",
    )

    def test_override_fires(self) -> None:
        for message in self.RETRACTIONS:
            with self.subTest(message=message):
                self.assertIsNotNone(_override_match(message))

    def test_a_held_requirement_does_not_mask_a_real_retraction(self) -> None:
        """Both in one message: the scan must not stop at the negated one."""
        message = "Don't forget the wool, but ignore my earlier preference on colour."
        self.assertIsNotNone(_override_match(message))


class NegatedTriggerDoesNotDisturbConstraints(unittest.TestCase):
    def test_values_in_a_held_requirement_stay_positive(self) -> None:
        store = StateStore()
        store.reset("held", {})
        state = store.observe("held", "Don't forget that I need cotton.", 1)
        found = {(c.attribute, c.value): c.polarity for c in state.active_constraints()}
        self.assertEqual(found.get(("material", "cotton")), Polarity.POSITIVE)


if __name__ == "__main__":
    unittest.main()
