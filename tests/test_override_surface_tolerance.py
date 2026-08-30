"""The override trigger must survive surface corruption of its own keywords.

A missed override is expensive and asymmetric: `intent_version` never
increments, `retract_stated` never runs, the retracted preference keeps
ranking, and under the released evaluator the session cannot convert at all
because `override_applied` gates the hit check. Measured on the released
override message, the trigger missed 26/60 typo variants and 31/40 accent
variants before this.

A *false* override is worse still, so repair is deliberately one-sided: it only
runs when the raw message did not already trigger, and only rewrites a token
when exactly one keyword is one edit away.
"""

from __future__ import annotations

import random
import unittest

from needle.semantic import repair_trigger_text, trigger_keywords
from needle.state import (
    EXPLICIT_OVERRIDE_RE,
    PREFERENCE_OVERRIDE_RE,
    SessionState,
)
from robustness.perturb import apply

KEYWORDS = trigger_keywords(EXPLICIT_OVERRIDE_RE, PREFERENCE_OVERRIDE_RE)
OVERRIDE = "Actually, ignore my earlier preference. What I need is: white leather."


def _state() -> SessionState:
    return SessionState("s", {}, override_policy="retract_stated")


class KeywordExtractionTest(unittest.TestCase):
    def test_keywords_are_words_not_regex_artifacts(self) -> None:
        """`\bactually` in the pattern source must not yield "bactually",
        which is one edit from the real word and would map it to a token the
        pattern cannot match."""
        self.assertIn("actually", KEYWORDS)
        self.assertNotIn("bactually", KEYWORDS)
        for keyword in KEYWORDS:
            self.assertTrue(keyword.isalpha(), keyword)

    def test_keywords_track_the_patterns(self) -> None:
        import re as _re

        extra = _re.compile(r"\bplease\s+rewind\b")
        self.assertIn("rewind", trigger_keywords(extra))


class SurfaceToleranceTest(unittest.TestCase):
    def test_typo_in_a_trigger_word_still_overrides(self) -> None:
        for corrupted in (
            "Actually, ignroe my earlier preference. What I need is: white.",
            "Actually, ignore my earleir preference. What I need is: white.",
            "Actually, ignore my earlier prefernce. What I need is: white.",
        ):
            with self.subTest(message=corrupted):
                self.assertFalse(EXPLICIT_OVERRIDE_RE.search(corrupted))
                state = _state()
                state.observe("I want a black cotton shirt", 1)
                state.observe(corrupted, 2)
                self.assertEqual(state.intent_version, 2)

    def test_accented_trigger_word_still_overrides(self) -> None:
        corrupted = "Actually, ignóre my earlier preferencé. What I need is: white."
        state = _state()
        state.observe("I want a black cotton shirt", 1)
        state.observe(corrupted, 2)
        self.assertEqual(state.intent_version, 2)

    def test_survives_the_measured_perturbation_families(self) -> None:
        for kind in ("typo", "accents"):
            recovered = 0
            for seed in range(40):
                corrupted = apply(kind, OVERRIDE, random.Random(seed)).text
                state = _state()
                state.observe("I want a black cotton shirt", 1)
                state.observe(corrupted, 2)
                recovered += state.intent_version == 2
            with self.subTest(kind=kind):
                self.assertEqual(recovered, 40, f"{kind}: {40 - recovered} overrides missed")


class NoFalseOverrideTest(unittest.TestCase):
    """Repair must never invent an override out of ordinary shopping text."""

    ORDINARY = (
        "I'm looking for running shoes, but I'm still exploring.",
        "For that, what matters is: Cloudsoft cotton.",
        "For that, what matters is: Water Resistant; budget around $29.99.",
        "I don't have a preference for color; please use your judgment.",
        "I need a black cotton shirt in medium",
        "I want something with a leather strap and a metal buckle.",
        "blue instead of black",
        "I prefer the last one you showed me.",
    )

    def test_ordinary_messages_never_trigger(self) -> None:
        for message in self.ORDINARY:
            with self.subTest(message=message):
                state = _state()
                state.observe(message, 1)
                self.assertEqual(state.intent_version, 1)

    def test_ordinary_messages_never_trigger_under_perturbation(self) -> None:
        for message in self.ORDINARY:
            for kind in ("typo", "accents", "filler", "word_order"):
                for seed in range(6):
                    corrupted = apply(kind, message, random.Random(seed)).text
                    with self.subTest(message=message[:26], kind=kind, seed=seed):
                        state = _state()
                        state.observe(corrupted, 1)
                        self.assertEqual(state.intent_version, 1)

    def test_repair_is_only_consulted_when_the_raw_message_misses(self) -> None:
        """A message that already triggers is never repaired, so a clean
        override cannot change meaning on its way through."""
        state = _state()
        state.observe(OVERRIDE, 1)
        self.assertEqual(state.intent_version, 2)

    def test_ambiguous_corruption_is_left_alone(self) -> None:
        """Repair requires a unique keyword at distance one."""
        self.assertEqual(repair_trigger_text("xxxx", KEYWORDS), "xxxx")

    def test_repair_does_not_alter_a_message_with_no_near_keywords(self) -> None:
        text = "waterproof leather hiking boots size medium"
        self.assertEqual(repair_trigger_text(text, KEYWORDS), text)


class OffsetSafetyTest(unittest.TestCase):
    """Repair changes offsets, so anything span-based must keep the raw text."""

    def test_no_preference_clause_still_scoped_correctly(self) -> None:
        state = _state()
        state.observe("i have no preference for color, but cotton is required", 1)
        self.assertEqual(state.excluded_values("color"), ())
        actives = {c.attribute: c.value for c in state.active_constraints()}
        self.assertEqual(actives.get("material"), "cotton")

    def test_subject_anchor_survives_an_override(self) -> None:
        state = _state()
        state.observe("I'm looking for running shoes. I want black leather.", 1)
        state.observe("Actually, ignore my earlier preference. I need white.", 2)
        self.assertEqual(state.intent_version, 2)
        self.assertIn("running shoes", " ".join(state.messages).lower())


if __name__ == "__main__":
    unittest.main()
