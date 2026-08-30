"""The bundled signature index must actually load.

`CatalogIndex` treats the bundled asset as an optimisation: if it is missing,
unreadable, or built against a different catalog or schema, construction falls
back to rebuilding in process rather than raising. That is the right behaviour
-- raising would abort the agent before any session runs and score zero -- but
it is silent, and silence is how the asset rotted.

It shipped built against `schema_version` 1 while the code had moved to 6. The
mismatch was caught, swallowed, and cost 21 seconds of rebuild on every single
run, with 32MB of dead weight in the bundle for nothing. Nothing failed, so
nothing noticed.

This is the guard. It asserts the fallback did *not* fire, which is the one
thing the production path cannot tell you on its own.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.catalog import SIGNATURE_INDEX_SCHEMA_VERSION, sha256_file  # noqa: E402

CATALOG = ROOT / ".artifacts/participant-kit/techjam-conversational-search/data/catalog.jsonl"
ASSET = ROOT / "submission/assets/catalog-signatures.sqlite3"


@unittest.skipUnless(ASSET.is_file(), "bundled index is not present")
class BundledIndexTest(unittest.TestCase):
    def _metadata(self) -> dict[str, str]:
        connection = sqlite3.connect(f"file:{ASSET.as_posix()}?mode=ro", uri=True)
        try:
            return dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()

    def test_the_schema_matches_the_code_that_reads_it(self) -> None:
        self.assertEqual(
            self._metadata().get("schema_version"), SIGNATURE_INDEX_SCHEMA_VERSION
        )

    @unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
    def test_the_asset_is_bound_to_the_catalog_it_ships_with(self) -> None:
        metadata = self._metadata()
        self.assertEqual(metadata.get("catalog_sha256"), sha256_file(CATALOG))

    @unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
    def test_the_submission_agent_uses_it_rather_than_rebuilding(self) -> None:
        """The assertion that would have caught the stale asset."""
        from submission.agent import Agent

        with Agent(catalog_path=str(CATALOG)) as agent:
            self.assertIsNone(
                agent.catalog.signature_index_fallback,
                "bundled index was rejected and silently rebuilt in process",
            )
            self.assertIsNotNone(agent.catalog.signature_index_path)


if __name__ == "__main__":
    unittest.main()
