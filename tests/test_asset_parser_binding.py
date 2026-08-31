"""The bundled asset stores this repository's parse of the catalog.

`build_signature_index` writes `product_clarification_facets` for all 50,000
products, and that calls `needle.state.extract_constraints`. So the 65MB asset
contains the belief state's parsing output, and a change to that parser makes
the stored facets wrong.

Until this binding existed, nothing noticed: `schema_version`,
`catalog_sha256` and `product_count` all still matched after a parsing change,
so `CatalogIndex` accepted the asset and the agent offered clarification options
that a parser it no longer contained had produced.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import needle.state as state
from needle.catalog import (
    SIGNATURE_INDEX_SCHEMA_VERSION,
    CatalogIndex,
    build_signature_index,
)

PRODUCTS = [
    {
        "parent_asin": "A1", "title": "Shirt", "categories": ["Clothing", "Shirts"],
        "features": ["I don't like black stitching"], "details": {"Material": "Cotton"},
        "rating_number": 5, "average_rating": 4.0,
    },
    {
        "parent_asin": "A2", "title": "Boot", "categories": ["Shoes", "Boots"],
        "features": ["Genuine Leather"], "details": {"Material": "Leather"},
        "rating_number": 9, "average_rating": 4.5,
    },
]


class FacetRulesFingerprint(unittest.TestCase):
    def test_it_is_stable_across_calls(self) -> None:
        self.assertEqual(state.facet_rules_fingerprint(), state.facet_rules_fingerprint())

    def test_every_input_to_the_parse_moves_it(self) -> None:
        """Derived, not hand-maintained. A constant someone has to remember to
        bump is a constant that does not get bumped."""
        original = state.facet_rules_fingerprint()
        changes = {
            "NEGATION_WINDOW": 25,
            "NEGATION_RE": state.re.compile(r"\bno\b", state.re.IGNORECASE),
            "NON_EXCLUDING_NEGATION_RE": state.re.compile(
                r"\bnot only\b", state.re.IGNORECASE
            ),
            "EXCEPTION_NEGATION_RE": state.re.compile(
                r"\banything but\s*$", state.re.IGNORECASE
            ),
            "NO_PREFERENCE_RE": state.re.compile(r"\bwhatever\b", state.re.IGNORECASE),
            "BUDGET_RE": state.re.compile(r"\$(\d+)"),
            "ATTRIBUTE_VOCABULARY": (("material", ("cotton",)),),
        }
        for name, replacement in changes.items():
            with self.subTest(rule=name):
                keep = getattr(state, name)
                setattr(state, name, replacement)
                try:
                    self.assertNotEqual(state.facet_rules_fingerprint(), original)
                finally:
                    setattr(state, name, keep)
        self.assertEqual(state.facet_rules_fingerprint(), original)


class TheAssetIsBoundToTheParser(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.catalog = root / "catalog.jsonl"
        self.catalog.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS), encoding="utf-8"
        )
        self.asset = root / "index.sqlite3"
        build_signature_index(self.catalog, self.asset)

    def _metadata(self) -> dict[str, str]:
        connection = sqlite3.connect(f"file:{self.asset.as_posix()}?mode=ro", uri=True)
        try:
            return dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()

    def _open(self) -> CatalogIndex:
        return CatalogIndex(
            str(self.catalog),
            retrieval_mode="signature_first",
            signature_index_path=str(self.asset),
        )

    def test_the_fingerprint_is_recorded(self) -> None:
        """The recorded value is the combined one, not the state half alone.

        The facets have two authors: `needle.state` parses the product's prose
        and `needle.catalog` derives brand, budget band and category leaf from
        fields. A fingerprint covering only the first would accept an asset
        built before the field facets existed, which is the same silent
        acceptance this binding was added to stop.
        """
        from needle.catalog import _facet_rules_fingerprint

        recorded = self._metadata().get("facet_parser_sha256")
        self.assertEqual(recorded, _facet_rules_fingerprint())
        self.assertNotEqual(
            recorded, state.facet_rules_fingerprint(),
            "the field-derived facets are not covered by the recorded fingerprint",
        )

    def test_a_matching_asset_is_used(self) -> None:
        index = self._open()
        self.addCleanup(index.close)
        self.assertIsNone(index.signature_index_fallback)

    def test_a_parser_change_retires_the_asset(self) -> None:
        """The exact case that was silently accepted: generalising negation so
        that "I don't like black" excludes black rather than requesting it.

        Every other guard still passes, which is why this one has to exist.
        """
        metadata = self._metadata()
        self.assertEqual(metadata["schema_version"], SIGNATURE_INDEX_SCHEMA_VERSION)

        keep = state.NEGATION_RE
        state.NEGATION_RE = state.re.compile(
            r"\b(?:no|not|nothing|(?:do|does|did|ca|wo)\s?n['’]?t)\b", state.re.IGNORECASE
        )
        try:
            self.assertNotEqual(
                self._metadata().get("facet_parser_sha256"),
                state.facet_rules_fingerprint(),
                "the change did not move the fingerprint, so this proves nothing",
            )
            index = self._open()
            self.addCleanup(index.close)
            self.assertIsNotNone(
                index.signature_index_fallback,
                "an asset parsed by a different rule set was accepted",
            )
        finally:
            state.NEGATION_RE = keep

    def test_the_rebuilt_asset_disagrees_with_the_old_one(self) -> None:
        """Not just a label change: the stored facets really do differ."""
        before = dict(
            sqlite3.connect(f"file:{self.asset.as_posix()}?mode=ro", uri=True)
            .execute("SELECT parent_asin, payload FROM clarification_facets")
        )
        keep = state.NEGATION_RE
        # Simulate the narrow legacy parser that missed auxiliary negation.
        # The current parser excludes black in "don't like black"; this one
        # treats it as a positive facet, proving that accepting a stale asset
        # would change the options the agent can ask about.
        state.NEGATION_RE = state.re.compile(r"\b(?:no|not|nothing)\b", state.re.IGNORECASE)
        try:
            rebuilt = self.asset.with_name("rebuilt.sqlite3")
            build_signature_index(self.catalog, rebuilt)
            after = dict(
                sqlite3.connect(f"file:{rebuilt.as_posix()}?mode=ro", uri=True)
                .execute("SELECT parent_asin, payload FROM clarification_facets")
            )
        finally:
            state.NEGATION_RE = keep
        self.assertNotIn("black", before["A1"])
        self.assertIn("black", after["A1"])


if __name__ == "__main__":
    unittest.main()
