from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "demo" / "needle-lens.html"


class LensArtifactTest(unittest.TestCase):
    def test_console_is_self_contained_and_discloses_policy_boundary(self) -> None:
        source = HTML.read_text(encoding="utf-8")
        self.assertIn("Target-blind runtime certificate", source)
        self.assertIn("human-shopping shadow", source)
        self.assertIn("/api/session", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("<script src=", source)
        self.assertNotIn("<link rel=", source)

    def test_dynamic_session_content_is_written_as_text(self) -> None:
        source = HTML.read_text(encoding="utf-8")
        self.assertIn("node.textContent = value", source)
        self.assertNotIn("innerHTML", source)


if __name__ == "__main__":
    unittest.main()
