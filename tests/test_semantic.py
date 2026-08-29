from __future__ import annotations

import unittest

from needle.contracts import Candidate
from needle.semantic import (
    LexicalNormalizer,
    NoOpSemanticReranker,
    fuzzy_match,
    normalize_text,
)


class NoOpSemanticRerankerTest(unittest.TestCase):
    def test_preserves_candidate_order_and_values(self) -> None:
        candidates = [Candidate("first", 2.0), Candidate("second", 1.0)]
        self.assertEqual(NoOpSemanticReranker().rerank(candidates, "query"), candidates)


class NormalizeTextTest(unittest.TestCase):
    def test_folds_case_accents_and_punctuation(self) -> None:
        self.assertEqual(normalize_text("Café-Blue, SIZE/M!"), "cafe blue size m")

    def test_is_idempotent(self) -> None:
        once = normalize_text("Núñez  Slim-Fit  T-Shirt")
        self.assertEqual(normalize_text(once), once)

    def test_collapses_whitespace_and_handles_empty(self) -> None:
        self.assertEqual(normalize_text("  a\t b\n"), "a b")
        self.assertEqual(normalize_text(""), "")

    def test_preserves_meaning_carrying_tokens(self) -> None:
        # normalization must not strip negation or other meaning-changing words
        self.assertEqual(normalize_text("NOT leather"), "not leather")
        self.assertIn("without", normalize_text("shoes without laces").split())

    def test_expands_negative_contractions_so_negation_stays_explicit(self) -> None:
        # apostrophe must not be split to a space; the negation word must survive.
        self.assertEqual(normalize_text("I don't want leather"), "i do not want leather")
        self.assertIn("not", normalize_text("won't need wool").split())

    def test_handles_straight_and_curly_apostrophes_identically(self) -> None:
        straight = normalize_text("I don't want leather")
        curly = normalize_text("I don’t want leather")
        self.assertEqual(straight, curly)
        self.assertIn("not", curly.split())

    def test_non_contraction_apostrophes_are_joined_not_split(self) -> None:
        self.assertEqual(normalize_text("men's slim-fit shirt"), "mens slim fit shirt")


class LexicalNormalizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = LexicalNormalizer()

    def test_expansion_is_additive_and_order_preserving(self) -> None:
        expanded = self.normalizer.expand_query("Blue Sneakers").split()
        self.assertEqual(expanded[:2], ["blue", "sneakers"])
        self.assertIn("shoes", expanded)

    def test_original_tokens_are_always_a_subset_of_the_result(self) -> None:
        for query in ("red wool coat", "sneakers", "no polyester pajamas", ""):
            base = set(self.normalizer.normalize(query).split())
            result = set(self.normalizer.expand_query(query).split())
            self.assertTrue(base <= result, query)

    def test_expansion_does_not_duplicate_tokens(self) -> None:
        expanded = self.normalizer.expand_query("shoes sneakers").split()
        self.assertEqual(expanded.count("shoes"), 1)
        self.assertEqual(expanded.count("sneakers"), 1)

    def test_unknown_tokens_pass_through_unchanged(self) -> None:
        self.assertEqual(self.normalizer.expand_query("crimson gabardine"), "crimson gabardine")

    def test_negation_survives_normalization_and_expansion(self) -> None:
        self.assertIn("not", self.normalizer.expand_query("not leather").split())
        self.assertIn("not", self.normalizer.expand_query("I don't want leather sneakers").split())

    def test_custom_expansions_replace_the_default_map(self) -> None:
        custom = LexicalNormalizer({"parka": ("coat",)})
        self.assertEqual(custom.expand_query("warm parka"), "warm parka coat")
        self.assertEqual(custom.expand_query("blue sneakers"), "blue sneakers")


class FuzzyMatchTest(unittest.TestCase):
    VOCAB = ("shirt", "shoes", "hoodie", "polyester", "cotton")

    def test_exact_match_returns_itself(self) -> None:
        self.assertEqual(fuzzy_match("cotton", self.VOCAB), "cotton")

    def test_close_typo_matches(self) -> None:
        self.assertEqual(fuzzy_match("polyeter", self.VOCAB), "polyester")
        self.assertEqual(fuzzy_match("cottn", self.VOCAB), "cotton")

    def test_unrelated_term_returns_none(self) -> None:
        self.assertIsNone(fuzzy_match("umbrella", self.VOCAB))

    def test_empty_inputs_return_none(self) -> None:
        self.assertIsNone(fuzzy_match("", self.VOCAB))
        self.assertIsNone(fuzzy_match("shirt", ()))

    def test_is_deterministic(self) -> None:
        self.assertEqual(fuzzy_match("hoodei", self.VOCAB), fuzzy_match("hoodei", self.VOCAB))


class LexicalRobustnessMatrixTest(unittest.TestCase):
    """Skeleton robustness matrix for the semantic path.

    EXP-010 fills this with the full slice set and target-recall / target-removal
    gates against real catalog data. Here it only pins the normalizer's
    meaning-preserving vs meaning-changing contract so a regression is caught early.
    """

    normalizer = LexicalNormalizer()

    MEANING_PRESERVING = (
        ("case", "Blue Cotton Shirt", "blue cotton shirt"),
        ("accent", "outerwear", "oûterwear"),
        ("punctuation", "size medium, slim fit", "size medium slim fit"),
        ("synonym", "sneakers", "shoes sneakers"),
        ("word_order", "cotton black shirt", "black shirt cotton"),
        ("contraction", "I do not want leather", "I don't want leather"),
        ("curly_apostrophe", "I don't want leather", "I don’t want leather"),
    )
    MEANING_CHANGING = (
        ("negation", "leather", "not leather"),
        ("attribute", "black shoes", "white shoes"),
        ("exclusion", "wool coat", "wool coat without hood"),
    )

    def test_meaning_preserving_variants_share_their_token_set(self) -> None:
        for label, base, variant in self.MEANING_PRESERVING:
            with self.subTest(label=label):
                base_tokens = set(self.normalizer.expand_query(base).split())
                variant_tokens = set(self.normalizer.expand_query(variant).split())
                self.assertEqual(base_tokens, variant_tokens)

    def test_meaning_changing_variants_are_not_equated(self) -> None:
        for label, base, variant in self.MEANING_CHANGING:
            with self.subTest(label=label):
                self.assertNotEqual(
                    self.normalizer.expand_query(base),
                    self.normalizer.expand_query(variant),
                )


if __name__ == "__main__":
    unittest.main()
