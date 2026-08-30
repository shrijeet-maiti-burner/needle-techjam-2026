import unittest

from needle.state import EXPLICIT_OVERRIDE_RE, PREFERENCE_OVERRIDE_RE


class OverrideTriggerRecall(unittest.TestCase):
    """Retraction is a rule about English, not a list of released templates.

    Phrasings written independently of the perturbation library, so this is a
    held-out check rather than a fit to our own generator.
    """

    OVERRIDES = (
        "Actually, ignore my earlier preference. What I need is: leather.",
        "Actually, please ignore my earlier preference.",
        "Forget what I said, I want something waterproof now.",
        "Disregard my previous requirement, go with wool.",
        "Scratch that, I need it in black.",
        "Scrap my earlier request. Show me boots.",
        "I've changed my mind, make it cotton.",
        "Never mind, let's look at something else.",
        "Let's start over. I need a winter coat.",
        "On second thought, I'd prefer leather.",
        "Change of plans, I need it for hiking.",
        "Cancel my last request and find me sandals.",
        "Undo that, I actually want the wool one.",
        "Ignore what I told you about the colour.",
        "Drop my earlier criteria, just show me anything cheap.",
    )

    def test_accented_override_is_detected_through_state_store(self) -> None:
        from needle.state import StateStore

        store = StateStore(override_policy="retract_stated")
        store.reset("accented", {})
        store.observe("accented", "I need a blue cotton shirt.", 1)
        state = store.observe(
            "accented",
            "Actuálly, ignôre my earlier preference. I need a red wool coat.",
            2,
        )

        self.assertEqual(state.intent_version, 2)

    def test_detects_every_retraction_phrasing(self):
        for message in self.OVERRIDES:
            with self.subTest(message=message):
                self.assertTrue(EXPLICIT_OVERRIDE_RE.search(message))

    def test_released_simulator_phrasings_still_detected(self):
        """The two strings the released evaluator can emit."""
        for message in (
            "Actually, ignore my earlier preference. What I need is: leather.",
            "Actually, please ignore my earlier preference.",
        ):
            self.assertTrue(EXPLICIT_OVERRIDE_RE.search(message))
            self.assertTrue(PREFERENCE_OVERRIDE_RE.search(message))


class OverrideTriggerPrecision(unittest.TestCase):
    """A false override is expensive: it bumps intent_version, clears the shown
    set, and discards belief. These must never fire."""

    NOT_OVERRIDES = (
        "I'm looking for running shoes. A key requirement is: leather.",
        "For that, what matters is: mesh upper; budget around $89.99.",
        "I don't have a preference for color; please use your judgment.",
        "Those options are not quite right yet. Ask me about one specific attribute.",
        "I'd prefer black instead of navy.",
        "Actually I think leather works well.",
        "No preference on size.",
        "I don't have an additional preference for material.",
        "I need something for hiking instead of the gym.",
        "Can you drop the price a bit?",
        "I'm still exploring, nothing decided.",
        "Actually, that second one looks good.",
    )

    def test_ordinary_dialogue_never_triggers(self):
        for message in self.NOT_OVERRIDES:
            with self.subTest(message=message):
                self.assertIsNone(EXPLICIT_OVERRIDE_RE.search(message))

    def test_bare_instead_is_not_a_trigger(self):
        """Regression: an earlier revision matched bare "instead", so ordinary
        corrections fired a full override."""
        self.assertIsNone(EXPLICIT_OVERRIDE_RE.search("I'd like the blue one instead."))

    def test_general_override_is_not_always_a_preference_retraction(self):
        """"start over" is an override but names no belief to retract, so it
        must not license keeping the earlier answers."""
        message = "Let's start over. I need a winter coat."
        self.assertTrue(EXPLICIT_OVERRIDE_RE.search(message))
        self.assertIsNone(PREFERENCE_OVERRIDE_RE.search(message))


if __name__ == "__main__":
    unittest.main()
