from __future__ import annotations

import unittest

from needle.state import ATTRIBUTE_VOCABULARY, Polarity, extract_constraints


def _polarity(message: str, attribute: str, value: str) -> Polarity | None:
    return next(
        (
            polarity
            for found_attribute, found_value, polarity in extract_constraints(message)
            if found_attribute == attribute and found_value == value
        ),
        None,
    )


class PermissiveNegationTest(unittest.TestCase):
    """Negating aversion or uncertainty does not reject the catalog value."""

    def test_non_excluding_negation_generalizes_across_every_attribute(self) -> None:
        templates = (
            "I would not mind {value}.",
            "I am not sure about {value}.",
            "I am not certain about {value}.",
            "I am not opposed to {value}.",
            "I am not against {value}.",
            "I do not dislike {value}.",
            "I would not object to {value}.",
        )
        for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
            value = vocabulary[0]
            for template in templates:
                message = template.format(value=value)
                with self.subTest(attribute=attribute, message=message):
                    self.assertIs(_polarity(message, attribute, value), Polarity.POSITIVE)

    def test_a_direct_rejection_is_still_negative(self) -> None:
        for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
            value = vocabulary[0]
            for message in (f"I do not want {value}.", f"No {value}, please."):
                with self.subTest(attribute=attribute, message=message):
                    self.assertIs(_polarity(message, attribute, value), Polarity.NEGATIVE)


class ExceptionConstructionTest(unittest.TestCase):
    """Exclusive exception markers reject their complement, not the whole turn."""

    def test_anything_and_all_but_are_exclusions_for_every_attribute(self) -> None:
        for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
            value = vocabulary[0]
            for message in (f"anything but {value}", f"all but the {value}"):
                with self.subTest(attribute=attribute, message=message):
                    self.assertIs(_polarity(message, attribute, value), Polarity.NEGATIVE)

    def test_nothing_but_is_inclusive(self) -> None:
        for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
            value = vocabulary[0]
            message = f"nothing but {value}"
            with self.subTest(attribute=attribute, message=message):
                self.assertIs(_polarity(message, attribute, value), Polarity.POSITIVE)


class CorrectionBoundaryTest(unittest.TestCase):
    def test_comma_scoped_correction_generalizes_across_every_attribute(self) -> None:
        for attribute, vocabulary in ATTRIBUTE_VOCABULARY:
            old, new = vocabulary[:2]
            message = f"not {old}, I prefer {new}"
            with self.subTest(attribute=attribute, message=message):
                self.assertIs(_polarity(message, attribute, old), Polarity.NEGATIVE)
                self.assertIs(_polarity(message, attribute, new), Polarity.POSITIVE)


class ReportedRegressionTest(unittest.TestCase):
    def test_the_reported_human_red_team_table(self) -> None:
        cases = {
            "I wouldn't mind a red shoe.": {("color", "red", Polarity.POSITIVE)},
            "I would not mind a red shoe.": {("color", "red", Polarity.POSITIVE)},
            "I do not want a red shoe.": {("color", "red", Polarity.NEGATIVE)},
            "I don't want a red shoe.": {("color", "red", Polarity.NEGATIVE)},
            "No red shoes please.": {("color", "red", Polarity.NEGATIVE)},
            "not black, I prefer red": {
                ("color", "black", Polarity.NEGATIVE),
                ("color", "red", Polarity.POSITIVE),
            },
            "I want a red shoe without leather": {
                ("material", "leather", Polarity.NEGATIVE),
                ("color", "red", Polarity.POSITIVE),
            },
            "anything but red": {("color", "red", Polarity.NEGATIVE)},
            "I am not sure, maybe red": {("color", "red", Polarity.POSITIVE)},
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(set(extract_constraints(message)), expected)


if __name__ == "__main__":
    unittest.main()
