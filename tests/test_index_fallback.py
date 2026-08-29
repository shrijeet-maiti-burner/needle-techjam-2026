import json
import tempfile
import unittest
from pathlib import Path

from needle.catalog import CatalogIndex, build_signature_index


class SignatureIndexFallback(unittest.TestCase):
    """A bundled index is a startup optimisation, never a hard requirement.

    Raising on a bad or absent index aborts the agent before any session runs
    and scores zero. Rebuilding in process costs a few seconds and scores what
    the in-process signature path scores.
    """

    def write_catalog(self, products: list[dict]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.jsonl"
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        return path

    def catalog(self) -> Path:
        return self.write_catalog(
            [
                {"parent_asin": "TARGET", "title": "shirt", "features": ["Cloudsoft cotton"]},
                {"parent_asin": "OTHER", "title": "shirt", "features": ["Polyester"]},
            ]
        )

    def index(self, path: Path, signature_index_path=None) -> CatalogIndex:
        return CatalogIndex(
            path,
            retrieval_mode="signature_first",
            signature_index_path=signature_index_path,
        )

    def test_missing_index_falls_back_instead_of_raising(self) -> None:
        index = self.index(self.catalog(), "/tmp/needle-definitely-not-here.sqlite3")
        self.assertIsNotNone(index.signature_index_fallback)
        self.assertEqual(index.product_count, 2)

    def test_corrupt_index_falls_back_instead_of_raising(self) -> None:
        path = self.catalog()
        broken = path.parent / "broken.sqlite3"
        broken.write_bytes(b"this is not a database")
        index = self.index(path, broken)
        self.assertIsNotNone(index.signature_index_fallback)
        self.assertEqual(index.product_count, 2)

    def test_index_built_for_a_different_catalog_is_rebuilt_not_reused(self) -> None:
        """The binding check still holds. A stale index must never be trusted."""
        other = self.write_catalog(
            [{"parent_asin": "STALE", "title": "shirt", "features": ["Cloudsoft cotton"]}]
        )
        stale_index = other.parent / "signatures.sqlite3"
        build_signature_index(other, stale_index)

        path = self.catalog()
        index = self.index(path, stale_index)

        self.assertIsNotNone(index.signature_index_fallback)
        self.assertIn("catalog_sha256", index.signature_index_fallback)
        _, candidates = index.signature_candidates(
            ["For that, what matters is: Cloudsoft cotton."]
        )
        self.assertEqual(candidates, {"TARGET"})  # rebuilt, not the stale STALE

    def test_fallback_matches_the_in_process_path_exactly(self) -> None:
        path = self.catalog()
        fallback = self.index(path, "/tmp/needle-definitely-not-here.sqlite3")
        native = self.index(path)
        query = ["For that, what matters is: Cloudsoft cotton."]
        self.assertEqual(
            fallback.signature_candidates(query), native.signature_candidates(query)
        )

    def test_no_fallback_recorded_on_the_healthy_path(self) -> None:
        path = self.catalog()
        good = path.parent / "signatures.sqlite3"
        build_signature_index(path, good)
        self.assertIsNone(self.index(path, good).signature_index_fallback)


if __name__ == "__main__":
    unittest.main()
