"""Answer the customer in the language they wrote in, without touching English.

The English wording carries distinctions the templates cannot: "in the catalog"
against "among boots", "one more detail" against naming the category. Those were
tuned on the English sentence, so English keeps its own code path and only a
customer who wrote in another language reaches the translated one.

That separation is the thing worth guarding, so the first class asserts it
directly rather than trusting it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from needle.agent import Agent
from needle.explain import message_for, turn_record
from needle.language import DEFAULT, phrases, supported

CATALOG = Path(__file__).resolve().parents[1] / (
    ".artifacts/participant-kit/techjam-conversational-search/data/catalog.jsonl"
)


def _record(**overrides) -> dict:
    base = dict(
        turn=2, category="boots", wanted=["100% Leather"], unwanted=[],
        candidates=12, identified=False, emitted=["B01"], withheld=False,
    )
    base.update(overrides)
    return turn_record(**base)


class EnglishIsUntouched(unittest.TestCase):
    def test_the_default_language_is_english(self) -> None:
        self.assertEqual(DEFAULT, "en")
        self.assertEqual(_record()["language"], "en")

    def test_english_wording_is_the_pre_existing_wording(self) -> None:
        """Exact strings, so a template refactor cannot quietly reword them."""
        said = message_for(_record(), asking=True)
        self.assertIn("I have 12 candidates among boots", said)
        self.assertIn("What else matters?", said)

    def test_the_generic_category_still_reads_as_the_catalog(self) -> None:
        said = message_for(_record(category="items", wanted=[]), asking=False)
        self.assertIn("catalog", said)
        self.assertNotIn("among items", said)

    def test_an_unknown_language_falls_back_rather_than_raising(self) -> None:
        said = message_for(_record(language="xx"), asking=False)
        self.assertTrue(said)


class EveryLanguageRenders(unittest.TestCase):
    def test_no_template_leaves_an_empty_slot(self) -> None:
        """A missing count used to render "Quedan  opciones"."""
        for language in supported():
            for candidates in (None, 1, 12):
                for wanted in ([], ["100% Leather"]):
                    with self.subTest(language=language, candidates=candidates, wanted=wanted):
                        said = message_for(
                            _record(language=language, candidates=candidates, wanted=wanted),
                            asking=True,
                        )
                        self.assertTrue(said.strip())
                        self.assertNotIn("  ", said)
                        self.assertNotIn("{", said)

    def test_every_language_defines_every_key_english_defines(self) -> None:
        expected = set(phrases("en"))
        for language in supported():
            with self.subTest(language=language):
                self.assertEqual(set(phrases(language)), expected)

    def test_catalog_values_are_never_translated(self) -> None:
        """A product attribute stays the string the catalog holds. Inventing a
        translation would assert something the catalog does not say."""
        for language in supported():
            with self.subTest(language=language):
                said = message_for(_record(language=language), asking=False)
                self.assertIn("100% Leather", said)


@unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
class TheSessionHoldsItsLanguage(unittest.TestCase):
    OPENINGS = {
        "es": "Busco unas botas de cuero.",
        "fr": "Je cherche des bottes en cuir.",
        "de": "Ich suche Stiefel aus Leder.",
        "ja": "ブーツを探しています。",
        "zh": "我在找靴子。",
    }
    # A phrase from that language's own templates, taken literally rather than
    # derived from the table, so a template edit has to be looked at.
    MARKERS = {
        "es": "importa",
        "fr": "compte",
        "de": "wichtig",
        "ja": "教えてください",
        "zh": "告诉我",
    }

    def test_the_reply_is_in_the_language_of_the_request(self) -> None:
        for language, opening in self.OPENINGS.items():
            with self.subTest(language=language):
                with Agent(str(CATALOG), explain=True) as agent:
                    agent.reset("s", {})
                    said = agent.respond("s", opening, 1, 10)["message"]
                self.assertIn(self.MARKERS[language], said)

    def test_a_short_later_message_does_not_flip_the_language(self) -> None:
        """"Sí, cuero." reads as English on its own. The session already knows."""
        with Agent(str(CATALOG), explain=True) as agent:
            agent.reset("s", {})
            agent.respond("s", self.OPENINGS["es"], 1, 10)
            said = agent.respond("s", "Sí, cuero.", 2, 10)["message"]
        self.assertNotIn("matters most", said)

    def test_an_english_session_is_answered_in_english(self) -> None:
        with Agent(str(CATALOG), explain=True) as agent:
            agent.reset("s", {})
            said = agent.respond("s", "I'm looking for Shoes Boots.", 1, 10)["message"]
        self.assertIn("starting with", said)


@unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
class TheLexiconOnlyRunsWhenEnglishGrammarFails(unittest.TestCase):
    """The branch that could reach retrieval, and the reason it cannot on English.

    `opening_category_signature` keys on the simulator's own request grammar. A
    non-English request is differently ordered, not unparseable, so the lexicon
    is the fallback. An English request either states a category in that grammar
    or genuinely has none, so it never reaches the fallback.
    """

    def test_an_english_opening_never_consults_the_lexicon(self) -> None:
        with Agent(str(CATALOG), explain=True) as agent:
            agent.reset("s", {})
            agent.respond("s", "I'm looking for Shoes Boots, but I'm still exploring.", 1, 10)
            self.assertEqual(agent._lexicon_words_by_session.get("s", ""), "")

    def test_a_non_english_opening_recovers_the_noun(self) -> None:
        with Agent(str(CATALOG), explain=True) as agent:
            agent.reset("s", {})
            agent.respond("s", "Busco unas botas de cuero.", 1, 10)
            self.assertEqual(agent._lexicon_words_by_session.get("s", ""), "boots")


if __name__ == "__main__":
    unittest.main()
