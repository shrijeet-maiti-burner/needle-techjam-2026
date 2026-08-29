from __future__ import annotations

import random
import unittest

from needle.semantic import normalize_text
from robustness.perturb import Meaning
from robustness.report import compare, gate_failures, summarize
from robustness.session import (
    BASELINE,
    SessionOutcome,
    SliceSpec,
    run_perturbed_session,
    run_slice,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #

class FakeSimulator:
    max_turns = 4
    top_k = 5

    def materialize_hidden_fields(self, sample, products):
        del products
        return dict(sample["intent_card"]), dict(sample.get("behavior", {}))

    def initial_message(self, sample, category, disclosed):
        hard = sample["intent_card"].get("hard_constraints", [])
        if sample["scenario_type"] == "buying" and hard:
            disclosed.add(hard[0])
            return f"I want {category}. A key requirement is: {hard[0]}."
        if sample["scenario_type"] == "intent_override":
            return f"I want {category}."
        return f"I want {category}, still exploring."

    def customer_reply(self, sample, ask_attribute, disclosed, boundary_used):
        if sample["scenario_type"] == "boundary" and not boundary_used and isinstance(ask_attribute, str):
            return f"I don't have a preference for {ask_attribute}; use your judgment.", True
        pool = [
            *sample["intent_card"].get("hard_constraints", []),
            *sample["intent_card"].get("soft_preferences", []),
        ]
        remaining = [value for value in pool if value not in disclosed][:1]
        if not remaining:
            return "Ask me about one specific attribute.", boundary_used
        disclosed.update(remaining)
        return "For that, what matters is: " + "; ".join(remaining) + ".", boundary_used

    def coarse_category(self, values):
        return " ".join(str(value) for value in list(values)[-2:]) or "item"

    def normalize_recommendations(self, payload, catalog_ids):
        if not isinstance(payload, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in payload:
            value = item.get("parent_asin") if isinstance(item, dict) else item
            value = str(value).strip()
            if value and value not in seen and value in catalog_ids:
                seen.add(value)
                result.append(value)
        return result[: self.top_k]


class SpyAgent:
    def __init__(self, **_):
        self.seen: list[tuple[int, str]] = []

    def reset(self, session_id, user_profile):
        del session_id, user_profile
        self.seen = []

    def respond(self, session_id, user_message, turn, top_k):
        del session_id, top_k
        self.seen.append((turn, user_message))
        return {
            "message": "ok",
            "ask_attribute": "material" if turn < 10 else None,
            "recommendations": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }


class KeywordAgent:
    """Recommends catalog ids sharing a token with the conversation so far.

    ``robust=True`` tokenises through the real ``needle.semantic.normalize_text``
    (case / accent / punctuation folding), so a meaning-preserving surface slice
    should not change its output. ``robust=False`` uses raw ``str.split``.
    """

    def __init__(self, catalog: dict[str, str], *, robust: bool = True, **_):
        self.catalog = catalog
        self.robust = robust
        self.history: list[str] = []

    def reset(self, session_id, user_profile):
        del session_id, user_profile
        self.history = []

    def _tokens(self, text: str) -> set[str]:
        return set((normalize_text(text) if self.robust else text).split())

    def respond(self, session_id, user_message, turn, top_k):
        del session_id, turn
        self.history.append(user_message)
        query = self._tokens(" ".join(self.history))
        scored = sorted(
            (
                (-len(query & self._tokens(text)), identifier)
                for identifier, text in self.catalog.items()
                if query & self._tokens(text)
            )
        )
        return {
            "message": "ok",
            "ask_attribute": None,
            "recommendations": [{"parent_asin": identifier} for _, identifier in scored[:top_k]],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }


def _sample(sid, scenario, target, hard, soft=(), override=None):
    data = {
        "sample_id": sid,
        "scenario_type": scenario,
        "user_profile": {},
        "ground_truth": {"parent_asin": target},
        "intent_card": {
            "target_category": "shirt",
            "hard_constraints": list(hard),
            "soft_preferences": list(soft),
        },
    }
    if override is not None:
        data["behavior"] = {"override": override}
    return data


COMMON = dict(catalog_ids=set(), categories={}, products={})


def _run(agent, sample, spec, *, catalog_ids, seed=0):
    return run_perturbed_session(
        agent,
        sample,
        catalog_ids=catalog_ids,
        categories={},
        products={},
        simulator=FakeSimulator(),
        spec=spec,
        rng=random.Random(seed),
    )


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

class DriverTest(unittest.TestCase):
    def test_baseline_hit_records_rank_and_recall(self) -> None:
        catalog = {"TARGET": "cotton shirt", "OTHER": "wool coat"}
        sample = _sample("s1", "buying", "TARGET", hard=["cotton"], soft=["soft"])
        outcome = _run(KeywordAgent(catalog), sample, BASELINE, catalog_ids=set(catalog))
        self.assertTrue(outcome.hit)
        self.assertEqual(outcome.first_hit_turn, 1)
        self.assertEqual(outcome.rank, 1)
        self.assertEqual(outcome.reciprocal_rank, 1.0)
        self.assertTrue(outcome.target_in_pool)

    def test_baseline_miss_is_scored_as_turn_eleven_equivalent(self) -> None:
        catalog = {"TARGET": "linen dress", "OTHER": "wool coat"}
        sample = _sample("s2", "buying", "TARGET", hard=["cotton"])
        outcome = _run(KeywordAgent(catalog), sample, BASELINE, catalog_ids=set(catalog))
        self.assertFalse(outcome.hit)
        self.assertIsNone(outcome.first_hit_turn)
        self.assertEqual(outcome.reciprocal_rank, 0.0)
        self.assertFalse(outcome.target_in_pool)

    def test_intent_override_cannot_convert_before_the_override_turn(self) -> None:
        catalog = {"TARGET": "cotton shirt"}
        override = {"turn": 3, "new_value": "cotton", "message": "Actually I need cotton."}
        sample = _sample("s3", "intent_override", "TARGET", hard=["silk"], soft=["a"], override=override)
        outcome = _run(KeywordAgent(catalog), sample, BASELINE, catalog_ids=set(catalog))
        # target text matches from turn 1, but the hit cannot be recorded until turn >= 3
        self.assertTrue(outcome.target_in_pool)
        self.assertIsNotNone(outcome.first_hit_turn)
        self.assertGreaterEqual(outcome.first_hit_turn, 3)


class SurfacePerturbationTest(unittest.TestCase):
    def _seen(self, spec: SliceSpec) -> list[str]:
        agent = SpyAgent()
        sample = _sample("s", "buying", "T", hard=["cotton fabric"], soft=["machine wash"])
        _run(agent, sample, spec, catalog_ids={"T"})
        return [message for _turn, message in agent.seen]

    def test_a_surface_slice_changes_what_the_agent_sees(self) -> None:
        baseline = self._seen(BASELINE)
        filled = self._seen(SliceSpec("filler", Meaning.PRESERVING, ("filler",)))
        self.assertNotEqual(baseline, filled)
        self.assertEqual(len(baseline), len(filled))

    def test_override_only_scope_leaves_pre_override_messages_untouched(self) -> None:
        override = {"turn": 3, "new_value": "wool", "message": "Actually, make it wool."}
        sample = _sample("s", "intent_override", "T", hard=["silk"], soft=["a"], override=override)
        spec = SliceSpec("op", Meaning.PRESERVING, ("politeness", "synonym"), surface_scope="override_only")

        base_agent, pert_agent = SpyAgent(), SpyAgent()
        _run(base_agent, sample, BASELINE, catalog_ids={"T"})
        _run(pert_agent, sample, spec, catalog_ids={"T"})

        self.assertEqual(base_agent.seen[0], pert_agent.seen[0])  # turn 1 identical
        self.assertNotEqual(base_agent.seen[2][1], pert_agent.seen[2][1])  # override turn changed


class CardEditTest(unittest.TestCase):
    def test_negation_edit_reaches_the_conversation(self) -> None:
        agent = SpyAgent()
        sample = _sample("s", "buying", "T", hard=["cotton"], soft=["lightweight"])
        outcome = _run(agent, sample, SliceSpec("neg", Meaning.CHANGING, card_edit="negate"), catalog_ids={"T"})
        transcript = " ".join(message for _turn, message in agent.seen).lower()
        self.assertTrue(outcome.changed)
        # one disclosed constraint (either the hard or the soft one) is now negated
        self.assertRegex(transcript, r"\b(?:not|no|non-?)\s*(?:cotton|lightweight)\b")

    def test_drop_soft_removes_a_preference_from_every_message(self) -> None:
        agent = SpyAgent()
        sample = _sample("s", "buying", "T", hard=["cotton"], soft=["waterproof", "breathable"])
        outcome = _run(agent, sample, SliceSpec("drop", Meaning.CHANGING, card_edit="drop_soft"), catalog_ids={"T"})
        transcript = " ".join(message for _turn, message in agent.seen)
        self.assertTrue(outcome.changed)
        dropped = [pref for pref in ("waterproof", "breathable") if pref not in transcript]
        self.assertEqual(len(dropped), 1)

    def test_a_normalising_agent_is_unaffected_by_token_preserving_slices(self) -> None:
        catalog = {"TARGET": "cotton machine wash shirt", "OTHER": "wool dry clean coat"}
        samples = [
            _sample("a", "buying", "TARGET", hard=["Cotton"], soft=["Machine Wash"]),
            _sample("b", "browsing", "TARGET", hard=["cotton"], soft=["machine wash"]),
        ]
        # slices whose output has the same normalised token multiset as the input
        for name in ("casing", "whitespace", "accents", "punctuation", "word_order"):
            spec = SliceSpec(name, Meaning.PRESERVING, (name,))
            for sample in samples:
                for seed in range(4):
                    base = _run(KeywordAgent(catalog), sample, BASELINE, catalog_ids=set(catalog), seed=seed)
                    pert = _run(KeywordAgent(catalog), sample, spec, catalog_ids=set(catalog), seed=seed)
                    with self.subTest(slice=name, sample=sample["sample_id"], seed=seed):
                        self.assertEqual(
                            (pert.hit, pert.first_hit_turn, pert.target_in_pool),
                            (base.hit, base.first_hit_turn, base.target_in_pool),
                        )


class RunSliceTest(unittest.TestCase):
    SAMPLES = [
        _sample("a", "buying", "T", hard=["cotton"], soft=["light"]),
        _sample("b", "browsing", "T", hard=["wool"], soft=["warm"]),
    ]

    def test_is_deterministic_for_a_given_seed(self) -> None:
        spec = SliceSpec("typo", Meaning.PRESERVING, ("typo",))
        first = run_slice(SpyAgent(), self.SAMPLES, spec, catalog_ids={"T"}, categories={}, products={}, simulator=FakeSimulator(), seed=7)
        second = run_slice(SpyAgent(), self.SAMPLES, spec, catalog_ids={"T"}, categories={}, products={}, simulator=FakeSimulator(), seed=7)
        self.assertEqual(first, second)

    def test_a_different_seed_changes_the_perturbation(self) -> None:
        spec = SliceSpec("filler", Meaning.PRESERVING, ("filler",))
        first = run_slice(SpyAgent(), self.SAMPLES, spec, catalog_ids={"T"}, categories={}, products={}, simulator=FakeSimulator(), seed=1)
        second = run_slice(SpyAgent(), self.SAMPLES, spec, catalog_ids={"T"}, categories={}, products={}, simulator=FakeSimulator(), seed=2)
        self.assertNotEqual(
            [o.perturbation_detail for o in first],
            [o.perturbation_detail for o in second],
        )


class SliceSpecValidationTest(unittest.TestCase):
    def test_card_edit_must_be_meaning_changing(self) -> None:
        with self.assertRaisesRegex(ValueError, "meaning_changing"):
            SliceSpec("x", Meaning.PRESERVING, card_edit="negate")

    def test_unknown_scope_and_edit_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "surface_scope"):
            SliceSpec("x", Meaning.PRESERVING, ("casing",), surface_scope="sometimes")
        with self.assertRaisesRegex(ValueError, "card_edit"):
            SliceSpec("x", Meaning.CHANGING, card_edit="mangle")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def _outcome(sid, slice_name, meaning, *, hit, turn=None, rank=None, in_pool=False, changed=True):
    return SessionOutcome(
        sample_id=sid,
        scenario_type="buying",
        slice=slice_name,
        meaning=meaning,
        hit=hit,
        first_hit_turn=turn,
        rank=rank,
        reciprocal_rank=0.0 if rank is None else 1.0 / rank,
        target_in_pool=in_pool,
        changed=changed,
    )


class ReportTest(unittest.TestCase):
    def test_metric_math_matches_the_official_definitions(self) -> None:
        outcomes = [
            _outcome("a", "exact_surface", Meaning.PRESERVING, hit=True, turn=2, rank=1, in_pool=True),
            _outcome("b", "exact_surface", Meaning.PRESERVING, hit=False, in_pool=True),
        ]
        metrics = summarize(outcomes)["exact_surface"]["overall"]
        self.assertEqual(metrics["hr_at_10"], 0.5)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertEqual(metrics["mttc"], (2 + 11) / 2)
        self.assertEqual(metrics["target_recall"], 1.0)

    def test_compare_reports_target_removal_over_changed_samples_only(self) -> None:
        baseline = [
            _outcome("a", "exact_surface", Meaning.PRESERVING, hit=True, turn=1, rank=1, in_pool=True),
            _outcome("b", "exact_surface", Meaning.PRESERVING, hit=True, turn=1, rank=1, in_pool=True),
        ]
        perturbed = [
            _outcome("a", "typo", Meaning.PRESERVING, hit=False, in_pool=False, changed=True),
            _outcome("b", "typo", Meaning.PRESERVING, hit=True, turn=1, rank=1, in_pool=True, changed=False),
        ]
        entry = compare(baseline, perturbed)["typo"]
        self.assertEqual(entry["effective_n"], 1)          # only "a" was changed
        self.assertEqual(entry["target_removal_rate"], 1.0)
        self.assertEqual(entry["delta"]["hr_at_10"], -0.5)

    def test_gate_failures_flags_removal_and_preserving_regression(self) -> None:
        comparison = {
            "typo": {
                "meaning": "meaning_preserving",
                "delta": {"hr_at_10": -0.1},
                "target_removal_rate": 0.2,
            },
            "negation": {
                "meaning": "meaning_changing",
                "delta": {"hr_at_10": 0.0, "mrr": 0.0, "mttc": 0.0, "target_recall": 0.0},
                "target_removal_rate": 0.0,
            },
        }
        failures = gate_failures(comparison)
        self.assertTrue(any("target_removal_rate" in message for message in failures))
        self.assertTrue(any("meaning-preserving HR@10 dropped" in message for message in failures))
        self.assertTrue(any("left every metric unchanged" in message for message in failures))

    def test_gate_failures_is_empty_for_a_clean_comparison(self) -> None:
        comparison = {
            "casing": {
                "meaning": "meaning_preserving",
                "delta": {"hr_at_10": 0.0, "mrr": 0.001, "mttc": -0.01, "target_recall": 0.0},
                "target_removal_rate": 0.0,
            }
        }
        self.assertEqual(gate_failures(comparison), [])


if __name__ == "__main__":
    unittest.main()
