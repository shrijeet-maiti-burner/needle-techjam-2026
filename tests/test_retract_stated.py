import unittest

from needle.state import StateStore


OPENER = "I'm looking for running shoes. color: black"
REPLY1 = "For that, what matters is: mesh upper; budget around $89.99."
OVERRIDE = "Actually, ignore my earlier preference. What I need is: waterproof leather."


class RetractStatedSemantics(unittest.TestCase):
    """The customer retracts the preference they stated, not their answers."""

    def _run(self, policy):
        store = StateStore(policy)
        store.reset("s", {})
        store.observe("s", OPENER, 1)
        store.observe("s", REPLY1, 2)
        return store.observe("s", OVERRIDE, 3)

    def test_retracted_preference_is_dropped(self):
        text = self._run("retract_stated").retrieval_text.lower()
        self.assertNotIn("color: black", text)

    def test_answers_to_our_questions_survive(self):
        text = self._run("retract_stated").retrieval_text.lower()
        self.assertIn("mesh upper", text)
        self.assertIn("89.99", text)

    def test_answers_survive_when_the_subject_surface_is_unparseable(self):
        store = StateStore("retract_stated")
        store.reset("no-anchor", {})
        store.observe(
            "no-anchor",
            "I'm briefly looking for running shoes. color: black",
            1,
        )
        store.observe("no-anchor", REPLY1, 2)

        state = store.observe("no-anchor", OVERRIDE, 3)

        self.assertNotIn("color: black", state.retrieval_text.lower())
        self.assertIn("mesh upper", state.retrieval_text.lower())

    def test_shopping_subject_survives(self):
        text = self._run("retract_stated").retrieval_text.lower()
        self.assertIn("running shoes", text)

    def test_new_requirement_is_present(self):
        text = self._run("retract_stated").retrieval_text.lower()
        self.assertIn("waterproof leather", text)

    def test_intent_version_still_bumps(self):
        self.assertEqual(self._run("retract_stated").intent_version, 2)

    def test_no_reset_wrongly_keeps_the_retracted_value(self):
        """The contrast that makes no_reset semantically invalid."""
        self.assertIn("color: black", self._run("no_reset").retrieval_text.lower())

    def test_preserve_subject_discards_the_answers(self):
        """The cost preserve_subject pays."""
        text = self._run("preserve_subject").retrieval_text.lower()
        self.assertNotIn("mesh upper", text)


if __name__ == "__main__":
    unittest.main()
