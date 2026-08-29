from __future__ import annotations

import unittest

from needle.state import (
    ConstraintStatus, Polarity, SessionState, StateStore, extract_constraints,
)


def _state(session_id: str = "s") -> SessionState:
    return SessionState(session_id, {})


def _active_map(state: SessionState) -> dict[str, str]:
    return {
        constraint.attribute: constraint.value
        for constraint in state.active_constraints()
        if constraint.polarity is Polarity.POSITIVE
    }


class ExtractionTest(unittest.TestCase):
    def test_extracts_material_and_color(self) -> None:
        found = extract_constraints("I need a black cotton shirt")
        self.assertIn(("material", "cotton", Polarity.POSITIVE), found)
        self.assertIn(("color", "black", Polarity.POSITIVE), found)

    def test_extracts_budget_amount(self) -> None:
        found = extract_constraints("something under $80")
        self.assertIn(("budget", "80", Polarity.POSITIVE), found)

    def test_prefers_longest_vocabulary_match(self) -> None:
        found = extract_constraints("a stainless steel bracelet")
        materials = [value for attribute, value, _ in found if attribute == "material"]
        self.assertIn("stainless steel", materials)

    def test_negation_directly_before_value_produces_exclusion(self) -> None:
        found = extract_constraints("not leather please")
        self.assertIn(("material", "leather", Polarity.NEGATIVE), found)

    def test_distant_negation_does_not_create_exclusion(self) -> None:
        # "no" is far from "cotton"; a loose window would wrongly exclude the
        # customer's actual requirement.
        message = "no rush on delivery, I would really like a soft cotton shirt"
        found = extract_constraints(message)
        self.assertIn(("material", "cotton", Polarity.POSITIVE), found)


class BoundaryTest(unittest.TestCase):
    """The released Boundary reply must never become a hard filter."""

    def test_no_preference_reply_creates_no_constraint(self) -> None:
        message = "I don't have a preference for color; please use your judgment."
        self.assertEqual(extract_constraints(message), [])

    def test_no_preference_reply_does_not_negate_a_named_value(self) -> None:
        # Even when a value word appears, a no-preference turn must stay inert.
        self.assertEqual(extract_constraints("I have no preference for black"), [])

    def test_no_preference_turn_leaves_earlier_beliefs_untouched(self) -> None:
        state = _state()
        state.observe("I want a cotton shirt", 1)
        state.observe("I don't have an additional preference for color.", 2)
        self.assertEqual(_active_map(state).get("material"), "cotton")
        self.assertEqual(state.excluded_values("color"), ())


class CorrectionTest(unittest.TestCase):
    def test_new_value_supersedes_previous_value_of_same_attribute(self) -> None:
        state = _state()
        state.observe("I want a black shirt", 1)
        state.observe("make it blue", 2)

        self.assertEqual(_active_map(state).get("color"), "blue")
        superseded = [
            constraint for constraint in state.constraints
            if constraint.status is ConstraintStatus.SUPERSEDED
        ]
        self.assertEqual([c.value for c in superseded], ["black"])

    def test_restating_the_same_value_does_not_duplicate(self) -> None:
        state = _state()
        state.observe("I want a cotton shirt", 1)
        state.observe("cotton is important to me", 2)
        material = [c for c in state.active_constraints() if c.attribute == "material"]
        self.assertEqual(len(material), 1)

    def test_correction_keeps_the_same_intent_version(self) -> None:
        state = _state()
        state.observe("I want a black shirt", 1)
        state.observe("make it blue", 2)
        self.assertEqual(state.intent_version, 1)

    def test_supersession_records_its_predecessor(self) -> None:
        state = _state()
        state.observe("I want a black shirt", 1)
        state.observe("make it blue", 2)
        blue = next(c for c in state.active_constraints() if c.value == "blue")
        self.assertEqual(blue.supersedes, "color:black:positive")


class NegationTest(unittest.TestCase):
    def test_exclusions_accumulate_rather_than_superseding(self) -> None:
        state = _state()
        state.observe("not black", 1)
        state.observe("not red either", 2)
        self.assertEqual(set(state.excluded_values("color")), {"black", "red"})

    def test_exclusions_are_not_recorded_as_positive_beliefs(self) -> None:
        # Guards the invariant that matters once EXP-006 lets constraints
        # survive into retrieval: an excluded value must never be treated as
        # something the customer wants.
        state = _state()
        state.observe("I want a shirt, not leather", 1)
        positives = [
            c.value for c in state.active_constraints()
            if c.polarity is Polarity.POSITIVE
        ]
        self.assertNotIn("leather", positives)
        self.assertIn("leather", state.excluded_values("material"))


class OverrideTest(unittest.TestCase):
    def test_override_increments_intent_version(self) -> None:
        state = _state()
        state.observe("I want black running shoes", 1)
        state.observe("Actually, ignore my earlier preference. I need white sneakers.", 2)
        self.assertEqual(state.intent_version, 2)

    def test_override_supersedes_every_prior_constraint(self) -> None:
        state = _state()
        state.observe("I want black cotton clothing", 1)
        state.observe("Actually, ignore my earlier preference. I need white wool.", 2)

        active = _active_map(state)
        self.assertEqual(active.get("color"), "white")
        self.assertEqual(active.get("material"), "wool")
        self.assertNotIn("black", active.values())
        self.assertNotIn("cotton", active.values())

    def test_override_preserves_the_event_log(self) -> None:
        # Superseded records are retained for replay and diagnostics rather
        # than deleted, even though the message history is cleared.
        state = _state()
        state.observe("I want a black shirt", 1)
        state.observe("Actually, ignore my earlier preference. I need white.", 2)
        superseded = [
            c for c in state.constraints if c.status is ConstraintStatus.SUPERSEDED
        ]
        self.assertTrue(any(c.value == "black" for c in superseded))

    def test_pre_override_constraints_are_excluded_from_active_view(self) -> None:
        state = _state()
        state.observe("I want a black shirt", 1)
        state.observe("Actually, ignore my earlier preference. I need white.", 2)
        self.assertTrue(
            all(c.intent_version == 2 for c in state.active_constraints())
        )

    def test_ordinary_correction_is_not_treated_as_an_override(self) -> None:
        # "instead" alone is ordinary correction language. Treating it as a
        # full override would wrongly discard every unrelated constraint.
        state = _state()
        state.observe("I want a black cotton shirt", 1)
        state.observe("blue instead of black", 2)
        self.assertEqual(state.intent_version, 1)
        self.assertEqual(_active_map(state).get("material"), "cotton")


class LifecycleTest(unittest.TestCase):
    def test_reset_isolates_sessions(self) -> None:
        store = StateStore()
        store.reset("a", {})
        store.reset("b", {})
        store.observe("a", "I want cotton", 1)
        self.assertEqual(store._sessions["b"].active_constraints(), ())

    def test_observe_requires_reset(self) -> None:
        store = StateStore()
        with self.assertRaisesRegex(RuntimeError, "reset must be called"):
            store.observe("missing", "cotton", 1)

    def test_reset_rejects_empty_session_id(self) -> None:
        store = StateStore()
        with self.assertRaisesRegex(ValueError, "session_id"):
            store.reset("", {})

    def test_turn_must_increase(self) -> None:
        state = _state()
        state.observe("cotton", 2)
        with self.assertRaisesRegex(ValueError, "must increase"):
            state.observe("wool", 2)

    def test_turn_bounds_are_enforced(self) -> None:
        state = _state()
        with self.assertRaisesRegex(ValueError, "turn must be in 1..10"):
            state.observe("cotton", 11)

    def test_retrieval_text_carries_current_version_only(self) -> None:
        state = _state()
        state.observe("I want a black shirt", 1)
        state.observe("Actually, ignore my earlier preference. I need a red coat.", 2)
        self.assertNotIn("black", state.retrieval_text)
        self.assertIn("red", state.retrieval_text)

    def test_user_profile_is_copied_not_aliased(self) -> None:
        store = StateStore()
        profile = {"preference_tags": ["fit"]}
        store.reset("p", profile)
        profile["preference_tags"] = ["mutated"]
        self.assertEqual(
            store._sessions["p"].user_profile["preference_tags"], ["fit"]
        )


if __name__ == "__main__":
    unittest.main()
