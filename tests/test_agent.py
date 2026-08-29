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

    def test_reset_is_required(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "reset must be called"):
            self.agent.respond("missing", "black shirt", 1, 10)

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


if __name__ == "__main__":
    unittest.main()
