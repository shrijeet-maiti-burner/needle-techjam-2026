from __future__ import annotations

import random
import unittest

from robustness.perturb import (
    ALL_KINDS,
    SURFACE_KINDS,
    Meaning,
    apply,
    compose,
    negate_value,
    swap_value,
)


def _r(seed: int = 0) -> random.Random:
    return random.Random(seed)


REALISTIC_INPUTS = (
    "I need a black cotton shirt",
    "something under $80",
    "not leather please",
    "size medium slim fit, machine washable",
    "blue sneakers for the gym",
    "cafe au lait colored wool-blend coat",
    "budget around $29.99",
    "a",
    "",
    "   ",
)


class SurfaceInvariantTest(unittest.TestCase):
    """Properties that must hold for every surface perturbation and input."""

    def test_surface_perturbations_are_meaning_preserving(self) -> None:
        for kind in SURFACE_KINDS:
            for text in REALISTIC_INPUTS:
                with self.subTest(kind=kind, text=text):
                    self.assertIs(apply(kind, text, _r(1)).meaning, Meaning.PRESERVING)

    def test_non_empty_input_never_becomes_empty(self) -> None:
        for kind in SURFACE_KINDS:
            for text in REALISTIC_INPUTS:
                if not text.strip():
                    continue
                for seed in range(15):
                    with self.subTest(kind=kind, text=text, seed=seed):
                        self.assertTrue(apply(kind, text, _r(seed)).text.strip())

    def test_empty_or_blank_input_is_a_no_op(self) -> None:
        for kind in SURFACE_KINDS:
            for text in ("", "   ", "\t\n"):
                for seed in range(5):
                    with self.subTest(kind=kind, text=repr(text), seed=seed):
                        result = apply(kind, text, _r(seed))
                        self.assertFalse(result.changed)
                        self.assertEqual(result.text, text)

    def test_perturbations_are_deterministic_for_a_given_seed(self) -> None:
        for kind in ALL_KINDS:
            options = {"alternatives": ["cotton", "polyester", "wool"]} if kind == "swap_value" else {}
            for text in REALISTIC_INPUTS:
                for seed in (0, 7, 42):
                    with self.subTest(kind=kind, text=text, seed=seed):
                        first = apply(kind, text, _r(seed), **options)
                        second = apply(kind, text, _r(seed), **options)
                        self.assertEqual(first, second)

    def test_surface_perturbations_never_introduce_a_state_machine_trigger(self) -> None:
        # A meaning-preserving paraphrase must not make the belief state machine
        # see an override, a negation, or a no-preference decline that the
        # original message did not contain.
        from needle.state import EXPLICIT_OVERRIDE_RE, NEGATION_RE, NO_PREFERENCE_RE

        probes = (
            "I need a black cotton shirt in medium under $80",
            "looking for waterproof hiking boots, wool-blend, size large",
            "blue sneakers for the gym please",
        )
        for kind in SURFACE_KINDS:
            for text in probes:
                for regex in (EXPLICIT_OVERRIDE_RE, NEGATION_RE, NO_PREFERENCE_RE):
                    if regex.search(text):
                        continue
                    for seed in range(20):
                        out = apply(kind, text, _r(seed)).text
                        with self.subTest(kind=kind, text=text, regex=regex.pattern[:20], seed=seed):
                            self.assertIsNone(regex.search(out))

    def test_reported_changed_flag_matches_the_text(self) -> None:
        for kind in ALL_KINDS:
            options = {"alternatives": ["cotton", "wool"]} if kind == "swap_value" else {}
            for text in REALISTIC_INPUTS:
                for seed in range(10):
                    result = apply(kind, text, _r(seed), **options)
                    with self.subTest(kind=kind, text=text, seed=seed):
                        self.assertEqual(result.changed, result.text != text)


class CasingTest(unittest.TestCase):
    def test_changes_letter_case_but_not_letters(self) -> None:
        result = apply("casing", "Black Cotton Shirt", _r(3))
        self.assertTrue(result.changed)
        self.assertEqual(result.text.lower(), "black cotton shirt")

    def test_all_caps_input_still_produces_a_variant(self) -> None:
        result = apply("casing", "COTTON", _r(0))
        self.assertTrue(result.changed)


class WhitespaceTest(unittest.TestCase):
    def test_word_sequence_is_always_preserved(self) -> None:
        for seed in range(40):
            result = apply("whitespace", "black cotton slim fit shirt", _r(seed))
            self.assertEqual(result.text.split(), ["black", "cotton", "slim", "fit", "shirt"])

    def test_some_seed_changes_the_spacing(self) -> None:
        self.assertTrue(any(apply("whitespace", "a b c", _r(seed)).changed for seed in range(20)))


class PunctuationTest(unittest.TestCase):
    def test_does_not_break_a_decimal_amount(self) -> None:
        for seed in range(40):
            result = apply("punctuation", "budget is $29.99 for a t-shirt", _r(seed))
            self.assertIn("29.99", result.text)

    def test_can_split_a_hyphenated_compound(self) -> None:
        changed = [apply("punctuation", "a well-known v-neck", _r(seed)).text for seed in range(30)]
        self.assertTrue(any("well known" in text or "v neck" in text for text in changed))


class AccentsTest(unittest.TestCase):
    def test_stripping_diacritics_is_meaning_preserving(self) -> None:
        result = apply("accents", "café coloured", _r(0))
        self.assertIs(result.meaning, Meaning.PRESERVING)

    def test_output_and_input_share_an_ascii_folding(self) -> None:
        import unicodedata

        def fold(value: str) -> str:
            return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))

        for seed in range(30):
            result = apply("accents", "a rose colored coat", _r(seed))
            self.assertEqual(fold(result.text), fold("a rose colored coat"))

    def test_input_without_vowels_is_a_no_op(self) -> None:
        self.assertFalse(apply("accents", "xyz-ptr", _r(0)).changed)


class SynonymTest(unittest.TestCase):
    def test_swaps_a_known_domain_synonym(self) -> None:
        result = apply("synonym", "blue sneakers", _r(0))
        self.assertEqual(result.text, "blue trainers")

    def test_is_bidirectional(self) -> None:
        self.assertEqual(apply("synonym", "blue trainers", _r(0)).text, "blue sneakers")

    def test_preserves_the_casing_of_the_replaced_word(self) -> None:
        self.assertEqual(apply("synonym", "Blue Sneakers", _r(0)).text, "Blue Trainers")

    def test_no_synonym_present_is_a_no_op(self) -> None:
        self.assertFalse(apply("synonym", "blue cotton shirt", _r(0)).changed)


class WordOrderTest(unittest.TestCase):
    def test_single_phrase_is_a_no_op(self) -> None:
        self.assertFalse(apply("word_order", "black cotton slim fit shirt", _r(0)).changed)

    def test_shuffles_phrases_but_keeps_the_token_multiset(self) -> None:
        text = "black, cotton, slim fit"
        result = apply("word_order", text, _r(1))
        self.assertTrue(result.changed)
        self.assertEqual(sorted(result.text.replace(",", "").split()), sorted(text.replace(",", "").split()))

    def test_splits_on_the_word_and(self) -> None:
        result = apply("word_order", "cotton and black", _r(0))
        self.assertEqual(sorted(result.text.replace(",", "").split()), ["black", "cotton"])


class FillerTest(unittest.TestCase):
    def test_keeps_every_original_word_in_order(self) -> None:
        for seed in range(30):
            result = apply("filler", "black cotton shirt", _r(seed))
            stream = iter(result.text.replace(",", "").split())
            self.assertTrue(all(word in stream for word in ("black", "cotton", "shirt")))

    def test_no_filler_can_trip_the_state_machine(self) -> None:
        # Check against the real state-machine regexes, not a hand-listed set.
        from needle.state import EXPLICIT_OVERRIDE_RE, NEGATION_RE, NO_PREFERENCE_RE
        from robustness.perturb import _FILLERS

        for phrase in _FILLERS:
            probe = f"black cotton shirt {phrase} in medium"
            self.assertIsNone(NEGATION_RE.search(phrase), phrase)
            self.assertIsNone(EXPLICIT_OVERRIDE_RE.search(probe), phrase)
            self.assertIsNone(NO_PREFERENCE_RE.search(probe), phrase)


class ContractionTest(unittest.TestCase):
    def test_contracts_an_auxiliary_phrase(self) -> None:
        result = apply("contraction", "I am looking for a cotton shirt", _r(0))
        self.assertIn("i'm", result.text.lower())
        self.assertNotIn("i am", result.text.lower())

    def test_negation_survives_contraction(self) -> None:
        result = apply("contraction", "I do not want leather", _r(0))
        self.assertIn("don't", result.text.lower())
        self.assertIn("leather", result.text.lower())

    def test_nothing_contractable_is_a_no_op(self) -> None:
        self.assertFalse(apply("contraction", "cotton shirt please", _r(0)).changed)


class NumberFormatTest(unittest.TestCase):
    def test_rewords_a_budget_comparator_without_touching_the_amount(self) -> None:
        for seed in range(20):
            result = apply("number_format", "something under $80", _r(seed))
            self.assertIn("80", result.text)

    def test_re_expresses_a_currency_amount(self) -> None:
        seen = {apply("number_format", "budget around $80", _r(seed)).text for seed in range(30)}
        self.assertTrue(any("dollars" in text for text in seen))
        for text in seen:
            self.assertTrue("80" in text or "eighty" in text)

    def test_preserves_cents_exactly_and_never_rounds(self) -> None:
        for seed in range(30):
            result = apply("number_format", "budget around $29.99", _r(seed))
            self.assertIn("29.99", result.text)

    def test_a_bare_size_number_is_left_alone(self) -> None:
        self.assertFalse(apply("number_format", "size 8 running shoes", _r(0)).changed)


class TypoTest(unittest.TestCase):
    def test_introduces_a_change_in_a_long_word(self) -> None:
        self.assertTrue(any(apply("typo", "waterproof hiking boots", _r(seed)).changed for seed in range(10)))

    def test_short_words_only_is_a_no_op(self) -> None:
        self.assertFalse(apply("typo", "a red hat on me", _r(0)).changed)

    def test_avoid_set_blocks_a_typo_that_would_be_a_real_word(self) -> None:
        # "coat" -> "goat"/"cost"/"coal"... every single-edit neighbour is forbidden,
        # so the perturbation must decline rather than silently change the meaning.
        neighbours = {"goat", "cost", "coal", "coats", "oat", "cot", "chat", "coa", "coar", "coot"}
        for seed in range(40):
            result = apply("typo", "wool coat", _r(seed), avoid=neighbours | {"wool", "woo", "wolo", "wooll", "wol"})
            self.assertNotIn(result.text.replace(",", "").split()[-1], neighbours)

    def test_avoid_set_still_allows_a_safe_typo(self) -> None:
        changed = [apply("typo", "waterproof jacket", _r(seed), avoid={"jackets"}).changed for seed in range(20)]
        self.assertTrue(any(changed))


class NegateValueTest(unittest.TestCase):
    def test_prefixes_a_negation_marker(self) -> None:
        result = negate_value("cotton", _r(0))
        self.assertIs(result.meaning, Meaning.CHANGING)
        self.assertTrue(result.text.startswith(("not ", "no ", "non-")))
        self.assertIn("cotton", result.text)

    def test_preserves_an_attribute_prefix(self) -> None:
        result = negate_value("color: blue", _r(1))
        self.assertTrue(result.text.startswith("color: "))
        self.assertIn("blue", result.text)

    def test_negation_is_its_own_inverse(self) -> None:
        once = negate_value("cotton", _r(0))
        twice = negate_value(once.text, _r(0))
        self.assertEqual(twice.text.strip(), "cotton")

    def test_budget_phrases_are_refused(self) -> None:
        for disclosure in ("budget around $29.99", "budget", "price under $50"):
            self.assertFalse(negate_value(disclosure, _r(0)).changed)


class SwapValueTest(unittest.TestCase):
    ALTS = ("cotton", "polyester", "wool", "nylon")

    def test_replaces_with_a_different_in_bucket_value(self) -> None:
        result = swap_value("cotton", _r(0), alternatives=self.ALTS)
        self.assertIs(result.meaning, Meaning.CHANGING)
        self.assertTrue(result.changed)
        self.assertNotEqual(result.text.strip().lower(), "cotton")
        self.assertIn(result.text.strip(), self.ALTS)

    def test_never_picks_the_current_value_even_across_seeds(self) -> None:
        for seed in range(50):
            self.assertNotEqual(
                swap_value("wool", _r(seed), alternatives=self.ALTS).text.strip().lower(), "wool"
            )

    def test_preserves_an_attribute_prefix(self) -> None:
        result = swap_value("color: blue", _r(0), alternatives=("blue", "red", "green"))
        self.assertTrue(result.text.startswith("color: "))
        self.assertNotIn("blue", result.text)

    def test_no_usable_alternative_is_a_no_op(self) -> None:
        self.assertFalse(swap_value("cotton", _r(0), alternatives=("cotton",)).changed)
        self.assertFalse(swap_value("cotton", _r(0), alternatives=()).changed)


class ComposeTest(unittest.TestCase):
    def test_all_surface_stages_stay_meaning_preserving(self) -> None:
        result = compose("Blue Cotton Shirt, machine washable", ["casing", "whitespace", "filler"], _r(2))
        self.assertIs(result.meaning, Meaning.PRESERVING)
        self.assertEqual(result.kind, "casing+whitespace+filler")

    def test_any_semantic_stage_makes_the_whole_composition_changing(self) -> None:
        result = compose("cotton", ["casing", "negate_value"], _r(0))
        self.assertIs(result.meaning, Meaning.CHANGING)
        self.assertTrue(result.changed)

    def test_changed_is_false_when_no_stage_changed_anything(self) -> None:
        result = compose("", ["casing", "filler", "synonym"], _r(0))
        self.assertFalse(result.changed)

    def test_stages_are_applied_in_order(self) -> None:
        # synonym first turns "sneakers" into "trainers", so a later typo can only
        # land on "trainers".
        result = compose("blue sneakers", ["synonym"], _r(0))
        self.assertEqual(result.text, "blue trainers")


class DispatchTest(unittest.TestCase):
    def test_unknown_kind_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown perturbation kind"):
            apply("does_not_exist", "text", _r(0))

    def test_keyword_options_pass_through(self) -> None:
        result = apply("swap_value", "cotton", _r(0), alternatives=["wool"])
        self.assertEqual(result.text.strip(), "wool")


if __name__ == "__main__":
    unittest.main()
