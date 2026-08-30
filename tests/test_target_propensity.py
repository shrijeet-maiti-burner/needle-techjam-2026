from __future__ import annotations

import unittest

from scripts.target_propensity import (
    FEATURE_NAMES,
    PairwiseLinearModel,
    build_feature_table,
    metadata_features,
    stratified_folds,
)


class TargetPropensityTests(unittest.TestCase):
    def test_feature_allowlist_contains_no_identity_or_text_tokens(self) -> None:
        forbidden = {
            "parent_asin",
            "title_tokens",
            "store_tokens",
            "category_tokens",
            "feature_tokens",
            "description_tokens",
            "brand",
        }
        self.assertTrue(forbidden.isdisjoint(FEATURE_NAMES))

    def test_metadata_features_are_finite_and_fixed_width(self) -> None:
        features = metadata_features(
            {
                "parent_asin": "MUST_NOT_APPEAR",
                "title": "some arbitrary product identity",
                "features": ["one", "two"],
                "description": ["description"],
                "price": "not-a-number",
                "categories": ["root", "leaf"],
                "details": {"Date First Available": "March 2, 2020"},
                "average_rating": float("nan"),
                "rating_number": -5,
            },
            store_frequency=3,
        )
        self.assertEqual(len(features), len(FEATURE_NAMES))
        self.assertEqual(features[0], 0.0)
        self.assertEqual(features[1], 0.0)
        self.assertEqual(features[3], 0.0)
        self.assertEqual(features[4], 2020.0)

    def test_feature_table_and_model_are_deterministic(self) -> None:
        products = {
            "a": {"rating_number": 100, "store": "same", "features": ["x"]},
            "b": {"rating_number": 1, "store": "same", "features": []},
        }
        first = build_feature_table(products)
        second = build_feature_table(products)
        self.assertEqual(first, second)
        weights = (1.0,) + (0.0,) * (len(FEATURE_NAMES) - 1)
        model = PairwiseLinearModel(weights)
        self.assertGreater(model.score(first.standardized("a")), model.score(first.standardized("b")))

    def test_stratified_folds_cover_every_sample_once(self) -> None:
        samples = [
            {"sample_id": f"s{index}", "scenario_type": scenario}
            for index, scenario in enumerate(("buying", "buying", "browsing", "browsing", "boundary"))
        ]
        folds = stratified_folds(samples, count=3)
        flattened = [index for fold in folds for index in fold]
        self.assertEqual(sorted(flattened), list(range(len(samples))))
        self.assertEqual(len(flattened), len(set(flattened)))


if __name__ == "__main__":
    unittest.main()
