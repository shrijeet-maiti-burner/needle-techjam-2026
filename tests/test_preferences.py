"""Numeric shopping intent is typed, persistent and catalog-grounded."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storefront.catalog_view import CatalogView
from storefront.compatibility import _audience, rerank_products
from storefront.journey import DeterministicJourneyPlanner, LineItem, ShoppingPlan
from storefront.preferences import (
    PRICE,
    RATING,
    REVIEWS,
    parse_numeric_intent,
    searchable_text,
)
from storefront.service import StorefrontService


PRODUCTS: tuple[dict[str, object], ...] = (
    {
        "parent_asin": "CHEAP",
        "title": "Men's Classic Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["navy wool formal suit"],
        "description": [],
        "details": {"Occasion": "Wedding", "Material": "Wool"},
        "price": 80,
        "average_rating": 4.2,
        "rating_number": 900,
        "store": "Tailor A",
    },
    {
        "parent_asin": "QUALITY",
        "title": "Men's Premium Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["navy wool formal suit"],
        "description": [],
        "details": {"Occasion": "Wedding", "Material": "Wool"},
        "price": 150,
        "average_rating": 4.8,
        "rating_number": 500,
        "store": "Tailor B",
    },
    {
        "parent_asin": "TINY_FIVE",
        "title": "Men's New Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["navy wool formal suit"],
        "description": [],
        "details": {"Occasion": "Wedding", "Material": "Wool"},
        "price": 120,
        "average_rating": 5.0,
        "rating_number": 1,
        "store": "Tailor C",
    },
    {
        "parent_asin": "UNKNOWN_PRICE",
        "title": "Men's Formal Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["navy wool formal suit"],
        "description": [],
        "details": {"Occasion": "Wedding", "Material": "Wool"},
        "price": None,
        "average_rating": 4.7,
        "rating_number": 200,
        "store": "Tailor D",
    },
    {
        "parent_asin": "RUN_SHOE",
        "title": "Men's Black Running Shoe",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Athletic", "Running"],
        "features": ["black road running shoe"],
        "description": [],
        "details": {"Color": "Black"},
        "price": 60,
        "average_rating": 4.5,
        "rating_number": 100,
        "store": "Runner",
    },
    {
        "parent_asin": "RUN_SOCK",
        "title": "Men's Black Running Socks",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Socks", "Running Socks"],
        "features": ["black road running socks"],
        "description": [],
        "details": {"Color": "Black"},
        "price": 10,
        "average_rating": 4.8,
        "rating_number": 1000,
        "store": "Runner",
    },
)


def write_catalog(case: unittest.TestCase) -> Path:
    directory = tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    path = Path(directory.name) / "catalog.jsonl"
    path.write_text(
        "\n".join(json.dumps(product) for product in PRODUCTS) + "\n",
        encoding="utf-8",
    )
    return path


class NumericIntentParserTest(unittest.TestCase):
    def test_catalog_taxonomy_is_authoritative_for_conflicting_audience_text(self) -> None:
        product = {
            "title": "Example Men's Running Shoe",
            "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes", "Running"],
        }
        self.assertEqual(_audience(product), "women")

    def test_price_upper_lower_and_range_are_distinct(self) -> None:
        upper = parse_numeric_intent("a suit under $100", 1).filters[0]
        lower = parse_numeric_intent("a suit more than $80", 1).filters[0]
        bounded = parse_numeric_intent("price between $80 and $150", 1).filters[0]
        self.assertEqual((upper.field, upper.minimum, upper.maximum), (PRICE, None, 100))
        self.assertEqual((lower.field, lower.minimum, lower.maximum), (PRICE, 80, None))
        self.assertEqual((bounded.field, bounded.minimum, bounded.maximum), (PRICE, 80, 150))
        self.assertFalse(upper.maximum_inclusive)
        self.assertFalse(lower.minimum_inclusive)
        self.assertTrue(bounded.minimum_inclusive)
        self.assertTrue(bounded.maximum_inclusive)

    def test_measurements_do_not_become_prices(self) -> None:
        for message in (
            "fits up to 30mm",
            "between size 8 and 10",
            "up to 8-inch wrist",
            "up to 3 pairs",
            "up to 30 mm",
        ):
            with self.subTest(message=message):
                self.assertFalse(parse_numeric_intent(message, 1).filters)

    def test_rating_and_review_filters_are_typed(self) -> None:
        stars = parse_numeric_intent("at least 4.5 stars", 2).filters[0]
        reviews = parse_numeric_intent("more than 100 reviews", 2).filters[0]
        self.assertEqual((stars.field, stars.minimum), (RATING, 4.5))
        self.assertEqual((reviews.field, reviews.minimum), (REVIEWS, 100))

    def test_rating_and_review_maxima_do_not_become_prices(self) -> None:
        stars = parse_numeric_intent("up to 4.5 stars", 2)
        reviews = parse_numeric_intent("under 100 reviews", 2)
        self.assertEqual(
            [(value.field, value.minimum, value.maximum) for value in stars.filters],
            [(RATING, None, 4.5)],
        )
        self.assertEqual(
            [(value.field, value.minimum, value.maximum) for value in reviews.filters],
            [(REVIEWS, None, 100)],
        )

    def test_review_range_is_typed(self) -> None:
        intent = parse_numeric_intent("between 100 and 500 reviews", 2)
        self.assertEqual(
            [(value.field, value.minimum, value.maximum) for value in intent.filters],
            [(REVIEWS, 100, 500)],
        )

    def test_each_explicit_ranking_phrase_selects_the_right_field(self) -> None:
        cases = {
            "the cheapest one": (PRICE, False),
            "the most expensive one": (PRICE, True),
            "the best rated one": (RATING, True),
            "the most reviewed one": (REVIEWS, True),
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                ranking = parse_numeric_intent(message, 1).ranking
                self.assertIsNotNone(ranking)
                self.assertEqual((ranking.field, ranking.descending), expected)

    def test_natural_rating_phrases_use_confidence_adjusted_ordering(self) -> None:
        for message in (
            "highly rated running shoes",
            "well reviewed running shoes",
            "running shoes with great reviews",
            "running shoes with good customer reviews",
        ):
            with self.subTest(message=message):
                intent = parse_numeric_intent(message, 1)
                self.assertEqual((intent.ranking.field, intent.ranking.descending), (RATING, True))
                self.assertFalse(intent.filters)

    def test_suffix_rating_floor_is_an_inclusive_filter(self) -> None:
        for message in (
            "rated 4.5 or higher",
            "4.5 stars or better",
            "rating 4.5 or above",
        ):
            with self.subTest(message=message):
                intent = parse_numeric_intent(message, 1)
                self.assertEqual(len(intent.filters), 1)
                constraint = intent.filters[0]
                self.assertEqual((constraint.field, constraint.minimum, constraint.maximum), (RATING, 4.5, None))
                self.assertTrue(constraint.minimum_inclusive)

    def test_bare_star_target_filters_then_uses_review_confidence(self) -> None:
        for message in ("5 star running shoes", "five-star running shoes"):
            with self.subTest(message=message):
                intent = parse_numeric_intent(message, 1)
                self.assertEqual((intent.filters[0].field, intent.filters[0].minimum), (RATING, 5.0))
                self.assertEqual((intent.ranking.field, intent.ranking.descending), (RATING, True))

    def test_quality_without_catalog_evidence_is_not_relabelled_as_rating(self) -> None:
        intent = parse_numeric_intent("good quality running shoes", 1)
        self.assertFalse(intent.filters)
        self.assertIsNone(intent.ranking)

    def test_negated_numeric_intent_is_not_silently_reversed(self) -> None:
        cases = (
            "not the cheapest one",
            "I do not want the most expensive one",
            "not rated above 4.5 stars",
            "not between $50 and $100",
            "not more than 100 reviews",
        )
        for message in cases:
            with self.subTest(message=message):
                intent = parse_numeric_intent(message, 1)
                self.assertFalse(intent.filters)
                self.assertIsNone(intent.ranking)

    def test_non_text_directives_are_removed_without_losing_product_evidence(self) -> None:
        cleaned = searchable_text("the best rated navy suit for men under $200")
        self.assertNotIn("best rated", cleaned)
        self.assertNotIn("$200", cleaned)
        self.assertIn("navy suit for men", cleaned)
        self.assertEqual(
            searchable_text("shoes in sizes from 8 to 10"),
            "shoes in sizes from 8 to 10",
        )
        self.assertEqual(searchable_text("up to 3 pairs of running shoes"), "up to 3 pairs of running shoes")
        self.assertEqual(searchable_text("running shoes rated 4.5 stars or higher"), "running shoes")
        self.assertEqual(searchable_text("highly rated running shoes"), "running shoes")


class StructuredRerankingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = write_catalog(self)
        self.view = CatalogView(self.catalog)
        self.planner = DeterministicJourneyPlanner(
            self.view.category_mentions,
            self.view.audience_mentions,
        )

    def _rank(self, message: str) -> tuple[list[str], object]:
        plan = ShoppingPlan("rank")
        self.planner.observe(plan, message, 1)
        item = plan.active_item
        assert item is not None
        result = rerank_products(
            self.view,
            plan,
            item,
            ["TINY_FIVE", "CHEAP", "UNKNOWN_PRICE", "QUALITY"],
        )
        return [row.parent_asin for row in result.products], result

    def test_best_rated_uses_review_confidence_not_raw_stars(self) -> None:
        identifiers, result = self._rank("best rated men's suit")
        self.assertEqual(identifiers[0], "QUALITY")
        self.assertNotEqual(identifiers[0], "TINY_FIVE")
        self.assertEqual(result.ranking["method"], "bayesian average weighted by catalog review count")

    def test_cheapest_uses_stated_prices_and_puts_missing_price_last(self) -> None:
        identifiers, _ = self._rank("cheapest men's suit")
        self.assertEqual(identifiers[0], "CHEAP")
        self.assertEqual(identifiers[-1], "UNKNOWN_PRICE")

    def test_a_price_range_is_a_hard_filter(self) -> None:
        identifiers, _ = self._rank("men's suit between $100 and $160")
        self.assertEqual(set(identifiers), {"QUALITY", "TINY_FIVE"})

    def test_a_minimum_rating_is_a_hard_filter(self) -> None:
        identifiers, _ = self._rank("men's suit at least 4.7 stars")
        self.assertEqual(set(identifiers), {"QUALITY", "TINY_FIVE", "UNKNOWN_PRICE"})

    def test_strict_and_inclusive_boundaries_are_not_conflated(self) -> None:
        strict_minimum, _ = self._rank("men's suit more than $80")
        inclusive_minimum, _ = self._rank("men's suit at least $80")
        strict_maximum, _ = self._rank("men's suit under $120")
        inclusive_maximum, _ = self._rank("men's suit up to $120")
        self.assertNotIn("CHEAP", strict_minimum)
        self.assertIn("CHEAP", inclusive_minimum)
        self.assertNotIn("TINY_FIVE", strict_maximum)
        self.assertIn("TINY_FIVE", inclusive_maximum)

    def test_multiword_category_integrity_rejects_partial_matches(self) -> None:
        plan = ShoppingPlan("category")
        item = LineItem("shoe", "running shoes", "Running shoes", 1, "category:shoe")
        plan.items.append(item)
        plan.active_item_id = item.item_id
        result = rerank_products(self.view, plan, item, ["RUN_SOCK", "RUN_SHOE"])
        self.assertEqual([row.parent_asin for row in result.products], ["RUN_SHOE"])

    def test_numeric_comparison_pool_covers_the_complete_catalog_category(self) -> None:
        self.assertEqual(
            self.view.category_candidates("running shoes", audience="men"),
            ["RUN_SHOE"],
        )
        self.assertEqual(set(self.view.raw_many(["QUALITY", "CHEAP"])), {"QUALITY", "CHEAP"})


class NumericJourneyIntegrationTest(unittest.TestCase):
    def test_best_rated_is_answered_instead_of_triggering_an_unrelated_question(self) -> None:
        with StorefrontService(write_catalog(self), journey_mode=True) as service:
            conversation = service.start("quality")
            turn = service.send(conversation.session_id, "the best rated suit for men")
        self.assertEqual(turn.cards[0]["parent_asin"], "QUALITY")
        self.assertIsNone(turn.ask_attribute)
        self.assertIn("confidence-adjusted rating", turn.message)
        self.assertEqual(turn.journey_trace["question"]["source"], "explicit shopper ranking")
        self.assertEqual(turn.journey_trace["ranking"]["field"], RATING)

    def test_highly_rated_uses_the_same_evidence_bounded_ordering(self) -> None:
        with StorefrontService(write_catalog(self), journey_mode=True) as service:
            conversation = service.start("natural-quality")
            turn = service.send(conversation.session_id, "highly rated suit for men")
        self.assertEqual(turn.cards[0]["parent_asin"], "QUALITY")
        self.assertIsNone(turn.ask_attribute)
        self.assertEqual(turn.journey_trace["ranking"]["method"], "bayesian average weighted by catalog review count")

    def test_explicit_numeric_filters_do_not_trigger_an_unrelated_question(self) -> None:
        for message in (
            "men's suit rated 4.5 or higher",
            "men's suit between $100 and $160",
            "men's suit with at least 100 reviews",
        ):
            with self.subTest(message=message):
                with StorefrontService(write_catalog(self), journey_mode=True) as service:
                    conversation = service.start()
                    turn = service.send(conversation.session_id, message)
                self.assertTrue(turn.cards)
                self.assertIsNone(turn.ask_attribute)
                self.assertEqual(
                    turn.journey_trace["question"]["source"],
                    "explicit shopper numeric filter",
                )
                self.assertIn("I applied", turn.message)

    def test_a_later_ranking_request_updates_the_existing_line_item(self) -> None:
        with StorefrontService(write_catalog(self), journey_mode=True) as service:
            conversation = service.start("later")
            service.send(conversation.session_id, "I need a men's wedding suit")
            turn = service.send(conversation.session_id, "show me the cheapest one")
        self.assertEqual(len(turn.journey["items"]), 1)
        self.assertEqual(turn.cards[0]["parent_asin"], "CHEAP")
        self.assertEqual(turn.journey["items"][0]["ranking"]["field"], PRICE)

    def test_cheapest_running_shoes_does_not_admit_running_socks(self) -> None:
        with StorefrontService(write_catalog(self), journey_mode=True) as service:
            conversation = service.start("category-price")
            turn = service.send(conversation.session_id, "the cheapest running shoes for men")
        self.assertEqual([card["parent_asin"] for card in turn.cards], ["RUN_SHOE"])

    def test_numeric_preference_can_be_replaced_and_cleared(self) -> None:
        plan = ShoppingPlan("change")
        planner = DeterministicJourneyPlanner(lambda _text: ["suit"])
        planner.observe(plan, "suit under $100", 1)
        planner.observe(plan, "actually, price between $100 and $160", 2)
        item = plan.active_item
        assert item is not None
        self.assertEqual(len(item.numeric_filters), 1)
        self.assertEqual((item.numeric_filters[0].minimum, item.numeric_filters[0].maximum), (100, 160))
        self.assertEqual(len(item.superseded_numeric), 1)
        planner.observe(plan, "any price", 3)
        self.assertFalse(item.numeric_filters)
        self.assertEqual(len(item.superseded_numeric), 2)


if __name__ == "__main__":
    unittest.main()
