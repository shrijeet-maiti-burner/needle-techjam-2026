"""`VocabularyCorrector` recovers single-character corruption using the corpus's
own vocabulary.

The property that matters is that nothing here is specific to a catalog, a
language, or a curated word list: every correction is drawn from the terms the
index actually contains. These tests use vocabularies that share no words with
the competition catalog, so a regression that quietly reintroduced a hardcoded
list would fail them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.agent import Agent
from needle.catalog import CatalogIndex
from needle.semantic import VocabularyCorrector, _within_one_edit


class EditDistanceTest(unittest.TestCase):
    def test_recognises_each_single_edit(self) -> None:
        for label, corrupted in (
            ("substitution", "cotton".replace("t", "x", 1)),
            ("deletion", "coton"),
            ("insertion", "cottton"),
            ("transposition", "octton"),
            ("identity", "cotton"),
        ):
            with self.subTest(edit=label):
                self.assertTrue(_within_one_edit("cotton", corrupted))

    def test_rejects_two_edits(self) -> None:
        # "ctton" is deliberately absent: it is one deletion, not two.
        for corrupted in ("cottxx", "ctto", "xottonx", ""):
            with self.subTest(term=corrupted):
                self.assertFalse(_within_one_edit("cotton", corrupted))

    def test_is_symmetric(self) -> None:
        for a, b in (("cotton", "coton"), ("band", "bnad"), ("alloy", "allwy")):
            self.assertEqual(_within_one_edit(a, b), _within_one_edit(b, a))


class CorrectorTest(unittest.TestCase):
    # Deliberately not apparel: the corrector must carry no domain knowledge.
    VOCABULARY = {
        "tungsten": 40, "titanium": 35, "obsidian": 12, "quartzite": 9,
        "basalt": 22, "gabbro": 5, "granite": 30, "gneiss": 4,
    }

    def setUp(self) -> None:
        self.corrector = VocabularyCorrector(self.VOCABULARY)

    def test_recovers_a_corrupted_term(self) -> None:
        for corrupted, expected in (
            ("tungstn", "tungsten"),      # deletion
            ("titaniun", "titanium"),     # substitution
            ("obsidain", "obsidian"),     # transposition
            ("granitte", "granite"),      # insertion
        ):
            with self.subTest(term=corrupted):
                self.assertEqual(self.corrector.correct(corrupted), expected)

    def test_never_corrects_a_term_the_corpus_contains(self) -> None:
        """A term that matches documents is not a typo. Replacing it would
        trade a real signal for a guess."""
        for term in self.VOCABULARY:
            with self.subTest(term=term):
                self.assertIsNone(self.corrector.correct(term))

    def test_refuses_when_nothing_is_close(self) -> None:
        for term in ("xylophone", "helicopter", "zzzzzzzz"):
            with self.subTest(term=term):
                self.assertIsNone(self.corrector.correct(term))

    def test_refuses_short_terms(self) -> None:
        """Short terms have too many neighbours for a correction to be
        evidence of anything."""
        corrector = VocabularyCorrector({"cat": 5, "car": 5, "can": 5, "cab": 5})
        self.assertIsNone(corrector.correct("caz"))

    def test_ties_break_on_corpus_frequency_then_the_term(self) -> None:
        corrector = VocabularyCorrector({"basalt": 22, "basale": 99})
        self.assertEqual(corrector.correct("basalx"), "basale")

    def test_is_deterministic_across_construction_order(self) -> None:
        """Set iteration order must not leak into the result."""
        reversed_vocabulary = dict(reversed(list(self.VOCABULARY.items())))
        other = VocabularyCorrector(reversed_vocabulary)
        for term in ("tungstn", "titaniun", "obsidain", "basalx"):
            with self.subTest(term=term):
                self.assertEqual(self.corrector.correct(term), other.correct(term))

    def test_carries_no_vocabulary_of_its_own(self) -> None:
        """An empty corpus can correct nothing. Guards against a future
        hardcoded fallback list."""
        empty = VocabularyCorrector({})
        for term in ("cotton", "leathr", "waterproof"):
            self.assertIsNone(empty.correct(term))

    def test_serves_a_vocabulary_it_was_never_designed_for(self) -> None:
        """Same code, non-English corpus."""
        corrector = VocabularyCorrector({"雨傘": 3, "ombrello": 7, "paraguas": 5})
        self.assertEqual(corrector.correct("ombrelo"), "ombrello")
        self.assertEqual(corrector.correct("paragaus"), "paraguas")


class RetrievalIntegrationTest(unittest.TestCase):
    PRODUCTS = [
        {"parent_asin": f"B{index:06d}",
         "title": "waterproof leather hiking boot",
         "features": ["breathable membrane"],
         "rating_number": index}
        for index in range(20)
    ]

    def _catalog(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.jsonl"
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in self.PRODUCTS),
            encoding="utf-8",
        )
        return path

    def test_disabled_by_default(self) -> None:
        index = CatalogIndex(self._catalog())
        self.addCleanup(index.close)
        self.assertFalse(index.correct_unmatched_terms)
        self.assertEqual(index.search("watreproof boots", 10), [])

    def test_enabled_recovers_the_query(self) -> None:
        index = CatalogIndex(self._catalog(), correct_unmatched_terms=True)
        self.addCleanup(index.close)
        self.assertTrue(index.search("watreproof leathr", 10))

    def test_a_clean_query_is_byte_identical_either_way(self) -> None:
        """The flag must be inert when every term already matches, so enabling
        it cannot move an unperturbed result."""
        path = self._catalog()
        off = CatalogIndex(path)
        on = CatalogIndex(path, correct_unmatched_terms=True)
        self.addCleanup(off.close)
        self.addCleanup(on.close)
        for query in ("waterproof leather", "hiking boot", "breathable membrane"):
            with self.subTest(query=query):
                self.assertEqual(
                    [c.parent_asin for c in off.search(query, 10)],
                    [c.parent_asin for c in on.search(query, 10)],
                )

    def test_recovery_is_recorded_for_the_experiment_record(self) -> None:
        index = CatalogIndex(self._catalog(), correct_unmatched_terms=True)
        self.addCleanup(index.close)
        index.search("watreproof", 10)
        self.assertIn(("watreproof", "waterproof"), index.recovered_terms)

    def test_structured_scope_corrects_explicit_evidence_only(self) -> None:
        index = CatalogIndex(
            self._catalog(),
            correct_unmatched_terms=True,
            correction_scope="structured",
        )
        self.addCleanup(index.close)

        results = index.search(
            "please watreproof",
            10,
            messages=[
                "I'm looking for hiking boots. A key requirement is: watreproof."
            ],
        )

        self.assertTrue(results)
        self.assertIn(("watreproof", "waterproof"), index.recovered_terms)

    def test_agent_exposes_the_flag_in_its_configuration(self) -> None:
        agent = Agent(self._catalog(), correct_unmatched_terms=True)
        self.addCleanup(agent.close)
        self.assertIs(agent.experiment_configuration["correct_unmatched_terms"], True)


if __name__ == "__main__":
    unittest.main()
