from __future__ import annotations

import unittest

from needle.presets import PRIMARY_AGENT_KWARGS, ROLLBACK_AGENT_KWARGS


class PresetTest(unittest.TestCase):
    def test_primary_is_the_measured_signature_configuration(self) -> None:
        self.assertEqual(PRIMARY_AGENT_KWARGS["retrieval_mode"], "signature_first")
        self.assertEqual(PRIMARY_AGENT_KWARGS["signature_bucket_limit"], 500)
        self.assertEqual(PRIMARY_AGENT_KWARGS["popularity_strength"], 0.30)
        self.assertEqual(PRIMARY_AGENT_KWARGS["category_strength"], 1.00)
        self.assertIs(PRIMARY_AGENT_KWARGS["exclude_seen"], True)
        self.assertEqual(PRIMARY_AGENT_KWARGS["override_policy"], "retract_stated")
        self.assertEqual(PRIMARY_AGENT_KWARGS["lexical_mode"], "none")
        self.assertEqual(PRIMARY_AGENT_KWARGS["slate_size"], 10)
        self.assertIs(PRIMARY_AGENT_KWARGS["identify_from_disclosures"], True)
        self.assertIs(PRIMARY_AGENT_KWARGS["adaptive_slate"], True)
        self.assertEqual(PRIMARY_AGENT_KWARGS["early_slate_size"], 1)
        self.assertEqual(PRIMARY_AGENT_KWARGS["full_slate_turn"], 5)
        self.assertEqual(PRIMARY_AGENT_KWARGS["full_slate_constraints"], 4)
        self.assertIs(PRIMARY_AGENT_KWARGS["correct_unmatched_terms"], True)
        self.assertEqual(PRIMARY_AGENT_KWARGS["correction_scope"], "structured")
        self.assertIs(PRIMARY_AGENT_KWARGS["promote_disclosure_bucket"], True)
        self.assertEqual(PRIMARY_AGENT_KWARGS["promotion_bucket_limit"], 50000)
        self.assertIs(PRIMARY_AGENT_KWARGS["promote_opening_category"], True)

    def test_rollback_removes_only_catalog_signature_promotion(self) -> None:
        self.assertEqual(ROLLBACK_AGENT_KWARGS["retrieval_mode"], "sparse")
        self.assertNotIn("signature_bucket_limit", ROLLBACK_AGENT_KWARGS)
        self.assertNotIn("identify_from_disclosures", ROLLBACK_AGENT_KWARGS)
        self.assertNotIn("adaptive_slate", ROLLBACK_AGENT_KWARGS)
        self.assertNotIn("promote_disclosure_bucket", ROLLBACK_AGENT_KWARGS)

    def test_presets_are_immutable(self) -> None:
        with self.assertRaises(TypeError):
            PRIMARY_AGENT_KWARGS["slate_size"] = 1  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
