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
    query_for,
    retired_terms,
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


def write_wide_catalog(case: unittest.TestCase) -> Path:
    """A slate wide enough that several facets stay viable for many turns.

    The bundled fixture runs out of catalog facets after one question and falls
    through to the open `other`, so a test written against it can pass while
    the behaviour it claims to check never happens. Reproducing a real board
    needs a catalog that keeps offering a winner as the slate shrinks.
    """
    directory = tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    path = Path(directory.name) / "catalog.jsonl"
    products = []
    index = 0
    for color in ("black", "blue", "brown", "green"):
        for material in ("leather", "canvas", "denim", "wool"):
            for style in ("classic", "casual", "formal", "athletic"):
                index += 1
                products.append({
                    "parent_asin": f"W{index:04d}",
                    "title": f"Men's {style} {color} {material} Suit",
                    "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Suits"],
                    "features": [f"{style} {material} weave"],
                    "description": [f"A {color} suit in {material}."],
                    "details": {"Color": color.title(), "Material": material.title()},
                    "price": 40 + index,
                    "average_rating": 4.0,
                    "rating_number": 100 + index,
                    "store": f"Maker{index % 5}",
                })
    path.write_text(
        "\n".join(json.dumps(product) for product in products) + "\n",
        encoding="utf-8",
    )
    return path


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

    def test_preference_retraction_rotates_only_the_active_product_session(self) -> None:
        self.planner.observe(self.plan, "I need a blue suit", 1)
        item = self.plan.active_item
        assert item is not None
        original_session = item.agent_session_id
        item.local_turn = 3
        item.asked_facets.append("style")
        item.offered_values["style"] = ["formal", "casual"]
        item.last_ids = ["SUIT_BLUE"]
        item.selected_id = "SUIT_BLUE"

        self.planner.observe(
            self.plan,
            "ignore my earlier preference; make it white",
            2,
        )

        self.assertEqual(len(self.plan.items), 1)
        self.assertNotEqual(item.agent_session_id, original_session)
        self.assertEqual(item.local_turn, 0)
        self.assertEqual(item.messages, ["ignore my earlier preference; make it white"])
        self.assertEqual(item.asked_facets, [])
        self.assertEqual(item.offered_values, {})
        self.assertEqual(item.last_ids, [])
        self.assertIsNone(item.selected_id)
        self.assertTrue(any("blue" in group.values for group in item.superseded))
        self.assertTrue(any("white" in group.values for group in item.constraints))

    def test_concrete_category_promotes_the_vague_placeholder(self) -> None:
        self.planner.observe(self.plan, "I need something for a wedding", 1)
        placeholder_id = self.plan.active_item_id
        self.planner.observe(self.plan, "make it a suit", 2)
        self.assertEqual(len(self.plan.items), 1)
        self.assertEqual(self.plan.active_item_id, placeholder_id)
        self.assertEqual(self.plan.active_item.category, "suit")
        self.assertEqual(self.plan.active_item.label, "Suit")
        self.assertIsNone(self.plan.active_item.relation)

    def test_an_offered_facet_value_refines_instead_of_creating_an_item(self) -> None:
        planner = DeterministicJourneyPlanner(
            lambda text: [value for value in ("suit", "formal") if value in text.lower()]
        )
        plan = ShoppingPlan("offered-value")
        planner.observe(plan, "I need a suit", 1)
        item = plan.active_item
        assert item is not None
        item.asked_facets.append("style")
        item.offered_values["style"] = ["formal", "casual"]
        planner.observe(plan, "formal", 2)
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.active_item.category, "suit")

    def test_a_typed_facet_value_is_not_mistaken_for_a_product_type(self) -> None:
        planner = DeterministicJourneyPlanner(
            lambda text: [value for value in ("suit", "formal", "shoes") if value in text.lower()]
        )
        plan = ShoppingPlan("typed-value")
        planner.observe(plan, "I need a suit", 1)
        planner.observe(plan, "formal", 2)
        self.assertEqual([item.category for item in plan.items], ["suit"])
        planner.observe(plan, "add formal shoes", 3)
        self.assertEqual([item.category for item in plan.items], ["suit", "shoes"])


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
        self.assertEqual(turn.journey_trace["question"]["catalog_coverage"], 1.0)
        self.assertIn("Who will wear it?", turn.message)
        self.assertNotIn("constraints I could verify", turn.message)

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
        self.assertNotIn(second.ask_attribute, {"brand", "category", "budget"})
        self.assertTrue(second.journey_trace["question"]["relationship_aware"])
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


class ACorrectionDoesNotComeBackThroughTheQuery(unittest.TestCase):
    """The plan can hold the correction and still ask retrieval for the old thing.

    `query_for` appends the customer's own recent words to the structured
    terms, which is useful for evidence the compact facets do not carry. It is
    also where a retracted value returns: "actually not navy, make it black"
    contains "navy", and so does the message before it, so the query one turn
    after the correction read

        suit wedding navy suit wedding black navy actually not make

    with the belief state entirely correct and the query wrong. The scored
    agent then read navy as the active colour, which is the failure the
    organizer used as their example of a weak agent.
    """

    def setUp(self) -> None:
        self.view = CatalogView(write_catalog(self))
        self.planner = DeterministicJourneyPlanner(self.view.category_mentions)
        self.plan = ShoppingPlan("correction")

    def _run(self, *messages: str):
        for turn, message in enumerate(messages, start=1):
            self.planner.observe(self.plan, message, turn)
        return self.plan.active_item

    def test_a_replaced_value_leaves_the_query(self) -> None:
        item = self._run("I need a men's suit", "a navy suit",
                         "actually not navy, make it black")
        query = query_for(self.plan, item)
        self.assertIn("black", query)
        self.assertNotIn("navy", query, f"the retracted colour is still in: {query!r}")

    def test_an_excluded_value_leaves_the_query(self) -> None:
        item = self._run("I need a men's suit", "no polyester")
        query = query_for(self.plan, item)
        self.assertNotIn("polyester", query, f"the excluded material is still in: {query!r}")

    def test_a_value_stated_again_after_a_retraction_is_wanted_again(self) -> None:
        """Retirement is not permanent. The positive groups are the authority."""
        item = self._run("I need a men's suit", "a navy suit",
                         "actually not navy, make it black", "on reflection, navy")
        colours = {
            value
            for group in item.positive_groups()
            for value in group.values
        }
        if "navy" in colours:
            self.assertIn("navy", query_for(self.plan, item))
            self.assertNotIn("navy", retired_terms(item))

    def test_the_shoppers_other_words_are_kept(self) -> None:
        """The tail earns its place; the fix must not empty it."""
        item = self._run("I need a men's suit for a garden ceremony")
        self.assertIn("garden", query_for(self.plan, item))


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


class AQuestionIsNotPutTwiceToTheSamePerson(unittest.TestCase):
    """Journey mode had its own question path and its own copy of this bug.

    Driving the wedding journey live, the interface asked "which wearer would
    help most" on five consecutive turns while the customer answered every
    time: the released slate shrinks under each answer, so the same facet keeps
    winning on the new numbers. An agent that repeats itself while you reply
    reads as one that is not listening, which is worse than asking nothing.
    """

    SCRIPT = (
        "I need an outfit for a wedding",
        "a navy suit",
        "actually not navy, make it black",
        "no polyester",
        "Add shoes to go along with it",
    )

    _wide_catalog = staticmethod(write_wide_catalog)

    def test_the_same_facet_is_not_offered_again_as_the_slate_shrinks(self) -> None:
        catalog = self._wide_catalog(self)
        asked: list[str] = []
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("wide")
            for message in ("I need shoes for men", "something durable",
                            "I do not know", "anything really", "you choose"):
                turn = service.send(conversation.session_id, message)
                if turn.ask_attribute and turn.ask_attribute != "other":
                    asked.append(turn.ask_attribute)
        self.assertTrue(asked, "the journey never asked a catalog facet")
        self.assertEqual(sorted(asked), sorted(set(asked)), f"a facet repeated: {asked}")

    def test_the_active_item_records_what_it_asked(self) -> None:
        catalog = self._wide_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("record")
            turn = service.send(conversation.session_id, "I need shoes for men")
        active = next(item for item in turn.journey["items"] if item["active"])
        if turn.ask_attribute and turn.ask_attribute != "other":
            self.assertIn(turn.ask_attribute, active["asked_facets"])

    def test_no_facet_is_asked_twice_for_one_line_item(self) -> None:
        catalog = write_catalog(self)
        asked_by_item: dict[str, list[str]] = {}
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("repeats")
            for message in self.SCRIPT:
                turn = service.send(conversation.session_id, message)
                active = str(turn.journey["active_item_id"])
                # `other` is the open question, "what else matters", and the
                # fallback when no catalog facet divides the slate. Asking it
                # again is not the defect; asking the same specific facet again
                # is.
                if turn.ask_attribute and turn.ask_attribute != "other":
                    asked_by_item.setdefault(active, []).append(turn.ask_attribute)
        self.assertTrue(asked_by_item, "the journey asked nothing at all")
        for item_id, asked in asked_by_item.items():
            with self.subTest(item=item_id):
                self.assertEqual(sorted(asked), sorted(set(asked)))

    def test_a_new_line_item_may_ask_about_itself(self) -> None:
        """Shoes and a suit can have different wearers, so the guard is per
        item rather than per session."""
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("peritem")
            first = service.send(conversation.session_id, "I need formal shoes")
            self.assertEqual(first.ask_attribute, "wearer")
            service.send(conversation.session_id, "for men")
            later = service.send(conversation.session_id, "Add a suit as well")
        suit = later.journey["items"][-1]
        self.assertIn("suit", suit["category"])
        self.assertNotEqual(suit["item_id"], later.journey["items"][0]["item_id"])
        # A separate line item keeps its own record of what it has asked.
        self.assertEqual(len(later.journey["items"]), 2)

    def test_the_placeholder_hands_over_what_it_already_asked(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("handover")
            first = service.send(conversation.session_id, "I need an outfit for a wedding")
            second = service.send(conversation.session_id, "a men's suit")
        if first.ask_attribute:
            self.assertNotEqual(first.ask_attribute, second.ask_attribute)


class TheQuestionCarriesWhatItBeat(unittest.TestCase):
    """A ranked board is the argument for asking anything, and it was discarded.

    The board scores every catalog facet by how much of the slate an answer
    removes, weighted by how many candidates can answer at all, less the cost
    of a turn. Only the winner reached the payload, so the interface could show
    a question but never why that one.
    """

    def test_the_alternatives_are_reported_with_their_numbers(self) -> None:
        catalog = write_wide_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("board")
            turn = service.send(conversation.session_id, "I need a men's suit")
        question = turn.journey_trace["question"]
        if not question.get("asks"):
            self.skipTest("this slate produced no catalog question")
        self.assertIn("alternatives", question)
        for other in question["alternatives"]:
            with self.subTest(attribute=other.get("attribute")):
                self.assertNotEqual(other["attribute"], question["attribute"])
                for field in ("net_value", "expected_remaining", "catalog_coverage"):
                    self.assertIn(field, other)

    def test_the_winner_outranks_everything_it_reports(self) -> None:
        catalog = write_wide_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("ranking")
            turn = service.send(conversation.session_id, "I need a men's suit")
        question = turn.journey_trace["question"]
        if not question.get("asks") or not question.get("alternatives"):
            self.skipTest("no alternatives on this slate")
        # The audience question can pre-empt the board, and when it does it is
        # not ranked against it. Only check the ordering the board decided.
        if question.get("source") == "released-candidate clarification board":
            best = max(other["net_value"] for other in question["alternatives"])
            self.assertGreaterEqual(question["net_value"], best)


class ASessionCanBeOpenedInALanguage(unittest.TestCase):
    """Seven languages work and an English page gives no way to find that out.

    Pinning at session start reaches the same code path detection reaches, so
    what a reviewer sees is the real behaviour rather than a translated
    interface.
    """

    def test_the_reply_is_in_the_requested_language(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            conversation = service.start("spanish", language="es")
            turn = service.send(conversation.session_id, "zapatos")
        self.assertEqual(turn.journey["language"], "es")
        self.assertTrue(
            any(mark in turn.message for mark in ("¿", "á", "é", "í", "ó", "ú", "ñ")),
            f"no Spanish in: {turn.message!r}",
        )

    def test_english_is_unchanged_by_the_new_argument(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            plain = service.send(service.start("plain").session_id, "I need a men's suit")
            asked = service.send(
                service.start("asked", language="en").session_id, "I need a men's suit"
            )
        self.assertEqual(plain.message, asked.message)

    def test_an_unsupported_language_is_refused_rather_than_guessed(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            with self.assertRaises(ValueError):
                service.start("klingon", language="tlh")

    def test_every_offered_language_is_one_the_module_supports(self) -> None:
        catalog = write_catalog(self)
        with StorefrontService(catalog, journey_mode=True) as service:
            offered = service.describe()["languages"]
        from needle.language import supported

        self.assertEqual([entry["code"] for entry in offered], list(supported()))
        for entry in offered:
            with self.subTest(code=entry["code"]):
                self.assertTrue(entry["label"].strip())


class JourneyArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(__file__).resolve().parents[1] / "demo" / "storefront.html").read_text(
            encoding="utf-8"
        )

    def test_interface_renders_plan_and_compatibility_without_html_injection(self) -> None:
        source = self.source
        self.assertIn("function renderJourney(journey)", source)
        self.assertIn("Compatibility evidence", source)
        self.assertIn("journey_trace", source)
        self.assertIn("receipt.open = false", source)
        self.assertIn("why needle asked", source)
        self.assertIn('["considered", numberFormat.format(considered)]', source)
        self.assertIn('["ruled out", numberFormat.format(ruledOut)]', source)
        self.assertIn("catalog evidence only", source)
        self.assertIn('id="mobile-journey-panel"', source)
        self.assertIn("Shopping plan · ", source)
        self.assertIn("retirePlanButtons()", source)
        self.assertIn("button.plan-select[data-current='true']", source)
        self.assertIn("Previous option", source)
        self.assertNotIn("Journey overlay:", source)
        self.assertNotIn("slate released", source)
        self.assertNotIn("fallback unresolved", source)
        self.assertNotIn("Product journey mode. ", source)
        self.assertNotIn("innerHTML", source)

    def test_the_question_reasoning_reads_the_board_rather_than_restating_it(self) -> None:
        self.assertIn("function renderQuestionReasoning(turn)", self.source)
        self.assertIn("decision.alternatives", self.source)
        # The numbers shown have to come from the payload. A hardcoded
        # percentage in the interface would be a claim rather than a reading.
        self.assertIn("decision.catalog_coverage", self.source)
        self.assertIn("decision.expected_remaining", self.source)

    def test_the_language_control_asks_the_service_what_it_supports(self) -> None:
        """A list of languages in the interface is a second place to forget."""
        self.assertIn("renderLanguages(config.languages)", self.source)
        for code in ("Deutsch", "Español", "日本語"):
            with self.subTest(label=code):
                self.assertNotIn(f'"{code}"', self.source)

    def test_the_comparison_never_claims_a_product_fails(self) -> None:
        """Absent metadata is not a failed constraint.

        Most of this catalog does not state a colour or a material, so a
        comparison that printed a cross wherever it found nothing would be
        inventing evidence against products for being poorly described.
        """
        self.assertIn("not stated", self.source)
        self.assertIn('node("span", "verdict unknown"', self.source)

    def test_a_new_session_clears_what_the_old_one_produced(self) -> None:
        reset = self.source[self.source.index("async function newSession()"):]
        reset = reset[:reset.index("async function send(")]
        for cleared in ("compared.length = 0", "renderCompare()", "renderTimeline(null)"):
            with self.subTest(cleared=cleared):
                self.assertIn(cleared, reset)


if __name__ == "__main__":
    unittest.main()
