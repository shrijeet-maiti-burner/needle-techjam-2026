from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from needle.agent import Agent


PRODUCTS = (
    {
        "parent_asin": "A1",
        "title": "Black Cotton Running Shirt",
        "features": ["cotton", "color: black", "lightweight running top"],
        "description": ["soft everyday athletic shirt"],
        "price": 20.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts", "T-Shirts"],
        "details": {"Department": "mens"},
        "average_rating": 4.7,
        "rating_number": 100,
        "store": "Alpha",
    },
    {
        "parent_asin": "A2",
        "title": "Blue Cotton Running Shirt",
        "features": ["cotton", "color: blue", "breathable running top"],
        "description": ["soft athletic shirt"],
        "price": 22.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts", "T-Shirts"],
        "details": {"Department": "mens"},
        "average_rating": 4.5,
        "rating_number": 80,
        "store": "Beta",
    },
    {
        "parent_asin": "A3",
        "title": "Red Wool Winter Shirt",
        "features": ["wool", "color: red", "warm winter layer"],
        "description": ["cold weather shirt"],
        "price": 35.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts", "T-Shirts"],
        "details": {"Department": "mens"},
        "average_rating": 4.4,
        "rating_number": 30,
        "store": "Gamma",
    },
)


class LensTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.catalog = Path(self.temporary.name) / "catalog.jsonl"
        self.catalog.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS),
            encoding="utf-8",
        )
        self.kwargs = {
            "retrieval_mode": "signature_first",
            "promote_disclosure_bucket": True,
            "promote_opening_category": True,
            "identify_from_disclosures": True,
            "adaptive_slate": True,
            "early_slate_size": 1,
            "exclude_seen": True,
            "override_policy": "retract_stated",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_enabling_trace_cannot_change_the_scored_response(self) -> None:
        plain = Agent(self.catalog, **self.kwargs)
        traced = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            for agent in (plain, traced):
                agent.reset("session", {})
            message = "I'm looking for Shirts T-Shirts, but I'm still exploring."
            self.assertEqual(
                plain.respond("session", message, 1, 10),
                traced.respond("session", message, 1, 10),
            )
            trace = traced.trace_for("session")
            self.assertEqual(len(trace), 1)
            self.assertTrue(trace[0]["target_blind"])
            self.assertEqual(trace[0]["decision"]["recommendations"], ["A1"])
        finally:
            plain.close()
            traced.close()

    def test_trace_contains_no_ground_truth_or_target_identifier_key(self) -> None:
        agent = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            agent.reset("session", {})
            agent.respond(
                "session",
                "I'm looking for Shirts T-Shirts. A key requirement is: cotton.",
                1,
                10,
            )
            payload = json.dumps(agent.trace_for("session"), sort_keys=True)
            self.assertNotIn("ground_truth", payload)
            self.assertNotIn("target_parent_asin", payload)
            self.assertIn('"target_blind": true', payload)
        finally:
            agent.close()

    def test_trace_certifies_the_grounded_message_returned_on_that_turn(self) -> None:
        agent = Agent(
            self.catalog,
            **self.kwargs,
            explain=True,
            trace_enabled=True,
        )
        try:
            agent.reset("session", {})
            response = agent.respond(
                "session",
                "I'm looking for Shirts T-Shirts, but I'm still exploring.",
                1,
                10,
            )
            trace = agent.trace_for("session")[-1]
            self.assertEqual(trace["response"]["message"], response["message"])
            self.assertEqual(
                trace["response"]["ask_attribute"],
                response["ask_attribute"],
            )
            self.assertNotEqual(
                response["message"],
                "What else matters most for the item you want?",
            )
        finally:
            agent.close()

    def test_override_is_visible_as_a_versioned_state_transition(self) -> None:
        agent = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            agent.reset("session", {})
            agent.respond("session", "I'm looking for Shirts T-Shirts. black.", 1, 10)
            agent.respond(
                "session",
                "Actually, ignore my earlier preference. What I need is: cotton.",
                2,
                10,
            )
            trace = agent.trace_for("session")[-1]
            self.assertEqual(trace["intent_version"], 2)
            events = trace["belief_ledger"]["events"]
            self.assertTrue(
                any(event["value"] == "black" and event["status"] == "superseded" for event in events)
            )
            self.assertTrue(
                any(event["value"] == "cotton" and event["status"] == "active" for event in events)
            )
        finally:
            agent.close()

    def test_interpretation_and_funnel_counts_are_catalog_derived(self) -> None:
        agent = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            agent.reset("session", {})
            agent.respond(
                "session",
                "I'm looking for Shirts T-Shirts. A key requirement is: cotton.",
                1,
                10,
            )
            trace = agent.trace_for("session")[-1]
            self.assertEqual(trace["interpretation_lattice"]["union_count"], 2)
            funnel = {item["stage"]: item["count"] for item in trace["candidate_funnel"]}
            self.assertEqual(funnel["frozen_catalog"], 3)
            self.assertEqual(funnel["evidence_safe_union"], 2)
            self.assertEqual(funnel["emitted_slate"], 1)
            evidence = trace["recommendation_evidence"][0]
            self.assertEqual(evidence["parent_asin"], "A1")
            self.assertEqual(evidence["rating_number"], 100)
        finally:
            agent.close()

    def test_human_question_board_is_bounded_and_explicitly_shadow_only(self) -> None:
        agent = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            agent.reset("session", {})
            agent.respond("session", "I'm looking for Shirts T-Shirts, but I'm still exploring.", 1, 10)
            question = agent.trace_for("session")[-1]["question_policy"]
            self.assertTrue(question["human_shadow_only"])
            self.assertEqual(question["scored_policy"], "other")
            self.assertTrue(question["human_shadow_board"])
            for row in question["human_shadow_board"]:
                self.assertGreaterEqual(row["catalog_coverage"], 0.0)
                self.assertLessEqual(row["catalog_coverage"], 1.0)
                self.assertGreaterEqual(row["expected_candidate_reduction"], 0.0)
                self.assertLessEqual(row["expected_candidate_reduction"], 1.0)
                self.assertTrue(row["presupposition_safe"])
        finally:
            agent.close()

    def test_reset_clears_prior_trace(self) -> None:
        agent = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            agent.reset("session", {})
            agent.respond("session", "I'm looking for Shirts T-Shirts, but I'm still exploring.", 1, 10)
            self.assertEqual(len(agent.trace_for("session")), 1)
            agent.reset("session", {})
            self.assertEqual(agent.trace_for("session"), ())
        finally:
            agent.close()

    def test_trace_failure_cannot_degrade_the_scored_response(self) -> None:
        plain = Agent(self.catalog, **self.kwargs)
        traced = Agent(self.catalog, **self.kwargs, trace_enabled=True)
        try:
            for agent in (plain, traced):
                agent.reset("session", {})
            message = "I'm looking for Shirts T-Shirts, but I'm still exploring."
            expected = plain.respond("session", message, 1, 10)
            with patch("needle.lens.build_turn_trace", side_effect=RuntimeError("trace broke")):
                actual = traced.respond("session", message, 1, 10)
            self.assertEqual(actual, expected)
            self.assertEqual(traced.respond_failures, [])
            self.assertIn("RuntimeError: trace broke", traced.trace_for("session")[0]["trace_error"])
        finally:
            plain.close()
            traced.close()


if __name__ == "__main__":
    unittest.main()
