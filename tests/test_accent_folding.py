"""Accented disclosures must still reach the belief state.

`ATTRIBUTE_VOCABULARY` is ASCII and `_find_values` matches it against the raw
message, so before this an accented value produced no constraint at all. The
fold has to be offset-preserving: `_declined_regions`, `inside_declined` and
`_is_negated` all address the same message by offset, so a fold that changed
length would silently mis-attribute negation and no-preference clauses.
"""
from __future__ import annotations

import unittest

from needle.state import (
    Polarity,
    _within_one_edit,
    extract_constraints,
    fold_marks_in_place,
    looks_like_retraction,
)


class FoldMarksInPlace(unittest.TestCase):
    def test_ascii_is_returned_unchanged(self):
        for text in ("cotton shirt", "", "100% Polyester; Imported"):
            self.assertIs(fold_marks_in_place(text), text)

    def test_length_is_always_preserved(self):
        for text in ("cótton", "naïve café", "ﬁre", "ß ø æ", "Ünïcödé", "日本語"):
            self.assertEqual(len(fold_marks_in_place(text)), len(text), text)

    def test_latin_accents_fold_to_their_base(self):
        self.assertEqual(fold_marks_in_place("cótton"), "cotton")
        self.assertEqual(fold_marks_in_place("naïve café"), "naive cafe")

    def test_ligatures_and_stroked_letters_are_left_alone(self):
        # Matches `remove_diacritics 2` rather than exceeding it: these are not
        # base-plus-combining-mark, so folding them would be transliteration.
        self.assertEqual(fold_marks_in_place("ﬁre"), "ﬁre")
        self.assertEqual(fold_marks_in_place("ß ø æ"), "ß ø æ")

    def test_non_latin_is_left_alone(self):
        self.assertEqual(fold_marks_in_place("日本語"), "日本語")


class AccentedDisclosures(unittest.TestCase):
    def test_accented_value_is_extracted(self):
        plain = extract_constraints("For that, what matters is: cotton.")
        accented = extract_constraints("For that, what matters is: cótton.")
        self.assertEqual(accented, plain)
        self.assertEqual(accented, [("material", "cotton", Polarity.POSITIVE)])

    def test_extracted_value_is_never_accented(self):
        for _, value, _ in extract_constraints("For that, what matters is: cótton."):
            self.assertTrue(value.isascii())

    def test_negation_still_applies_across_a_fold(self):
        # The negation window is measured in offsets before the accent, so this
        # is the assertion that would fail under a length-changing fold.
        found = extract_constraints("I don't want cótton.")
        self.assertEqual(found, [("material", "cotton", Polarity.NEGATIVE)])

    def test_no_preference_suppression_still_applies_across_a_fold(self):
        found = extract_constraints(
            "For that, what matters is: cótton, and I don't have a preference for color."
        )
        self.assertEqual(found, [("material", "cotton", Polarity.POSITIVE)])
        self.assertNotIn("color", [attribute for attribute, _, _ in found])


if __name__ == "__main__":
    unittest.main()


class TypoTolerantOverride(unittest.TestCase):
    """A single typo must not cost the whole session.

    `EXPLICIT_OVERRIDE_RE` is a phrase match, so "earliier preference" left it
    unmatched, the retracted constraints stayed active, and the agent spent the
    rest of the session chasing a preference the customer had withdrawn. On the
    typo slice that was `intent_override` HR 0.567 against 1.000.
    """

    def test_single_typo_in_either_half_still_retracts(self):
        for message in (
            "Actually, ignore my earliier preference. What I need is: leather.",
            "Actually, ignore my eartier preference. What I need is: leather.",
            "Actually, ignore my earlier prefference. What I need is: leather.",
            "Actually, ignroe my earlier preference. What I need is: leather.",
        ):
            self.assertTrue(looks_like_retraction(message), message)

    def test_both_halves_are_still_required(self):
        # A retraction verb with nothing to retract, and a prior-reference with
        # no retraction, must both stay quiet: a false override bumps the intent
        # version and discards belief, which costs more than a missed one.
        self.assertFalse(looks_like_retraction("Please ignore the fit for now."))
        self.assertFalse(looks_like_retraction("My earlier preference was cotton."))

    def test_released_non_override_replies_stay_quiet(self):
        for message in (
            "I don't have an additional preference for other.",
            "For that, what matters is: cotton; Imported.",
            "Those options are not quite right yet. Ask me about one specific attribute.",
            "I need cotton instead of polyester.",
            "I'm looking for Men's Shirts, but I'm still exploring.",
        ):
            self.assertFalse(looks_like_retraction(message), message)

    def test_short_words_are_matched_exactly(self):
        # One edit reaches too many unrelated words below five characters.
        self.assertFalse(_within_one_edit("undp", "undo"))
        self.assertTrue(_within_one_edit("ignorre", "ignore"))
