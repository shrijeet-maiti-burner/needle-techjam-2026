from __future__ import annotations

import unittest

from scripts.run_unseen_proxy import build_proxy_samples


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


if __name__ == "__main__":
    unittest.main()
