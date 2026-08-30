"""The evaluator imports `starter.agent.Agent`, so this is the shipped path.

It once resolved its signature index inside gitignored `.artifacts/`, which is
present on every developer machine and in no bundle, and construction raised
before any session ran. `scripts/bundle_rehearsal.py` covers that end to end
from a clean tree; these cover the resolution rule itself.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from starter.agent import BUNDLED_INDEX, DEVELOPMENT_INDEX, default_index


class StarterIndexResolutionTest(unittest.TestCase):
    def test_missing_indexes_resolve_to_none_rather_than_a_dead_path(self) -> None:
        # None means "rebuild from the catalog". Returning a path that is not
        # there is what scored zero.
        with mock.patch.object(Path, "is_file", return_value=False):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(default_index())

    def test_the_bundled_asset_wins_over_the_development_build(self) -> None:
        with mock.patch.object(Path, "is_file", return_value=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(default_index(), BUNDLED_INDEX)

    def test_the_development_build_is_used_when_nothing_is_bundled(self) -> None:
        def only_development(self: Path) -> bool:
            return self == DEVELOPMENT_INDEX

        with mock.patch.object(Path, "is_file", only_development):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(default_index(), DEVELOPMENT_INDEX)

    def test_the_environment_override_wins_over_both(self) -> None:
        with mock.patch.object(Path, "is_file", return_value=True):
            with mock.patch.dict(os.environ, {"NEEDLE_SIGNATURE_INDEX": "/tmp/x.sqlite3"}):
                self.assertEqual(default_index(), Path("/tmp/x.sqlite3"))

    def test_the_bundled_asset_lives_inside_the_shipped_tree(self) -> None:
        # `submission/` ships; `.artifacts/` does not. If this ever points
        # outside `submission/`, a bundle loses the asset silently.
        self.assertEqual(BUNDLED_INDEX.parent.parent.name, "submission")


if __name__ == "__main__":
    unittest.main()
