from __future__ import annotations

import unittest

from needle.presets import PRIMARY_AGENT_KWARGS, ROLLBACK_AGENT_KWARGS


class PresetTest(unittest.TestCase):
    def test_primary_is_the_measured_signature_configuration(self) -> None:
        self.assertEqual(PRIMARY_AGENT_KWARGS["retrieval_mode"], "signature_first")
        self.assertEqual(PRIMARY_AGENT_KWARGS["signature_bucket_limit"], 100)
        self.assertEqual(PRIMARY_AGENT_KWARGS["popularity_strength"], 0.30)
        self.assertEqual(PRIMARY_AGENT_KWARGS["category_strength"], 1.00)
        self.assertIs(PRIMARY_AGENT_KWARGS["exclude_seen"], True)
        self.assertEqual(PRIMARY_AGENT_KWARGS["override_policy"], "retract_stated")
        self.assertEqual(PRIMARY_AGENT_KWARGS["lexical_mode"], "none")
        self.assertEqual(PRIMARY_AGENT_KWARGS["slate_size"], 10)
        self.assertEqual(PRIMARY_AGENT_KWARGS["emission_mode"], "promote")
        self.assertEqual(PRIMARY_AGENT_KWARGS["release_turn"], 8)

    def test_rollback_assumes_least(self) -> None:
        """The rollback drops both things the primary asserts about the protocol.

        Signature retrieval assumes the customer states catalog-grounded values;
        promotion assumes the intent card is built from the target's own fields
        and disclosed in order. Each is measured, and each is an assumption, so
        the known-good fallback carries neither.
        """
        expected = dict(PRIMARY_AGENT_KWARGS)
        expected.pop("signature_bucket_limit")
        expected.pop("release_turn")
        expected["retrieval_mode"] = "sparse"
        expected["emission_mode"] = "slate"
        self.assertEqual(dict(ROLLBACK_AGENT_KWARGS), expected)

    def test_presets_are_immutable(self) -> None:
        with self.assertRaises(TypeError):
            PRIMARY_AGENT_KWARGS["slate_size"] = 1  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
