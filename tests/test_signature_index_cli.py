"""The remediation the release path prints has to actually work.

When `SIGNATURE_INDEX_SCHEMA_VERSION` moves, every asset built before the bump
is stale. `CatalogIndex` rejects it and rebuilds in process, and the bundler
refuses to ship it and prints "rebuild it with scripts/build_signature_index.py".
That command used to fail with "signature index already exists", so the loop
did not close and the stale asset stayed where it was.

The library refusal is correct and is left alone; an index is 65MB and a
function should not clobber one on its own. This is the CLI deciding, which is
where that decision belongs.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_signature_index.py"

PRODUCTS = [
    {"parent_asin": "A1", "title": "Cotton Shirt", "category": "clothing",
     "features": ["100% Cotton"], "details": {"Material": "Cotton"}},
    {"parent_asin": "A2", "title": "Leather Boot", "category": "shoes",
     "features": ["Genuine Leather"], "details": {"Material": "Leather"}},
]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True, text=True, cwd=ROOT,
    )


class BuilderReplacesAStaleIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.catalog = root / "catalog.jsonl"
        self.catalog.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS), encoding="utf-8"
        )
        self.output = root / "index.sqlite3"

    def _build(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return _run("--catalog", str(self.catalog), "--output", str(self.output), *extra)

    def _schema(self) -> str | None:
        connection = sqlite3.connect(f"file:{self.output.as_posix()}?mode=ro", uri=True)
        try:
            return dict(connection.execute("SELECT key, value FROM metadata")).get("schema_version")
        finally:
            connection.close()

    def _set_metadata(self, key: str, value: str) -> None:
        connection = sqlite3.connect(self.output)
        try:
            with connection:
                connection.execute("UPDATE metadata SET value = ? WHERE key = ?", (value, key))
        finally:
            connection.close()

    def test_a_first_build_writes_the_index(self) -> None:
        completed = self._build()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(self.output.is_file())
        self.assertTrue(json.loads(completed.stdout)["rebuilt"])

    def test_a_matching_index_is_left_alone(self) -> None:
        self._build()
        before = self.output.stat().st_mtime_ns
        completed = self._build()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["rebuilt"])
        self.assertEqual(payload["reason"], "already current")
        self.assertEqual(self.output.stat().st_mtime_ns, before, "an up-to-date index was rewritten")

    def test_a_stale_schema_is_replaced_rather_than_refused(self) -> None:
        """The case the bundler's message is about."""
        self._build()
        connection = sqlite3.connect(self.output)
        with connection:
            connection.execute("UPDATE metadata SET value = '0' WHERE key = 'schema_version'")
        connection.close()
        self.assertEqual(self._schema(), "0")

        completed = self._build()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["rebuilt"])
        self.assertIn("stale", completed.stderr)

        from needle.catalog import SIGNATURE_INDEX_SCHEMA_VERSION
        self.assertEqual(self._schema(), SIGNATURE_INDEX_SCHEMA_VERSION)

    def test_a_stale_facet_parser_is_replaced_even_when_schema_matches(self) -> None:
        """Facet rules can move without a storage-schema change."""

        self._build()
        before = self.output.stat().st_mtime_ns
        self._set_metadata("facet_parser_sha256", "stale-parser")
        completed = self._build()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["rebuilt"])
        self.assertIn("parser stale", completed.stderr)
        self.assertNotEqual(self.output.stat().st_mtime_ns, before)

    def test_an_index_bound_to_another_catalog_is_replaced(self) -> None:
        self._build()
        self.catalog.write_text(
            json.dumps(PRODUCTS[0]) + "\n", encoding="utf-8"
        )
        completed = self._build()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["rebuilt"])

    def test_force_rebuilds_a_current_index(self) -> None:
        self._build()
        completed = self._build("--force")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["rebuilt"])
        self.assertIn("forced", completed.stderr)

    def test_a_missing_catalog_is_a_clean_error(self) -> None:
        completed = _run("--catalog", str(self.output.parent / "absent.jsonl"),
                         "--output", str(self.output))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("catalog not found", completed.stderr)


if __name__ == "__main__":
    unittest.main()
