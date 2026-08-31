"""Product-mode journey behavior that the one-target evaluator cannot express."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storefront.catalog_view import CatalogView
from storefront.compatibility import compatibility_evidence, rerank_products
from storefront.journey import (
    ConstraintGroup,
    ConstraintOperator,
    ConstraintStrength,
    DeterministicJourneyPlanner,
    JourneyAction,
    LineItem,
    ShoppingPlan,
    alternative_queries,
    journey_beliefs,
)
from storefront.service import StorefrontService


PRODUCTS: tuple[dict[str, object], ...] = (
    {
        "parent_asin": "SUIT_BLUE",
        "title": "Men's Formal Blue Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["Classic formal blue suit"],
        "description": [],
        "details": {"Color": "Blue"},
        "price": 180,
        "average_rating": 4.6,
        "rating_number": 90,
        "store": "Tailor",
    },
    {
        "parent_asin": "SUIT_WHITE",
        "title": "Men's Formal White Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["Classic formal white suit"],
        "description": [],
        "details": {"Color": "White"},
        "price": 190,
        "average_rating": 4.5,
        "rating_number": 80,
        "store": "Tailor",
    },
    {
        "parent_asin": "SUIT_BOTH",
        "title": "Men's Formal Blue and White Wedding Suit",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
        "features": ["Classic formal blue white suit"],
        "description": [],
        "details": {"Color": "Blue and White"},
        "price": 195,
        "average_rating": 4.7,
        "rating_number": 70,
        "store": "Tailor",
    },
    {
        "parent_asin": "SHOE_BLACK",
        "title": "Men's Black Formal Oxford Shoes",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Oxfords"],
        "features": ["Black leather formal shoes for weddings"],
        "description": [],
        "details": {"Color": "Black"},
        "price": 85,
        "average_rating": 4.8,
        "rating_number": 200,
        "store": "Shoemaker",
    },
    {
        "parent_asin": "SHOE_BROWN",
        "title": "Men's Brown Casual Loafers",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Loafers"],
        "features": ["Brown leather casual shoes"],
        "description": [],
        "details": {"Color": "Brown"},
        "price": 70,
        "average_rating": 4.4,
        "rating_number": 110,
        "store": "Shoemaker",
    },
    {
        "parent_asin": "SHOE_WOMEN",
        "title": "Women's Black Formal Heels",
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes", "Heels"],
        "features": ["Black formal wedding shoes"],
        "description": [],
        "details": {"Color": "Black"},
        "price": 90,
        "average_rating": 4.9,
        "rating_number": 400,
        "store": "Shoemaker",
    },
    {
        "parent_asin": "UMBRELLA",
        "title": "Black Travel Umbrella",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Accessories", "Umbrellas"],
        "features": ["Black compact umbrella"],
        "description": [],
        "details": {},
        "price": 20,
        "average_rating": 4.9,
        "rating_number": 900,
        "store": "Rain",
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


class CatalogTaxonomyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.view = CatalogView(write_catalog(self))

    def test_categories_come_from_the_catalog_and_keep_item_boundaries(self) -> None:
        self.assertEqual(self.view.category_mentions("I need a suit"), ["suit"])
        self.assertEqual(
            self.view.category_mentions("I need a suit and shoes"),
            ["suit", "shoes"],
        )
        self.assertEqual(self.view.category_mentions("This is for a wedding"), [])
        self.assertEqual(self.view.category_mentions("for men, blue or white"), [])
        self.assertEqual(self.view.audience_mentions("for men, blue or white"), ["men"])


class JourneyPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.view = CatalogView(write_catalog(self))
        self.planner = DeterministicJourneyPlanner(self.view.category_mentions)
        self.plan = ShoppingPlan("journey")

    def test_the_reported_wedding_flow_becomes_two_linked_items(self) -> None:
        messages = (
            "I'm getting married and need a suit",
            "I like blue or white, maybe one with both colours",
            "Shoes to go along with it",
            "I don't know what I want, give me suggestions",
        )
        decisions = [
            self.planner.observe(self.plan, message, turn)
            for turn, message in enumerate(messages, start=1)
        ]
        self.assertEqual([decision.action for decision in decisions], [
            JourneyAction.CREATE,
            JourneyAction.UPDATE,
            JourneyAction.CREATE,
            JourneyAction.EXPLORE,
        ])
        self.assertEqual([item.category for item in self.plan.items], ["suit", "shoes"])
        self.assertEqual(self.plan.global_context, ["wedding"])
        shoes = self.plan.active_item
        assert shoes is not None
        self.assertEqual(shoes.relation, "complements")
        self.assertEqual(shoes.related_item_id, self.plan.items[0].item_id)
        colours = self.plan.items[0].constraints[0]
        self.assertEqual(colours.operator, ConstraintOperator.ANY)
        self.assertEqual(colours.values, ("blue", "white"))
        self.assertTrue(colours.prefer_all)

    def test_correction_supersedes_only_the_rejected_value(self) -> None:
        self.planner.observe(self.plan, "I need a black cotton suit", 1)
        self.planner.observe(self.plan, "No, not black - blue instead", 2)
        item = self.plan.active_item
        assert item is not None
        live = {(group.operator, group.values) for group in item.constraints}
        self.assertIn((ConstraintOperator.NOT, ("black",)), live)
        self.assertIn((ConstraintOperator.ALL, ("blue",)), live)
        self.assertTrue(any("black" in group.values for group in item.superseded))
        self.assertTrue(any("cotton" in group.values for group in item.constraints))

    def test_alternative_queries_give_each_value_a_retrieval_path(self) -> None:
        self.planner.observe(self.plan, "blue or white suit", 1)
        item = self.plan.active_item
        assert item is not None
        queries = alternative_queries(self.plan, item)
        self.assertTrue(any("blue" in query for query in queries))
        self.assertTrue(any("white" in query for query in queries))

    def test_comparison_values_do_not_become_preferences(self) -> None:
        self.planner.observe(self.plan, "I need a black suit", 1)
        before = self.plan.as_dict()
        decision = self.planner.observe(self.plan, "Why is black above brown?", 2)
        self.assertEqual(decision.action, JourneyAction.COMPARE)
        self.assertEqual(
            self.plan.items[0].constraints,
            [
                group
                for group in self.plan.items[0].constraints
                if "black" in group.values
            ],
        )
        self.assertFalse(any("brown" in group.values for group in self.plan.items[0].constraints))
        self.assertEqual(before["items"][0]["constraints"], self.plan.as_dict()["items"][0]["constraints"])

    def test_full_restart_replaces_the_journey(self) -> None:
        self.planner.observe(self.plan, "I need a suit and shoes", 1)
        self.planner.observe(self.plan, "Start over. I need a white suit", 2)
        self.assertEqual(len(self.plan.items), 1)
        self.assertEqual(self.plan.active_item.category, "suit")
        self.assertEqual(self.plan.active_item.constraints[0].values, ("white",))


class CompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.view = CatalogView(write_catalog(self))

    def test_related_items_reject_wrong_audience_and_wrong_category(self) -> None:
        plan = ShoppingPlan("p", global_context=["wedding"])
        suit = LineItem("suit", "suit", "Suit", 1, "p:suit", last_ids=["SUIT_BLUE"])
        shoes = LineItem(
            "shoes",
            "shoes",
            "Shoes",
            2,
            "p:shoes",
            relation="complements",
            related_item_id="suit",
        )
        plan.items.extend((suit, shoes))
        plan.active_item_id = "shoes"
        result = rerank_products(
            self.view,
            plan,
            shoes,
            ["SHOE_WOMEN", "UMBRELLA", "SHOE_BROWN", "SHOE_BLACK"],
            anchor_id="SUIT_BLUE",
            enforce_anchor_audience=True,
        )
        identifiers = [product.parent_asin for product in result.products]
        self.assertEqual(set(identifiers), {"SHOE_BLACK", "SHOE_BROWN"})
        self.assertEqual(identifiers[0], "SHOE_BLACK")

    def test_colour_reasoning_reports_evidence_and_uncertainty(self) -> None:
        evidence = compatibility_evidence(
            "SUIT_BLUE",
            self.view.raw("SUIT_BLUE") or {},
            self.view.raw("SHOE_BLACK") or {},
            ["wedding"],
        )
        self.assertGreater(evidence.score, 0.5)
        self.assertTrue(any("colour" in signal for signal in evidence.signals))
        self.assertIn(evidence.confidence, {"medium", "high"})

    def test_an_or_group_keeps_both_branches_and_rewards_both(self) -> None:
        plan = ShoppingPlan("p")
        suit = LineItem("suit", "suit", "Suit", 1, "p:suit")
        suit.constraints.append(
            ConstraintGroup(
                "color",
                ConstraintOperator.ANY,
                ("blue", "white"),
                ConstraintStrength.HARD,
                1,
                "blue or white",
                prefer_all=True,
            )
        )
        plan.items.append(suit)
        plan.active_item_id = suit.item_id
        result = rerank_products(
            self.view,
            plan,
            suit,
            ["SUIT_BLUE", "SUIT_WHITE", "SUIT_BOTH"],
        )
        identifiers = [product.parent_asin for product in result.products]
        self.assertEqual(set(identifiers), {"SUIT_BLUE", "SUIT_WHITE", "SUIT_BOTH"})
        self.assertEqual(identifiers[0], "SUIT_BOTH")


class JourneyServiceTest(unittest.TestCase):
    def test_journey_mode_never_returns_the_unrelated_product(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("live")
            service.send(conversation.session_id, "I am getting married and need a men's suit")
            turn = service.send(conversation.session_id, "Add shoes to go along with it")
        self.assertEqual(turn.journey["mode"], "journey")
        self.assertTrue(turn.cards)
        identifiers = {card["parent_asin"] for card in turn.cards}
        self.assertNotIn("UMBRELLA", identifiers)
        self.assertNotIn("SHOE_WOMEN", identifiers)
        self.assertTrue(identifiers.issubset({"SHOE_BLACK", "SHOE_BROWN"}))
        self.assertFalse(turn.degraded)
        self.assertEqual(turn.journey["items"][1]["audience"], "men")

    def test_unspecified_wearer_is_asked_not_assumed(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("audience")
            turn = service.send(conversation.session_id, "I need formal shoes")
        self.assertEqual(turn.ask_attribute, "wearer")
        self.assertIsNone(turn.journey["items"][0]["audience"])
        self.assertEqual(turn.journey_trace["question"]["source"], "catalog audience board")

    def test_a_displayed_product_can_be_confirmed_as_the_relation_anchor(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("selection")
            first = service.send(conversation.session_id, "I need a men's wedding suit")
            identifier = first.cards[0]["parent_asin"]
            selected = service.select(conversation.session_id, identifier)
            second = service.send(conversation.session_id, "Add shoes to go along with it")
        self.assertEqual(selected["selected_id"], identifier)
        self.assertEqual(second.journey_trace["anchor_id"], identifier)
        self.assertEqual(second.journey_trace["anchor_status"], "confirmed")
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("bad-selection")
            service.send(conversation.session_id, "I need shoes")
            with self.assertRaisesRegex(ValueError, "current slate"):
                service.select(conversation.session_id, "UMBRELLA")

    def test_first_turn_vagueness_uses_catalog_derived_exploration(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("vague")
            turn = service.send(
                conversation.session_id,
                "I don't know what I want, give me some suggestions",
            )
        self.assertTrue(turn.cards)
        self.assertTrue(turn.journey["exploration"])
        self.assertEqual(turn.journey["items"][0]["category"], "item")

    def test_supported_language_keeps_category_routing_and_reply_language(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("spanish")
            turn = service.send(conversation.session_id, "Busco unos zapatos para una boda")
        self.assertEqual(turn.journey["language"], "es")
        self.assertEqual(turn.journey["items"][0]["category"], "shoes")
        self.assertEqual(turn.journey["items"][0]["label"].lower(), "zapatos")
        self.assertTrue(turn.cards)
        self.assertIn("¿", turn.message)
        self.assertNotIn("wearer", turn.message.lower())


class TheRailShowsWhatThePlanUnderstands(unittest.TestCase):
    """The panel is headed "what I have understood", so it has to mean the plan.

    Scoped to the active line item it contradicted the plan beside it: after a
    wedding, a navy suit and then shoes, the plan showed the occasion and the
    colour while the rail said nothing had been disclosed, because navy belongs
    to the suit and the shoes had become active.
    """

    def _plan(self) -> ShoppingPlan:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("rail")
            service.send(conversation.session_id, "I am getting married and need a men's suit")
            service.send(conversation.session_id, "make it navy")
            turn = service.send(conversation.session_id, "Add shoes to go along with it")
        self.assertEqual(turn.journey["items"][-1]["category"], "shoes")
        return turn

    def test_a_constraint_on_an_earlier_item_still_appears(self) -> None:
        turn = self._plan()
        wanted = turn.beliefs["wanted"]
        self.assertTrue(wanted, "the rail is empty while the plan holds constraints")
        colours = [entry for entry in wanted if entry["value"] == "navy"]
        self.assertEqual(len(colours), 1)
        self.assertEqual(colours[0]["attribute"], "color")

    def test_every_entry_names_the_item_it_constrains(self) -> None:
        turn = self._plan()
        # Without an owner, "color navy" beside an active shoes item reads as
        # the shoes being navy.
        for entry in turn.beliefs["wanted"] + turn.beliefs["excluded"]:
            self.assertIn("item", entry)
            self.assertTrue(str(entry["item"]).strip())
        navy = next(entry for entry in turn.beliefs["wanted"] if entry["value"] == "navy")
        self.assertNotEqual(navy["item"].lower(), "shoes")

    def test_shared_context_is_attributed_to_the_journey_and_to_a_real_turn(self) -> None:
        turn = self._plan()
        shared = [entry for entry in turn.beliefs["wanted"] if entry["item"] == "shared"]
        self.assertTrue(shared, "the journey occasion never reaches the rail")
        for entry in shared:
            self.assertIn(entry["value"], turn.journey["global_context"])
            # The chip tooltip claims a turn. It has to be one that happened.
            self.assertGreaterEqual(entry["turn"], 1)
            self.assertLessEqual(entry["turn"], turn.turn)

    def test_an_empty_plan_still_reports_the_three_groups(self) -> None:
        beliefs = journey_beliefs(ShoppingPlan(session_id="empty"))
        self.assertEqual(beliefs["wanted"], [])
        self.assertEqual(beliefs["excluded"], [])
        self.assertEqual(beliefs["superseded"], [])
        self.assertEqual(beliefs["intent_version"], 1)


class AnUnnamedItemIsNotReadAsANoun(unittest.TestCase):
    """A line item the customer has not named carries the label "Current item".

    That is a heading in the plan rail and a noun in a sentence, and the
    opening turn of the wedding journey read "I updated the current item line
    item from the constraints I could verify in the catalog."
    """

    def test_no_message_doubles_the_placeholder_label(self) -> None:
        catalog = write_catalog(self)
        openings = (
            "I need an outfit for a wedding",
            "something for a formal event",
            "show me what you have",
        )
        for opening in openings:
            with self.subTest(opening=opening):
                with StorefrontService(catalog, journey_mode=True) as service:
                    conversation = service.start("unnamed")
                    turn = service.send(conversation.session_id, opening)
                message = turn.message.lower()
                self.assertNotIn("current item line item", message)
                self.assertNotIn("these current item", message)
                self.assertNotIn("your current item intent", message)
                self.assertNotIn("no current item that", message)
                self.assertNotIn("added current item", message)

    def test_a_named_item_still_names_itself(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("named")
            service.send(conversation.session_id, "I am getting married and need a men's suit")
            turn = service.send(conversation.session_id, "Add shoes to go along with it")
        self.assertIn("shoes", turn.message.lower())


class JourneyArtifactTest(unittest.TestCase):
    def test_interface_renders_plan_and_compatibility_without_html_injection(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "demo" / "storefront.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("function renderJourney(journey)", source)
        self.assertIn("Compatibility evidence", source)
        self.assertIn("journey_trace", source)
        self.assertNotIn("innerHTML", source)


if __name__ == "__main__":
    unittest.main()
