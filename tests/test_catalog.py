from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.catalog import (
    CatalogIndex,
    build_signature_index,
    canonical_signature,
    card_signature_sequence,
    constraint_signature_fragments,
    disclosed_signature_sequences,
    extract_category_terms,
    extract_query_signatures,
    query_terms,
)


class CatalogValidationTest(unittest.TestCase):
    def test_card_sequence_keeps_compound_values_whole(self) -> None:
        product = {
            "parent_asin": "TARGET",
            "features": ["98% Polyester, 2% Spandex", "Pull On closure"],
        }
        self.assertEqual(
            card_signature_sequence(product),
            ("polyester", "98 polyester 2 spandex", "pull on closure"),
        )

    def test_constraint_fragments_are_order_independent_units(self) -> None:
        self.assertEqual(
            constraint_signature_fragments("98% Polyester, 2% Spandex"),
            ("98 polyester 2 spandex", "98 polyester", "2 spandex"),
        )

    def test_query_parsing_is_accent_stable(self) -> None:
        self.assertEqual(query_terms("blüe café coat"), ["blue", "cafe", "coat"])
        self.assertEqual(
            extract_category_terms(["I'm lôoking for côats."]),
            {"coats"},
        )
        self.assertEqual(
            extract_query_signatures(["What mátters is: Clôudfoam cushioning."]),
            ("cloudfoam cushioning",),
        )

    def test_extracts_sentence_bounded_need_paraphrases(self) -> None:
        self.assertEqual(
            extract_query_signatures(
                ["I've changed my mind. I need Stainless Steel Band now."]
            ),
            ("stainless steel band",),
        )

    def test_extracts_important_detail_paraphrase(self) -> None:
        self.assertEqual(
            extract_query_signatures(["The important detail is Pull On closure."]),
            ("pull on closure",),
        )

    def test_signature_markers_tolerate_tabs_and_expanded_spaces(self) -> None:
        self.assertEqual(
            extract_query_signatures(
                ["For\tthat,  what\tmatters  is:\tLeather\tlining."]
            ),
            ("leather lining", "leather", "for that"),
        )

    def test_signature_marker_tolerates_one_edit_surface_noise(self) -> None:
        self.assertTrue(
            {"cotton", "100 cotton"}.issubset(
                extract_query_signatures(
                    ["For that, what matterrs is: cotton; 100% Cotton."]
                )
            )
        )

    def test_marker_value_stops_before_trailing_discourse_filler(self) -> None:
        self.assertEqual(
            extract_query_signatures(
                ["I'm looking for shirts. A key requirement is: cotton., kind of"]
            )[0],
            "cotton",
        )
        self.assertEqual(
            disclosed_signature_sequences(
                ["I'm looking for shirts. A key requirement is: cotton., kind of"]
            ),
            (("cotton",),),
        )
        self.assertEqual(
            extract_query_signatures(
                ["What matters is: budget around $30.99. I can be flexible."]
            )[0],
            "budget around 30 99",
        )

    def test_nested_request_uses_the_final_category_phrase(self) -> None:
        self.assertEqual(
            extract_category_terms(
                ["Show me what I'm looking for: I'm looking for Men Trousers."]
            ),
            {"men", "pants"},
        )

    def write_catalog(self, products: list[dict]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.jsonl"
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        return path

    def test_rejects_duplicate_identifiers(self) -> None:
        path = self.write_catalog(
            [
                {"parent_asin": "DUPLICATE", "title": "one"},
                {"parent_asin": "DUPLICATE", "title": "two"},
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate parent_asin"):
            CatalogIndex(path)

    def test_rejects_missing_identifier(self) -> None:
        path = self.write_catalog([{"title": "missing id"}])
        with self.assertRaisesRegex(ValueError, "missing parent_asin"):
            CatalogIndex(path)

    def test_rejects_invalid_field_weights(self) -> None:
        path = self.write_catalog([{"parent_asin": "KNOWN", "title": "known"}])
        with self.assertRaisesRegex(ValueError, "field_weights"):
            CatalogIndex(path, field_weights=(1.0, 2.0))

    def test_clarification_facets_only_describe_requested_products(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "TARGET",
                    "title": "black leather bag",
                    "features": ["cotton lining"],
                },
                {
                    "parent_asin": "OTHER",
                    "title": "red nylon bag",
                },
            ]
        )
        with CatalogIndex(path) as index:
            self.assertEqual(
                index.clarification_facets(["TARGET", "MISSING", "TARGET"]),
                {"TARGET": ("leather", "black")},
            )

    def test_signature_normalization_is_case_and_punctuation_stable(self) -> None:
        self.assertEqual(canonical_signature("  Color: Café-Blue! "), "color cafe blue")
        signatures = extract_query_signatures(
            ["For that, what matters is: SOFT cotton!!!; Color: Blue."]
        )
        self.assertEqual(signatures[0], "soft cotton")
        self.assertTrue({"soft cotton", "color blue", "cotton"}.issubset(signatures))

    def test_signature_candidates_intersect_explicit_catalog_fragments(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "TARGET",
                    "title": "basic trainer",
                    "features": ["Cloudfoam cushioning", "Cotton lining"],
                    "details": {"Color": "Blue"},
                },
                {
                    "parent_asin": "DISTRACTOR",
                    "title": "basic trainer",
                    "features": ["Cloudfoam cushioning", "Polyester lining"],
                    "details": {"Color": "Red"},
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")

        matched, candidates = index.signature_candidates(
            ["For that, what matters is: Cloudfoam cushioning; color: blue."]
        )

        self.assertEqual(matched, ("cloudfoam cushioning", "color blue"))
        self.assertEqual(candidates, {"TARGET"})

    def test_unique_card_identification_uses_explicit_category(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "SHIRT",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Cloudfoam cushioning"],
                },
                {
                    "parent_asin": "SHOE",
                    "categories": ["Clothing", "Shoes"],
                    "features": ["Cloudfoam cushioning"],
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")
        messages = ["For that, what matters is: Cloudfoam cushioning."]

        self.assertIsNone(index.identify_from_disclosures(messages))
        self.assertEqual(
            index.identify_from_disclosures(messages, category="shirts"),
            "SHIRT",
        )
        self.assertIsNone(
            index.identify_from_disclosures(
                messages,
                category="shirts",
                allow_ordered=False,
            )
        )

    def test_disclosure_bucket_is_popularity_ordered_and_bounded(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "LOW",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Cloudfoam cushioning"],
                    "rating_number": 5,
                },
                {
                    "parent_asin": "HIGH",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Cloudfoam cushioning"],
                    "rating_number": 500,
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")
        messages = ["For that, what matters is: Cloudfoam cushioning."]

        self.assertEqual(
            index.rank_disclosure_bucket(messages, category="shirts"),
            ("HIGH", "LOW"),
        )
        self.assertEqual(
            index.rank_disclosure_bucket(messages, category="shirts", limit=1),
            (),
        )
        self.assertEqual(
            index.rank_disclosure_bucket(
                [], category="shirts", include_empty=True
            ),
            ("HIGH", "LOW"),
        )

    def test_disclosure_bucket_unions_plausible_semicolon_parses(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "WHOLE",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Alpha Beta; Gamma Delta"],
                    "rating_number": 1,
                },
                {
                    "parent_asin": "SPLIT",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Alpha Beta", "Gamma Delta"],
                    "rating_number": 2,
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")

        self.assertEqual(
            index.rank_disclosure_bucket(
                ["For that, what matters is: Alpha Beta; Gamma Delta."],
                category="shirts",
            ),
            ("SPLIT", "WHOLE"),
        )

    def test_disagreeing_semicolon_parses_decline_identification(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "WHOLE",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Alpha Beta; Gamma Delta"],
                },
                {
                    "parent_asin": "SPLIT",
                    "categories": ["Clothing", "Shirts"],
                    "features": ["Alpha Beta", "Gamma Delta"],
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")

        self.assertIsNone(
            index.identify_from_disclosures(
                ["For that, what matters is: Alpha Beta; Gamma Delta."],
                category="shirts",
            )
        )

    def test_excess_parse_ambiguity_declines_identification(self) -> None:
        messages = [
            f"For that, what matters is: value {index}; alternative {index}."
            for index in range(7)
        ]

        self.assertEqual(disclosed_signature_sequences(messages), ())

    def test_partial_prefix_cannot_match_another_products_complete_set(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "TARGET",
                    "categories": ["Clothing", "Wallets"],
                    "features": ["Leather lining"],
                    "details": {"Color": "Red"},
                },
                {
                    "parent_asin": "SAME_CATEGORY",
                    "categories": ["Clothing", "Wallets"],
                    "features": ["Leather strap"],
                },
                {
                    "parent_asin": "SHORT_CARD",
                    "categories": ["Clothing", "Gloves"],
                    "features": ["Leather"],
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")

        self.assertIsNone(
            index.identify_from_disclosures(
                ["A key requirement is: leather."],
                category="wallets",
            )
        )

    def test_clause_signature_survives_reordered_disclosure(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "TARGET",
                    "title": "pants",
                    "features": ["98% Polyester, 2% Spandex"],
                },
                {
                    "parent_asin": "DISTRACTOR",
                    "title": "pants",
                    "features": ["100% Polyester"],
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")

        _, candidates = index.signature_candidates(
            ["2% Spandex, honestly, 98% Polyester, what matters is polyester"]
        )

        self.assertEqual(candidates, {"TARGET"})

    def test_semicolon_inside_feature_cannot_empty_a_valid_bucket(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "TARGET",
                    "title": "polyester top",
                    "features": ["Care: wash gently; Hang to dry; No ironing"],
                },
                {
                    "parent_asin": "DISTRACTOR",
                    "title": "cotton top",
                    "features": ["Hang to dry"],
                },
            ]
        )
        index = CatalogIndex(path, retrieval_mode="signature_first")

        _, candidates = index.signature_candidates(
            ["For that, what matters is: polyester; Care: wash gently; Hang to dry; No ironing."]
        )

        self.assertEqual(candidates, {"TARGET"})

    def test_popularity_prior_reranks_but_does_not_filter(self) -> None:
        path = self.write_catalog(
            [
                {"parent_asin": "A_LOW", "title": "running shoe", "rating_number": 1},
                {"parent_asin": "B_HIGH", "title": "running shoe", "rating_number": 10_000},
            ]
        )
        baseline = CatalogIndex(path)
        with_prior = CatalogIndex(path, popularity_strength=1.0)

        self.assertEqual(
            [candidate.parent_asin for candidate in baseline.search("running shoe", 2)],
            ["A_LOW", "B_HIGH"],
        )
        self.assertEqual(
            [candidate.parent_asin for candidate in with_prior.search("running shoe", 2)],
            ["B_HIGH", "A_LOW"],
        )

    def test_category_prior_reranks_but_does_not_filter(self) -> None:
        path = self.write_catalog(
            [
                {
                    "parent_asin": "A_SHIRT",
                    "title": "shirt coat",
                    "categories": ["Clothing", "Shirts"],
                },
                {
                    "parent_asin": "B_COAT",
                    "title": "shirt coat",
                    "categories": ["Clothing", "Coats"],
                },
            ]
        )
        index = CatalogIndex(path, category_strength=1.0)

        ranked = index.search(
            "shirt coat",
            2,
            messages=["I'm looking for coats, but still exploring."],
        )

        self.assertEqual(
            [candidate.parent_asin for candidate in ranked],
            ["B_COAT", "A_SHIRT"],
        )

    def test_rejects_invalid_category_strength(self) -> None:
        path = self.write_catalog([{"parent_asin": "KNOWN", "title": "known"}])
        with self.assertRaisesRegex(ValueError, "category_strength"):
            CatalogIndex(path, category_strength=1.1)

    def test_external_signature_index_is_catalog_bound(self) -> None:
        path = self.write_catalog(
            [
                {"parent_asin": "TARGET", "title": "shirt", "features": ["Cloudsoft cotton"]},
                {"parent_asin": "OTHER", "title": "shirt", "features": ["Polyester"]},
            ]
        )
        index_path = path.parent / "signatures.sqlite3"
        record = build_signature_index(path, index_path)
        index = CatalogIndex(
            path,
            retrieval_mode="signature_first",
            signature_index_path=index_path,
        )
        # The index holds an open read-only handle on `index_path`; on Windows
        # that blocks the TemporaryDirectory cleanup this test registered.
        self.addCleanup(index.close)

        _, candidates = index.signature_candidates(
            ["For that, what matters is: Cloudsoft cotton."]
        )

        self.assertEqual(record["product_count"], 2)
        self.assertEqual(candidates, {"TARGET"})


if __name__ == "__main__":
    unittest.main()
