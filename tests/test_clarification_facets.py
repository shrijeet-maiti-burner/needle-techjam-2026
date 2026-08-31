"""The question has to be one the customer can answer.

The board used to rank a facet by the reduction of its full partition. That
rewards exactly the wrong shape: `brand` splits a 400-product pool into
hundreds of singletons, which minimises expected remaining, while the four
makers it can actually offer cover 9% of the pool. Nine times in ten the honest
answer is "none of those", the set does not shrink, and a turn is gone.

So the partition scored is the one the question creates: one group per offered
value and one group for everything else, which is what an unoffered value and an
unknown value both mean to someone reading four choices.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from needle.catalog import product_clarification_facets
from needle.questions import FACETS, clarification_board


class FieldDerivedFacets(unittest.TestCase):
    """`store`, `price` and the category leaf are stated by the catalog, so they
    are answerable without parsing a description."""

    PRODUCT = {
        "title": "Leather Hiking Boot",
        "features": ["100% Leather", "black"],
        "details": {"Material": "Leather"},
        "store": "Timberland",
        "price": 89.99,
        "categories": ["Clothing", "Men", "Shoes", "Hiking Boots"],
    }

    def test_brand_comes_from_the_store_field(self) -> None:
        self.assertEqual(product_clarification_facets(self.PRODUCT)["brand"], "Timberland")

    def test_the_category_leaf_separates_siblings(self) -> None:
        self.assertEqual(product_clarification_facets(self.PRODUCT)["category"], "hiking boots")

    def test_price_becomes_a_band(self) -> None:
        self.assertEqual(product_clarification_facets(self.PRODUCT)["budget"], "$50 to $100")

    def test_a_bare_number_in_prose_is_never_a_budget_option(self) -> None:
        """"500" is not a choice a customer can pick out of a description."""
        product = {**self.PRODUCT, "features": ["holds 500 lumens"], "price": None}
        self.assertNotIn("budget", product_clarification_facets(product))

    def test_nothing_is_invented_when_the_field_is_absent(self) -> None:
        bare = {"title": "Boot", "features": [], "details": {}}
        facets = product_clarification_facets(bare)
        for absent in ("brand", "budget", "category"):
            with self.subTest(facet=absent):
                self.assertNotIn(absent, facets)

    def test_every_facet_the_board_ranks_can_be_produced(self) -> None:
        produced = set(product_clarification_facets(self.PRODUCT))
        self.assertTrue(produced <= set(FACETS), f"unrankable facets: {produced - set(FACETS)}")


class TheQuestionIsScoredNotTheFacet(unittest.TestCase):
    def _long_tail(self) -> tuple[list[str], dict]:
        """396 distinct makers, four of which can be offered."""
        ids = [f"p{i}" for i in range(400)]
        facets = {
            pid: {"brand": f"maker {i}", "material": "leather" if i % 2 else "canvas"}
            for i, pid in enumerate(ids)
        }
        return ids, facets

    def test_a_long_tail_facet_does_not_win_on_its_full_partition(self) -> None:
        ids, facets = self._long_tail()
        board = clarification_board(ids, facets, max_options=4)
        ranked = [decision.attribute for decision in board]
        self.assertIn("material", ranked)
        if "brand" in ranked:
            self.assertLess(
                ranked.index("material"), ranked.index("brand"),
                "a facet whose options cover almost nothing outranked an answerable one",
            )

    def test_a_long_tail_question_does_not_repay_a_turn(self) -> None:
        ids, facets = self._long_tail()
        brand = next(
            (d for d in clarification_board(ids, facets, max_options=4) if d.attribute == "brand"),
            None,
        )
        if brand is not None:
            self.assertFalse(brand.asks, "offering four of 396 makers was treated as worth a turn")

    def test_the_same_facet_wins_when_it_is_answerable(self) -> None:
        """Three makers, every candidate covered. Now it is the right question."""
        ids = [f"p{i}" for i in range(60)]
        facets = {
            pid: {"brand": ["Timberland", "Columbia", "Merrell"][i % 3],
                  "color": ["black", "brown"][i % 2]}
            for i, pid in enumerate(ids)
        }
        board = clarification_board(ids, facets, max_options=4)
        self.assertTrue(board, "no question was offered at all")
        self.assertEqual(board[0].attribute, "brand")
        self.assertTrue(board[0].asks)


if __name__ == "__main__":
    unittest.main()


class AQuestionIsNotAskedTwice(unittest.TestCase):
    """The set shrinks between turns, so the same facet keeps winning on fresh
    numbers. Asked four times running it reads as an agent that is not
    listening, which is worse than asking nothing at all.
    """

    def _pool(self) -> tuple[list[str], dict]:
        ids = [f"p{i}" for i in range(40)]
        facets = {
            pid: {
                "category": ["hiking boots", "hiking shoes"][i % 2],
                "color": ["black", "brown"][i % 2],
                "style": ["casual", "classic"][i % 2],
            }
            for i, pid in enumerate(ids)
        }
        return ids, facets

    def test_an_answered_facet_is_not_offered_again(self) -> None:
        ids, facets = self._pool()
        first = clarification_board(ids, facets, max_options=4)[0].attribute
        second = clarification_board(ids, facets, already_asked=[first], max_options=4)
        self.assertTrue(second, "nothing else was available to ask")
        self.assertNotIn(first, [decision.attribute for decision in second])

    def test_the_board_empties_rather_than_repeating(self) -> None:
        ids, facets = self._pool()
        asked = [decision.attribute for decision in clarification_board(ids, facets)]
        self.assertEqual(clarification_board(ids, facets, already_asked=asked), ())

    def test_the_agent_holds_it_for_the_session(self) -> None:
        """Through the agent, because the memory is per session and `reset`
        has to clear it or a second customer inherits the first one's."""
        from needle.agent import Agent

        catalog = ROOT / ".artifacts/participant-kit/techjam-conversational-search/data/catalog.jsonl"
        if not catalog.is_file():
            self.skipTest("official catalog is not bootstrapped")
        with Agent(str(catalog), explain=True) as agent:
            agent.reset("s", {})
            asked = []
            for turn, message in enumerate(
                ["leather boots for hiking", "waterproof", "something durable"], 1
            ):
                agent.respond("s", message, turn, 10)
                asked = list(agent._asked_facets_by_session.get("s", []))
            self.assertEqual(len(asked), len(set(asked)), f"a facet was asked twice: {asked}")
            agent.reset("s", {})
            self.assertEqual(agent._asked_facets_by_session.get("s", []), [])
