from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.catalog import CatalogIndex, canonical_signature, extract_query_signatures


class CatalogValidationTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
