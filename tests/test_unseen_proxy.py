from __future__ import annotations

import unittest

from scripts.run_unseen_proxy import build_matched_proxy_samples, build_proxy_samples


class UnseenProxyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.public = [
            {
                "scenario_type": "buying",
                "user_profile": {"summary": "first"},
                "ground_truth": {"parent_asin": "public-a"},
            },
            {
                "scenario_type": "browsing",
                "user_profile": {"summary": "second"},
                "ground_truth": {"parent_asin": "public-b"},
            },
        ]

    def test_excludes_every_public_target(self) -> None:
        samples, _ = build_proxy_samples(
            {"public-a", "public-b", "fresh-a", "fresh-b"},
            self.public,
            sample_count=2,
            seed="fixed",
        )
        targets = {sample["ground_truth"]["parent_asin"] for sample in samples}
        self.assertEqual(targets, {"fresh-a", "fresh-b"})

    def test_selection_is_deterministic_and_seeded(self) -> None:
        catalog = {f"item-{index}" for index in range(20)}
        first = build_proxy_samples(catalog, self.public, sample_count=8, seed="a")
        repeated = build_proxy_samples(catalog, self.public, sample_count=8, seed="a")
        other = build_proxy_samples(catalog, self.public, sample_count=8, seed="b")
        self.assertEqual(first, repeated)
        self.assertNotEqual(first[1], other[1])

    def test_preserves_released_scenario_marginal_cycle(self) -> None:
        samples, _ = build_proxy_samples(
            {f"item-{index}" for index in range(10)},
            self.public,
            sample_count=4,
            seed="fixed",
        )
        self.assertEqual(
            [sample["scenario_type"] for sample in samples],
            ["buying", "browsing", "buying", "browsing"],
        )

    def test_rejects_impossible_sample_count(self) -> None:
        with self.assertRaises(ValueError):
            build_proxy_samples({"public-a"}, self.public, sample_count=1, seed="fixed")

    def test_matched_selection_is_disjoint_and_reproducible(self) -> None:
        products = {
            "public-a": {"parent_asin": "public-a", "rating_number": 100, "price": 5, "categories": ["Coats"]},
            "public-b": {"parent_asin": "public-b", "rating_number": 2, "categories": ["Shoes"]},
            **{
                f"fresh-{index}": {
                    "parent_asin": f"fresh-{index}",
                    "rating_number": 100 if index % 2 == 0 else 2,
                    "price": 5 if index % 2 == 0 else None,
                    "categories": ["Coats" if index % 2 == 0 else "Shoes"],
                }
                for index in range(12)
            },
        }
        first = build_matched_proxy_samples(products, self.public, sample_count=2, seed="fixed")
        repeated = build_matched_proxy_samples(products, self.public, sample_count=2, seed="fixed")
        other = build_matched_proxy_samples(products, self.public, sample_count=2, seed="other")

        self.assertEqual(first, repeated)
        self.assertNotEqual(first[1], other[1])
        targets = {sample["ground_truth"]["parent_asin"] for sample in first[0]}
        self.assertFalse(targets.intersection({"public-a", "public-b"}))
        self.assertEqual(first[2]["category_match_fraction"], 1.0)
        self.assertEqual(first[2]["fallback_counts"], {"exact": 2})

    def test_matched_selection_rejects_oversized_panel(self) -> None:
        products = {
            "public-a": {"parent_asin": "public-a"},
            "public-b": {"parent_asin": "public-b"},
            "fresh-a": {"parent_asin": "fresh-a"},
            "fresh-b": {"parent_asin": "fresh-b"},
            "fresh-c": {"parent_asin": "fresh-c"},
        }
        with self.assertRaisesRegex(ValueError, "public panel size"):
            build_matched_proxy_samples(
                products,
                self.public,
                sample_count=3,
                seed="fixed",
            )

    def test_matched_selection_records_fallback_without_leaking_ids(self) -> None:
        products = {
            "public-a": {"parent_asin": "public-a", "rating_number": 100, "price": 5, "categories": ["Coats"]},
            "public-b": {"parent_asin": "public-b", "rating_number": 2, "categories": ["Shoes"]},
            "fresh-a": {"parent_asin": "fresh-a", "rating_number": 100, "price": 5, "categories": ["Other"]},
            "fresh-b": {"parent_asin": "fresh-b", "rating_number": 2, "categories": ["Other"]},
        }
        _, _, metadata = build_matched_proxy_samples(
            products,
            self.public,
            sample_count=2,
            seed="fixed",
        )

        serialized = str(metadata)
        self.assertNotIn("fresh-a", serialized)
        self.assertNotIn("fresh-b", serialized)
        self.assertEqual(metadata["fallback_counts"], {"rating-price": 2})


if __name__ == "__main__":
    unittest.main()
