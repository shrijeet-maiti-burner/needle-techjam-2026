from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.agent import Agent
from needle.contracts import ALLOWED_ASK_ATTRIBUTES


PRODUCTS = (
    {
        "parent_asin": "BLACK_SHIRT",
        "title": "Black cotton shirt",
        "categories": ["Clothing", "Shirts"],
        "features": ["soft cotton"],
        "details": {"Color": "Black"},
        "store": "Example",
        "description": "casual button shirt",
    },
    {
        "parent_asin": "RED_COAT",
        "title": "Red wool coat",
        "categories": ["Clothing", "Coats"],
        "features": ["warm wool"],
        "details": {"Color": "Red"},
        "store": "Example",
        "description": "winter outerwear",
    },
    {
        "parent_asin": "BLACK_SHIRT_2",
        "title": "Black cotton shirt",
        "categories": ["Clothing", "Shirts"],
        "features": ["cotton blend"],
        "details": {"Color": "Black"},
        "store": "Second Example",
        "description": "casual shirt",
    },
    {
        "parent_asin": "BLACK_SHIRT_3",
        "title": "Black cotton shirt",
        "categories": ["Clothing", "Shirts"],
        "features": ["cotton blend"],
        "details": {"Color": "Black"},
        "store": "Third Example",
        "description": "casual shirt",
    },
    {
        "parent_asin": "BLUE_SHOES",
        "title": "Blue running shoes",
        "categories": ["Shoes", "Running"],
        "features": ["lightweight"],
        "details": {"Color": "Blue"},
        "store": "Example",
        "description": "road running trainer",
    },
)


class AgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.temporary.name) / "catalog.jsonl"
        self.catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS),
            encoding="utf-8",
        )
        self.agent = Agent(self.catalog_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_response_is_strict_and_catalog_grounded(self) -> None:
        self.agent.reset("session", {})
        response = self.agent.respond("session", "I need a black cotton shirt", 1, 10)

        self.assertEqual(
            set(response),
            {"message", "ask_attribute", "recommendations", "usage"},
        )
        self.assertIn(response["ask_attribute"], ALLOWED_ASK_ATTRIBUTES)
        self.assertLessEqual(len(response["recommendations"]), 10)
        self.assertEqual(response["recommendations"][0]["parent_asin"], "BLACK_SHIRT")
        self.assertEqual(response["usage"], {"prompt_tokens": 0, "completion_tokens": 0})

    def test_reset_is_required_by_the_state_store(self) -> None:
        """The invariant still holds where it is owned. `Agent.respond` no
        longer propagates it; see `test_respond_never_raises` for why."""
        with self.assertRaisesRegex(RuntimeError, "reset must be called"):
            self.agent.state.observe("missing", "black shirt", 1)

    def test_explicit_override_starts_a_new_intent_version(self) -> None:
        self.agent.reset("override", {})
        self.agent.respond("override", "I need a black cotton shirt", 1, 10)
        response = self.agent.respond(
            "override",
            "Actually, ignore my earlier preference. I need a red wool coat.",
            2,
            10,
        )

        self.assertEqual(response["recommendations"][0]["parent_asin"], "RED_COAT")
        self.assertEqual(self.agent.state._sessions["override"].intent_version, 2)

    def test_top_k_is_bounded_by_strict_contract(self) -> None:
        self.agent.reset("bounded", {})
        response = self.agent.respond("bounded", "clothing shoes", 1, 100)
        self.assertLessEqual(len(response["recommendations"]), 10)

    def test_fixed_slate_size_is_respected(self) -> None:
        agent = Agent(self.catalog_path, slate_size=1)
        agent.reset("single", {})

        response = agent.respond("single", "black cotton shirt", 1, 10)

        self.assertEqual(len(response["recommendations"]), 1)

    def test_adaptive_slate_marks_only_emitted_products_seen(self) -> None:
        agent = Agent(
            self.catalog_path,
            retrieval_mode="signature_first",
            adaptive_slate=True,
            early_slate_size=1,
            full_slate_turn=5,
            exclude_seen=True,
        )
        agent.reset("adaptive", {})

        response = agent.respond("adaptive", "I'm looking for clothing.", 1, 10)

        self.assertEqual(len(response["recommendations"]), 1)
        self.assertEqual(len(agent._seen_by_version[("adaptive", 1)]), 1)

    def test_intent_override_keeps_the_early_slate_when_text_order_is_stable(self) -> None:
        agent = Agent(
            self.catalog_path,
            retrieval_mode="signature_first",
            adaptive_slate=True,
            early_slate_size=1,
            full_slate_turn=5,
            exclude_seen=True,
        )
        agent.reset("override-slate", {})
        agent.respond(
            "override-slate",
            "I'm looking for coats. A key requirement is: wool.",
            1,
            10,
        )

        response = agent.respond(
            "override-slate",
            "Actually, ignore my earlier preference. I'm looking for shirts.",
            2,
            10,
        )

        self.assertEqual(agent.state._sessions["override-slate"].intent_version, 2)
        self.assertEqual(len(response["recommendations"]), 1)

    def test_unique_disclosure_identification_emits_only_the_target(self) -> None:
        agent = Agent(
            self.catalog_path,
            retrieval_mode="signature_first",
            identify_from_disclosures=True,
            adaptive_slate=True,
            exclude_seen=True,
        )
        agent.reset("identified", {})
        agent.respond(
            "identified",
            "I'm looking for shirts. A key requirement is: cotton.",
            1,
            10,
        )

        response = agent.respond(
            "identified",
            "For that, what matters is: color: black; soft cotton.",
            2,
            10,
        )

        self.assertEqual(response["recommendations"], [{"parent_asin": "BLACK_SHIRT"}])

    def test_prefix_promotion_walks_unseen_members_by_popularity(self) -> None:
        path = Path(self.temporary.name) / "promotion.jsonl"
        products = [
            {
                "parent_asin": "LOW",
                "title": "cotton shirt",
                "categories": ["Clothing", "Shirts"],
                "features": ["cotton weave"],
                "rating_number": 5,
            },
            {
                "parent_asin": "HIGH",
                "title": "cotton shirt",
                "categories": ["Clothing", "Shirts"],
                "features": ["cotton weave"],
                "rating_number": 500,
            },
        ]
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        agent = Agent(
            path,
            retrieval_mode="signature_first",
            promote_disclosure_bucket=True,
            adaptive_slate=True,
            early_slate_size=1,
            exclude_seen=True,
        )
        agent.reset("promoted", {})

        first = agent.respond(
            "promoted",
            "I'm looking for shirts. A key requirement is: cotton.",
            1,
            10,
        )
        second = agent.respond(
            "promoted",
            "I don't have an additional preference for other.",
            2,
            10,
        )

        self.assertEqual(first["recommendations"], [{"parent_asin": "HIGH"}])
        self.assertEqual(second["recommendations"], [{"parent_asin": "LOW"}])

    def test_sequential_policy_does_not_repeat_candidates(self) -> None:
        agent = Agent(self.catalog_path, slate_size=1, exclude_seen=True)
        agent.reset("sequential", {})

        first = agent.respond("sequential", "black cotton shirt", 1, 10)
        second = agent.respond("sequential", "same requirements", 2, 10)
        third = agent.respond("sequential", "same requirements", 3, 10)
        identifiers = [
            first["recommendations"][0]["parent_asin"],
            second["recommendations"][0]["parent_asin"],
            third["recommendations"][0]["parent_asin"],
        ]

        self.assertEqual(len(set(identifiers)), 3)

    def test_reset_clears_sequential_history(self) -> None:
        agent = Agent(self.catalog_path, slate_size=1, exclude_seen=True)
        agent.reset("reused", {})
        first = agent.respond("reused", "black cotton shirt", 1, 10)
        agent.reset("reused", {})

        restarted = agent.respond("reused", "black cotton shirt", 1, 10)

        self.assertEqual(restarted["recommendations"], first["recommendations"])

    def test_rejects_unknown_lexical_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "lexical mode"):
            Agent(self.catalog_path, lexical_mode="unknown")

    def test_expansion_adds_retrieval_terms_without_rewriting_state(self) -> None:
        agent = Agent(self.catalog_path, lexical_mode="expand")
        agent.reset("expanded", {})

        response = agent.respond("expanded", "sneakers", 1, 10)

        self.assertEqual(response["recommendations"][0]["parent_asin"], "BLUE_SHOES")
        self.assertEqual(agent.state._sessions["expanded"].retrieval_text, "sneakers")

    def test_exposes_effective_experiment_configuration(self) -> None:
        agent = Agent(
            self.catalog_path,
            popularity_strength=0.20,
            override_policy="preserve_subject",
        )
        self.assertEqual(agent.experiment_configuration["popularity_strength"], 0.20)
        self.assertEqual(
            agent.experiment_configuration["override_policy"],
            "preserve_subject",
        )
        self.assertIsNone(agent.experiment_configuration["signature_index_path"])


if __name__ == "__main__":
    unittest.main()
