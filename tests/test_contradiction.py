import unittest

from needle.state import Polarity, StateStore


def run(messages, policy="retract_stated"):
    store = StateStore(policy)
    store.reset("x", {})
    state = None
    for turn, message in enumerate(messages, 1):
        state = store.observe("x", message, turn)
    return state


class ContradictionInvalidation(unittest.TestCase):
    """A value and its own exclusion must never be active at the same time."""

    def test_negation_retracts_the_earlier_positive(self):
        state = run([
            "I'm looking for a jacket. I want leather.",
            "Actually no leather, I don't want leather at all.",
        ])
        active = [(c.value, c.polarity) for c in state.active_constraints()]
        self.assertEqual(active, [("leather", Polarity.NEGATIVE)])

    def test_negated_value_is_excluded(self):
        state = run([
            "I'm looking for a jacket. I want leather.",
            "Actually no leather, I don't want leather at all.",
        ])
        self.assertEqual(state.excluded_values("material"), ("leather",))

    def test_restating_a_positive_reinstates_it(self):
        state = run(["No black please.", "Actually black is fine, I want black."])
        active = [(c.value, c.polarity) for c in state.active_constraints()]
        self.assertEqual(active, [("black", Polarity.POSITIVE)])
        self.assertEqual(state.excluded_values("color"), ())

    def test_independent_exclusions_still_accumulate(self):
        state = run(["I want a black bag.", "No black please.", "Not red either."])
        self.assertEqual(sorted(state.excluded_values("color")), ["black", "red"])

    def test_contradiction_supersedes_rather_than_deletes(self):
        """Audit trail is preserved: the retracted belief stays as history."""
        state = run([
            "I'm looking for a jacket. I want leather.",
            "Actually no leather, I don't want leather at all.",
        ])
        self.assertEqual(len(state.constraints), 2)
        superseded = [c for c in state.constraints if c not in state.active_constraints()]
        self.assertEqual([c.polarity for c in superseded], [Polarity.POSITIVE])


if __name__ == "__main__":
    unittest.main()
