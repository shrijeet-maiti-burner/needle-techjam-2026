"""An explicit locale beats a guess where a guess cannot be right.

Script detection cannot separate kanji-only Japanese from Chinese: the
characters really are the same, so no tuning fixes it. `Agent.set_language` is
the honest answer to that ambiguity rather than a heuristic dressed up as one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.agent import Agent  # noqa: E402

CATALOG = ROOT / ".artifacts/participant-kit/techjam-conversational-search/data/catalog.jsonl"

@unittest.skipUnless(CATALOG.is_file(), "official catalog is not bootstrapped")
class LanguageOverrideTest(unittest.TestCase):
    """Script detection cannot separate kanji-only Japanese from Chinese.

    The characters really are the same, so no tuning fixes it. A caller that
    knows the customer's locale can say so instead of being stuck with a guess.
    """

    KANJI_ONLY = "革靴を購入したい"

    def test_a_pinned_language_overrides_detection(self) -> None:
        with Agent(CATALOG, explain=True) as agent:
            agent.reset("s", {})
            detected = agent.respond("s", self.KANJI_ONLY, 1, 10)["message"]
            agent.reset("t", {})
            agent.set_language("t", "ja")
            pinned = agent.respond("t", self.KANJI_ONLY, 1, 10)["message"]
        self.assertNotEqual(detected, pinned)
        self.assertIn("から始めます", pinned)

    def test_an_unsupported_code_falls_back_to_english(self) -> None:
        with Agent(CATALOG, explain=True) as agent:
            agent.reset("s", {})
            agent.set_language("s", "xx")
            self.assertIn("Starting from", agent.respond("s", self.KANJI_ONLY, 1, 10)["message"])

    def test_reset_clears_the_pin(self) -> None:
        with Agent(CATALOG, explain=True) as agent:
            agent.reset("s", {})
            agent.set_language("s", "ja")
            agent.reset("s", {})
            self.assertIn("Starting from", agent.respond("s", "I'm looking for Shoes Boots.", 1, 10)["message"])

    def test_a_blank_code_is_ignored_rather_than_pinning_nothing(self) -> None:
        with Agent(CATALOG, explain=True) as agent:
            agent.reset("s", {})
            agent.set_language("s", "   ")
            self.assertIn("Starting from", agent.respond("s", "I'm looking for Shoes Boots.", 1, 10)["message"])
