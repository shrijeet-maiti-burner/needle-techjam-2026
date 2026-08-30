from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from needle.presets import PRIMARY_AGENT_KWARGS

from storefront.catalog_view import CatalogView
from storefront.service import StorefrontService


PRODUCTS: tuple[dict[str, object], ...] = (
    {
        "parent_asin": "BELT",
        "title": "Classic Leather Belt",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Accessories", "Belts"],
        "features": ["100% Leather", "Buckle closure"],
        "details": {"Department": "Mens"},
        "store": "Northgate",
        "description": ["A plain belt."],
        "price": 27.99,
        "average_rating": 4.7,
        "rating_number": 5531,
    },
    {
        "parent_asin": "SHIRT",
        "title": "Soft Cotton Shirt",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts"],
        "features": ["Cloudsoft cotton"],
        "details": {"Color": "Café Blue"},
        "store": "Westlake",
        "description": [],
        "price": None,
        "average_rating": 4.1,
        "rating_number": 12,
    },
    {
        "parent_asin": "SHOE",
        "title": "Running Shoe",
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Belts"],
        "features": [],
        "details": {},
        "store": "",
        "description": ["Road running trainer."],
        "price": "$45.00",
        "average_rating": 9.9,
        "rating_number": -4,
    },
)


def write_catalog(case: unittest.TestCase, products=PRODUCTS) -> Path:
    directory = tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    path = Path(directory.name) / "catalog.jsonl"
    # A blank line is legal in the released catalog's format and must not shift
    # a byte offset by one record.
    path.write_text(
        "\n".join(json.dumps(product) for product in products) + "\n\n",
        encoding="utf-8",
    )
    return path


class CatalogViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.view = CatalogView(write_catalog(self))

    def test_offsets_cover_every_product_and_skip_blank_lines(self) -> None:
        self.assertEqual(self.view.product_count, 3)
        self.assertEqual(
            set(self.view.offsets), {"BELT", "SHIRT", "SHOE"}
        )

    def test_seeking_an_offset_returns_that_product(self) -> None:
        """The offset index is only useful if it lands on the right line."""
        for parent_asin in ("BELT", "SHIRT", "SHOE"):
            with self.subTest(parent_asin=parent_asin):
                record = self.view.raw(parent_asin)
                assert record is not None
                self.assertEqual(record["parent_asin"], parent_asin)

    def test_card_carries_the_display_fields(self) -> None:
        card = self.view.card("BELT")
        self.assertEqual(card.title, "Classic Leather Belt")
        self.assertEqual(card.store, "Northgate")
        self.assertEqual(card.price, 27.99)
        self.assertEqual(card.average_rating, 4.7)
        self.assertEqual(card.rating_number, 5531)
        self.assertIn("100% Leather", card.features)
        self.assertTrue(card.category_path.endswith("Belts"))

    def test_unknown_identifier_degrades_to_an_identifier_card(self) -> None:
        """A catalog mismatch must not take the turn down with it."""
        card = self.view.card("NOT_IN_CATALOG")
        self.assertEqual(card.parent_asin, "NOT_IN_CATALOG")
        self.assertEqual(card.title, "NOT_IN_CATALOG")
        self.assertIsNone(card.price)
        self.assertEqual(card.categories, ())

    def test_absent_and_unusable_values_are_reported_as_absent(self) -> None:
        shirt = self.view.card("SHIRT")
        self.assertIsNone(shirt.price)
        shoe = self.view.card("SHOE")
        self.assertEqual(shoe.price, 45.0)  # "$45.00" is still a price
        self.assertIsNone(shoe.average_rating)  # 9.9 is not on a five point scale
        self.assertEqual(shoe.rating_number, 0)  # a negative count is not a count

    def test_matched_terms_cite_the_first_field_that_carries_them(self) -> None:
        card = self.view.card("BELT", terms=["leather", "belts", "northgate"])
        cited = {term: field for term, field, _ in card.matched}
        self.assertEqual(cited["leather"], "title")
        self.assertEqual(cited["belts"], "categories")
        self.assertEqual(cited["northgate"], "store")

    def test_a_term_absent_from_the_product_is_not_cited(self) -> None:
        card = self.view.card("BELT", terms=["cotton"])
        self.assertEqual(card.matched, ())

    def test_matching_folds_accents_the_way_retrieval_does(self) -> None:
        """`cafe` must cite `Café Blue`, or the chip contradicts the retriever."""
        card = self.view.card("SHIRT", terms=["cafe"])
        self.assertEqual([term for term, _, _ in card.matched], ["cafe"])

    def test_superseded_values_are_cited_but_marked_stale(self) -> None:
        card = self.view.card("SHIRT", terms=["cotton"], stale_terms=["cotton"])
        self.assertEqual(card.matched, (("cotton", "title", True),))

    def test_a_live_term_alongside_a_stale_one_is_not_marked_stale(self) -> None:
        card = self.view.card(
            "SHIRT", terms=["cotton", "cloudsoft"], stale_terms=["cotton"]
        )
        self.assertEqual(
            card.matched,
            (("cotton", "title", True), ("cloudsoft", "features", False)),
        )

    def test_common_categories_are_read_from_the_catalog(self) -> None:
        categories = self.view.common_categories(2)
        self.assertEqual(categories[0], "Belts")  # two products, versus one
        self.assertNotIn("Men", categories)  # not a leaf

    def test_a_shallow_category_is_not_offered_as_a_suggestion(self) -> None:
        """The released catalog files 1136 products directly under "Westlake".

        It is a real category and a useless thing to suggest, and it outranks
        every genuine leaf on count. Depth is what separates them.
        """
        shallow = [
            {"parent_asin": f"SHALLOW{index}", "title": "thing", "categories": ["Root", "Broad"]}
            for index in range(5)
        ]
        view = CatalogView(write_catalog(self, (*PRODUCTS, *shallow)))
        categories = view.common_categories(6)
        self.assertNotIn("Broad", categories)
        self.assertIn("Belts", categories)


class StorefrontServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = write_catalog(self)
        self.service = StorefrontService(self.catalog)
        self.addCleanup(self.service.close)

    def test_it_runs_the_primary_preset_with_no_deviation(self) -> None:
        for key, value in PRIMARY_AGENT_KWARGS.items():
            with self.subTest(key=key):
                self.assertEqual(self.service.agent_kwargs[key], value)
        self.assertEqual(self.service.deviations, {})

    def test_an_override_is_applied_and_reported(self) -> None:
        service = StorefrontService(self.catalog, overrides={"slate_size": 3})
        self.addCleanup(service.close)
        self.assertEqual(service.agent_kwargs["slate_size"], 3)
        self.assertEqual(
            service.deviations["slate_size"],
            {"primary": PRIMARY_AGENT_KWARGS["slate_size"], "effective": 3},
        )

    def test_an_override_the_agent_does_not_accept_fails_loudly(self) -> None:
        """A stale flag must not be silently ignored into a wrong demo."""
        with self.assertRaisesRegex(ValueError, "does not accept override"):
            StorefrontService(self.catalog, overrides={"not_a_real_keyword": 1})

    def test_a_missing_catalog_is_refused_at_construction(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "catalog not found"):
            StorefrontService(self.catalog.parent / "absent.jsonl")

    def test_a_turn_returns_a_grounded_slate(self) -> None:
        conversation = self.service.start()
        turn = self.service.send(conversation.session_id, "I need a leather belt")
        self.assertEqual(turn.turn, 1)
        self.assertFalse(turn.degraded)
        self.assertTrue(turn.within_scored_budget)
        self.assertTrue(turn.cards)
        self.assertTrue(
            all(card["parent_asin"] in {"BELT", "SHIRT", "SHOE"} for card in turn.cards)
        )

    def test_an_empty_message_is_rejected_rather_than_sent(self) -> None:
        conversation = self.service.start()
        with self.assertRaisesRegex(ValueError, "message is empty"):
            self.service.send(conversation.session_id, "   ")

    def test_beliefs_track_what_the_customer_disclosed(self) -> None:
        conversation = self.service.start()
        self.service.send(conversation.session_id, "I'm looking for Accessories Belts.")
        turn = self.service.send(
            conversation.session_id, "For that, what matters is: leather."
        )
        self.assertIn(
            "leather", [entry["value"] for entry in turn.beliefs["wanted"]]
        )

    def test_turns_past_the_scored_budget_are_marked_not_truncated(self) -> None:
        """A tester is not bound by ten turns; the interface just says so."""
        conversation = self.service.start()
        for index in range(11):
            turn = self.service.send(conversation.session_id, f"belt number {index}")
        self.assertEqual(turn.turn, 11)
        self.assertFalse(turn.within_scored_budget)

    def test_evidence_cites_disclosed_values_not_message_scaffolding(self) -> None:
        """"For that, what matters is" must never reach a card as evidence.

        Filtering the message by corpus frequency does not achieve this: in the
        released catalog `what` sits on 1968 products and `leather` on 7503, so
        any threshold that drops the first drops the second. Sourcing the terms
        from what the agent extracted excludes scaffolding structurally.
        """
        conversation = self.service.start()
        self.service.send(conversation.session_id, "I'm looking for Accessories Belts.")
        turn = self.service.send(
            conversation.session_id, "For that, what matters is: leather."
        )
        cited = {hit["term"] for card in turn.cards for hit in card["matched"]}
        self.assertIn("leather", cited)
        self.assertNotIn("what", cited)
        self.assertNotIn("matters", cited)

    def test_evidence_falls_back_to_the_message_when_nothing_is_extracted(self) -> None:
        conversation = self.service.start()
        turn = self.service.send(conversation.session_id, "running shoe")
        cited = {hit["term"] for card in turn.cards for hit in card["matched"]}
        self.assertTrue(cited)

    def test_stale_terms_exclude_values_an_active_constraint_restates(self) -> None:
        beliefs = {
            "wanted": [{"attribute": "material", "value": "leather", "turn": 3}],
            "excluded": [],
            "superseded": [
                {"attribute": "material", "value": "leather", "turn": 1},
                {"attribute": "material", "value": "cotton", "turn": 2},
            ],
        }
        self.assertEqual(StorefrontService._stale_terms(beliefs), ["cotton"])

    def test_sessions_are_bounded_and_evict_the_least_recently_used(self) -> None:
        service = StorefrontService(self.catalog, max_sessions=2)
        self.addCleanup(service.close)
        first = service.start().session_id
        second = service.start().session_id
        service.send(first, "belt")  # first becomes the most recent
        third = service.start().session_id
        self.assertIsNone(service.conversation(second))
        self.assertIsNotNone(service.conversation(first))
        self.assertIsNotNone(service.conversation(third))

    def test_turns_serve_correctly_from_threads_that_did_not_build_the_agent(self) -> None:
        """Regression: the agent's SQLite connection is bound to one thread.

        Served from a threading HTTP server without pinning, every turn raised
        inside `respond`, was absorbed by its never-raise guard, and returned an
        empty slate in under a millisecond. Nothing else in the interface would
        have reported that, so this asserts on `degraded` as well as the slate.
        """
        self.service.agent  # construct before the workers start
        results: list[object] = []
        errors: list[BaseException] = []

        def drive(index: int) -> None:
            try:
                conversation = self.service.start()
                turn = self.service.send(conversation.session_id, "leather belt")
                results.append((turn.degraded, len(turn.cards)))
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        workers = [threading.Thread(target=drive, args=(index,)) for index in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=60)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 6)
        for degraded, card_count in results:
            self.assertFalse(degraded)
            self.assertGreater(card_count, 0)

    def test_describe_reports_the_facts_the_interface_shows(self) -> None:
        described = self.service.describe()
        self.assertEqual(described["product_count"], 3)
        self.assertEqual(described["deviations"], {})
        self.assertEqual(described["scored_turn_budget"], 10)
        self.assertIn("Belts", described["suggestions"])

    def test_close_is_idempotent(self) -> None:
        self.service.agent
        self.service.close()
        self.service.close()


if __name__ == "__main__":
    unittest.main()
