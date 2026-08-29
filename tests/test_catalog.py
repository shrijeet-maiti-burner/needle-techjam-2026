from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.catalog import CatalogIndex


class CatalogValidationTest(unittest.TestCase):
    def write_catalog(self, products: list[dict]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.jsonl"
        path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        return path

    def test_rejects_duplicate_identifiers(self) -> None:
        path = self.write_catalog(
            [
                {"parent_asin": "DUPLICATE", "title": "one"},
                {"parent_asin": "DUPLICATE", "title": "two"},
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate parent_asin"):
            CatalogIndex(path)

    def test_rejects_missing_identifier(self) -> None:
        path = self.write_catalog([{"title": "missing id"}])
        with self.assertRaisesRegex(ValueError, "missing parent_asin"):
            CatalogIndex(path)


if __name__ == "__main__":
    unittest.main()
