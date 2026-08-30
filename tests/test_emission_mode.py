"""The emission gate as it ships, not as the experiment harness ran it.

`docs/evidence/EXP_023.md` measures these arms by wrapping `Agent.respond`.
This covers the same rules in `needle/agent.py` and `needle/promotion.py`, so a
refactor cannot quietly restore the behaviour the evidence was measured against.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.agent import Agent  # noqa: E402
from needle.promotion import (  # noqa: E402
    clause_parses,
    coarse_category,
    normalize_for_match,
)

CATALOG = ROOT / ".artifacts/participant-kit/techjam-conversational-search/data/catalog.jsonl"


class ConfigurationTest(unittest.TestCase):
    def test_the_mode_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            Agent(CATALOG, emission_mode="promote-ish")

    def test_the_release_turn_is_bounded(self) -> None:
        for value in (1, 0, 11, -3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Agent(CATALOG, emission_mode="slate", release_turn=value)

    def test_slate_mode_builds_no_index(self) -> None:
        # The index costs a full catalog pass, so the rollback preset must not
        # pay for a feature it does not use.
        with Agent(CATALOG, emission_mode="slate") as agent:
            self.assertIsNone(agent.prefix_index)


class CoarseCategoryTest(unittest.TestCase):
    """Mirrors `local_evaluator.coarse_category`; the key has to match exactly."""

    def test_the_last_two_parts_are_kept(self) -> None:
        self.assertEqual(
            coarse_category(["Clothing, Shoes & Jewelry", "Women", "Shoes", "Boots"]),
            "Shoes Boots",
        )

    def test_the_excluded_root_is_dropped_but_its_siblings_are_not(self) -> None:
        # "Clothing, Shoes & Jewelry" splits on the comma first, so only
        # "Clothing" is excluded and "Shoes & Jewelry" survives. Getting this
        # wrong would build a key the opening message never states.
        self.assertEqual(coarse_category(["Clothing, Shoes & Jewelry"]), "Shoes & Jewelry")

    def test_empty_categories_fall_back(self) -> None:
        self.assertEqual(coarse_category([]), "clothing item")

    @unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
    def test_the_mirror_agrees_with_the_evaluator_on_every_product(self) -> None:
        """The whole promotion key rests on this being the same function.

        `local_evaluator.coarse_category` is mirrored rather than imported,
        because the agent must not depend on the grader's module. That is only
        safe while the two agree, so this asserts it over the entire catalog.
        """
        import json
        sys.path.insert(1, str(CATALOG.parents[1]))
        from evaluator.local_evaluator import coarse_category as official

        disagreements = 0
        with CATALOG.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                categories = json.loads(line).get("categories")
                if not isinstance(categories, list):
                    categories = []
                if official(categories) != coarse_category(categories):
                    disagreements += 1
        self.assertEqual(disagreements, 0)


class NormalizationTest(unittest.TestCase):
    def test_accents_are_folded(self) -> None:
        self.assertEqual(normalize_for_match("Sandàls"), "Sandals")

    def test_discourse_markers_are_dropped(self) -> None:
        self.assertEqual(
            clause_parses("For that, um, what matters is: 100% Cotton."),
            clause_parses("For that, what matters is: 100% Cotton."),
        )

    def test_a_clause_is_parsed_both_ways_when_it_is_ambiguous(self) -> None:
        # "Solid colors: 100% Cotton; Heather Grey: 90% Cotton" is either one
        # constraint or two, and the text cannot say which. Both are offered.
        parses = clause_parses("For that, what matters is: a; b.")
        self.assertIn(("a b",), parses)
        self.assertIn(("a", "b"), parses)


@unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
class EmissionTest(unittest.TestCase):
    """The gate withholds, and never withholds a product it has already shown."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = Agent(
            CATALOG,
            retrieval_mode="signature_first",
            emission_mode="promote",
            release_turn=8,
            exclude_seen=True,
            popularity_strength=0.30,
            category_strength=1.00,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.agent.close()

    def test_one_product_is_emitted_while_the_state_is_thin(self) -> None:
        self.agent.reset("s1", {})
        response = self.agent.respond("s1", "I'm looking for Shoes Boots, but I'm still exploring.", 1, 10)
        self.assertEqual(len(response["recommendations"]), 1)

    def test_the_release_turn_restores_a_full_slate(self) -> None:
        self.agent.reset("s2", {})
        message = "I'm looking for Shoes Boots, but I'm still exploring."
        for turn in range(1, 8):
            self.agent.respond("s2", message, turn, 10)
            message = "Those options are not quite right yet. Ask me about one specific attribute."
        final = self.agent.respond("s2", message, 8, 10)
        self.assertGreater(len(final["recommendations"]), 1)

    def test_a_withheld_product_is_never_marked_seen(self) -> None:
        # The shipped path marks everything *retrieved* as seen. Under a gate
        # that withholds, that would let `exclude_seen` blacklist the very
        # target the gate is holding back for.
        self.agent.reset("s3", {})
        response = self.agent.respond("s3", "I'm looking for Shoes Boots, but I'm still exploring.", 1, 10)
        shown = {item["parent_asin"] for item in response["recommendations"]}
        marked = set(self.agent._seen_by_version[("s3", 1)])
        self.assertEqual(marked, shown)
        self.assertEqual(len(shown), 1)

    def test_the_response_contract_still_holds(self) -> None:
        self.agent.reset("s4", {})
        response = self.agent.respond("s4", "I'm looking for Shoes Boots.", 1, 10)
        self.assertEqual(set(response), {"message", "ask_attribute", "recommendations", "usage"})
        self.assertIsInstance(response["message"], str)
        self.assertLessEqual(len(response["recommendations"]), 10)


if __name__ == "__main__":
    unittest.main()
