from __future__ import annotations

import unittest

from needle.presets import PRIMARY_AGENT_KWARGS, ROLLBACK_AGENT_KWARGS


class PresetTest(unittest.TestCase):
    def test_primary_is_the_measured_signature_configuration(self) -> None:
        self.assertEqual(PRIMARY_AGENT_KWARGS["retrieval_mode"], "signature_first")
        self.assertEqual(PRIMARY_AGENT_KWARGS["signature_bucket_limit"], 100)
        self.assertEqual(PRIMARY_AGENT_KWARGS["popularity_strength"], 0.20)
        self.assertEqual(PRIMARY_AGENT_KWARGS["override_policy"], "preserve_subject")
        self.assertEqual(PRIMARY_AGENT_KWARGS["lexical_mode"], "none")
        self.assertEqual(PRIMARY_AGENT_KWARGS["slate_size"], 10)

    def test_rollback_removes_only_catalog_signature_promotion(self) -> None:
        expected = dict(PRIMARY_AGENT_KWARGS)
        expected.pop("signature_bucket_limit")
        expected["retrieval_mode"] = "sparse"
        self.assertEqual(dict(ROLLBACK_AGENT_KWARGS), expected)

    def test_presets_are_immutable(self) -> None:
        with self.assertRaises(TypeError):
            PRIMARY_AGENT_KWARGS["slate_size"] = 1  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
