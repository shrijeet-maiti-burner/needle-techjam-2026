"""Answer in the customer's language, and never guess it from the catalog's.

The released simulator speaks English, so nothing here can move a score. The
risk is entirely the other way: a false positive answers an English speaker in
German. Detection is therefore built to fail towards English, and these pin that.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.explain import message_for, turn_record  # noqa: E402
from needle.language import (  # noqa: E402
    DEFAULT,
    category_mention,
    detect,
    phrases,
    supported,
)


class DetectionTest(unittest.TestCase):
    def test_each_script_is_recognised(self) -> None:
        for expected, text in (
            ("es", "Busco unos zapatos de cuero para el trabajo"),
            ("fr", "Je cherche des bottes en cuir pour le travail"),
            ("de", "Ich suche Stiefel aus Leder für die Arbeit"),
            ("hi", "मुझे चमड़े के जूते चाहिए"),
            ("ja", "革のブーツを探しています"),
            ("zh", "我想要一双皮靴"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(detect(text), expected)

    def test_english_stays_english(self) -> None:
        for text in (
            "I'm looking for Shoes Boots, but I'm still exploring.",
            "For that, what matters is: 100% Cotton; Imported.",
            "Actually, ignore my earlier preference. What I need is: leather.",
            "I don't have a preference for material; please use your judgment.",
        ):
            with self.subTest(text=text[:30]):
                self.assertEqual(detect(text), DEFAULT)

    def test_a_foreign_catalog_value_does_not_change_the_language(self) -> None:
        """The bug this threshold exists for.

        The catalog is a US marketplace export that still carries
        source-language attribute values, so an English request can contain a
        Chinese material name. Counting characters read 2 of the 2000 released
        simulator messages as Chinese; requiring a share of the letters reads
        none of them.
        """
        self.assertEqual(detect("For that, what matters is: 进口; Pull On closure."), DEFAULT)
        self.assertEqual(detect("For that, what matters is: 进口."), DEFAULT)

    def test_one_stray_cue_is_not_enough_to_leave_english(self) -> None:
        # "para" is a Spanish cue and also appears in English product text.
        self.assertEqual(detect("looking for a parachute cord bracelet"), DEFAULT)

    def test_empty_and_malformed_input_falls_back(self) -> None:
        for value in ("", "   ", None, 42, b"bytes"):
            with self.subTest(value=value):
                self.assertEqual(detect(value), DEFAULT)


class PhraseTableTest(unittest.TestCase):
    REQUIRED = {
        "start", "narrow", "single", "ask", "choose", "or_other",
        "ruled_out", "material", "color", "and", "going_on",
    }

    def test_every_language_is_complete(self) -> None:
        """A half-translated language renders half an English sentence."""
        for code in supported():
            with self.subTest(code=code):
                self.assertTrue(self.REQUIRED <= set(phrases(code)))

    def test_an_unknown_language_falls_back_rather_than_failing(self) -> None:
        self.assertEqual(phrases("xx"), phrases(DEFAULT))

    def test_templates_render_without_leftover_placeholders(self) -> None:
        for code in supported():
            record = turn_record(
                turn=2, category="belts", wanted=["leather"], unwanted=["suede"],
                candidates=12, identified=False, emitted=["x"], withheld=True,
                language=code,
            )
            message = message_for(record, asking=True)
            with self.subTest(code=code):
                self.assertNotIn("{", message)
                self.assertNotIn("}", message)
                self.assertTrue(message.strip())

    def test_an_unknown_count_is_never_reported_as_one(self) -> None:
        record = turn_record(
            turn=2, category="belts", wanted=["leather"], unwanted=[],
            candidates=None, identified=False, emitted=["x"], withheld=True,
        )
        self.assertNotIn("1 candidates", message_for(record, asking=True))


if __name__ == "__main__":
    unittest.main()


class CategoryLexiconTest(unittest.TestCase):
    """A non-English request should not lose its category.

    The category is the strongest single key the agent has -- it qualifies the
    disclosure bucket, not just the sentence -- and before the lexicon a shopper
    writing in Spanish lost it entirely and was answered about "items".
    """

    def test_the_noun_is_found_regardless_of_grammar(self) -> None:
        for text, english in (
            ("Busco unos cinturones de cuero", "belts"),
            ("Je cherche des bottes en cuir", "boots"),
            ("Ich suche Gürtel aus Leder", "belts"),
            ("मुझे बेल्ट चाहिए", "belts"),
            ("ベルトを探しています", "belts"),
            ("我在找腰带", "belts"),
        ):
            with self.subTest(text=text):
                self.assertEqual(category_mention(text)[0], english)

    def test_the_customers_own_spelling_is_echoed_back(self) -> None:
        self.assertEqual(category_mention("Ich suche Gürtel")[1], "Gürtel")
        self.assertEqual(category_mention("Busco unos CINTURONES")[1], "CINTURONES")

    def test_an_unknown_noun_resolves_to_nothing_rather_than_a_guess(self) -> None:
        self.assertEqual(category_mention("Busco algo bonito"), ("", ""))

    def test_a_substring_is_not_a_match(self) -> None:
        # "rock" is a German skirt; "rocket" is not.
        self.assertEqual(category_mention("a rocket launcher"), ("", ""))

    def test_english_requests_do_not_use_the_lexicon(self) -> None:
        """English openings are read by the simulator's own pattern."""
        self.assertEqual(category_mention("I am looking for Accessories Belts"), ("", ""))


class ResolutionTest(unittest.TestCase):
    def test_a_word_naming_exactly_one_category_resolves(self) -> None:
        from needle.catalog import resolve_coarse_category

        known = {"accessories wallets", "shoes boots", "women shoes boots"}
        self.assertEqual(resolve_coarse_category("wallets", known), "accessories wallets")

    def test_an_ambiguous_word_declines(self) -> None:
        from needle.catalog import resolve_coarse_category

        known = {"men belts", "women belts", "accessories belts"}
        self.assertEqual(resolve_coarse_category("belts", known), "")

    def test_the_shortest_wins_only_when_uniquely_shortest(self) -> None:
        from needle.catalog import resolve_coarse_category

        known = {"shoes boots", "women shoes boots"}
        self.assertEqual(resolve_coarse_category("boots", known), "shoes boots")
