"""The explanation layer says only what the turn's state supports, and costs nothing.

`message` is the one field of the response contract that nothing scores, and it
had been a constant since the first milestone. Filling it in is free score-wise
and is the difference between a transcript that reads like a product and one
that reads like a stub -- but only while two properties hold, which is what
these pin:

* it can never change what the agent recommends, and
* it can never forfeit a turn, because `local_evaluator.evaluate` replaces the
  entire response when `respond` raises.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.agent import Agent  # noqa: E402
from needle.evaluation import validate_response  # noqa: E402
from needle.explain import message_for, turn_record  # noqa: E402

CATALOG = ROOT / ".artifacts/participant-kit/techjam-conversational-search/data/catalog.jsonl"


def record(**overrides) -> dict:
    base = dict(
        turn=1, category="accessories belts", wanted=[], unwanted=[],
        candidates=None, identified=False, emitted=[], withheld=False,
    )
    base.update(overrides)
    return turn_record(**base)


class ClaimTest(unittest.TestCase):
    def test_a_single_candidate_is_stated_as_one(self) -> None:
        message = message_for(record(wanted=["leather"], candidates=1), asking=False)
        self.assertIn("One candidate", message)

    def test_a_count_is_never_attached_to_a_match_claim(self) -> None:
        # The bucket unions several plausible parses of the same clause, so it
        # is not keyed on the named values alone. "N match X" would overclaim;
        # the count and the evidence are two separate true statements.
        message = message_for(record(wanted=["leather"], candidates=23), asking=True)
        self.assertIn("23 candidates", message)
        self.assertNotIn("match", message)

    def test_nothing_disclosed_makes_no_claim_about_matches(self) -> None:
        message = message_for(record(candidates=None), asking=True)
        self.assertIn("Starting from", message)
        self.assertNotIn("candidates", message)

    def test_negated_values_are_reported_as_ruled_out(self) -> None:
        message = message_for(
            record(wanted=["leather"], unwanted=["suede"], candidates=4), asking=True
        )
        self.assertIn("ruled out", message)
        self.assertIn("suede", message)

    def test_long_value_lists_are_summarised_rather_than_recited(self) -> None:
        message = message_for(
            record(wanted=["a", "b", "c", "d", "e"], candidates=4), asking=True
        )
        self.assertIn("2 more", message)

    def test_a_malformed_record_still_yields_a_usable_sentence(self) -> None:
        for broken in ({}, {"category": None}, {"wanted": None, "candidates": "x"}):
            with self.subTest(broken=broken):
                message = message_for(broken, asking=True)
                self.assertIsInstance(message, str)
                self.assertTrue(message)


@unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
class IntegrationTest(unittest.TestCase):
    OPENING = "I'm looking for Accessories Belts, but I'm still exploring."
    REPLY = "For that, what matters is: leather; 100% Leather."

    def _agent(self, explain: bool) -> Agent:
        return Agent(
            CATALOG, retrieval_mode="signature_first", explain=explain,
            promote_disclosure_bucket=True, promote_opening_category=True,
            identify_from_disclosures=True, adaptive_slate=True,
            early_slate_size=1, full_slate_turn=5, full_slate_constraints=4,
            exclude_seen=True, popularity_strength=0.30, category_strength=1.00,
        )

    def test_explaining_never_changes_a_recommendation(self) -> None:
        """The whole safety case. If this can fail, the feature is not free."""
        outputs = []
        for explain in (False, True):
            with self._agent(explain) as agent:
                agent.reset("s", {})
                turns = []
                message = self.OPENING
                for turn in range(1, 6):
                    response = agent.respond("s", message, turn, 10)
                    turns.append([x["parent_asin"] for x in response["recommendations"]])
                    message = self.REPLY
                outputs.append(turns)
        self.assertEqual(outputs[0], outputs[1])

    def test_the_official_contract_still_validates(self) -> None:
        with self._agent(True) as agent:
            agent.reset("s", {})
            response = agent.respond("s", self.OPENING, 1, 10)
            catalog_ids = {item["parent_asin"] for item in response["recommendations"]}
            violations = validate_response(
                response, catalog_ids, session_id="s", turn=1
            )
            self.assertEqual(violations, [])

    def test_the_trace_is_recorded_per_turn_and_never_leaks_into_the_payload(self) -> None:
        with self._agent(True) as agent:
            agent.reset("s", {})
            response = agent.respond("s", self.OPENING, 1, 10)
            self.assertEqual(
                set(response), {"message", "ask_attribute", "recommendations", "usage"}
            )
            self.assertEqual(len(agent.explanations["s"]), 1)
            self.assertEqual(agent.explanations["s"][0]["turn"], 1)

    def test_the_trace_is_bounded(self) -> None:
        with self._agent(True) as agent:
            agent.explanation_history = 3
            for index in range(10):
                agent.reset(f"s{index}", {})
                agent.respond(f"s{index}", self.OPENING, 1, 10)
            self.assertLessEqual(len(agent.explanations), 3)

    def test_the_history_bound_is_validated(self) -> None:
        for value in (0, -1, 20_000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Agent(CATALOG, explanation_history=value)


if __name__ == "__main__":
    unittest.main()
