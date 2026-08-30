"""EXP-013: pin the measured question policy.

Repeated `other` on every turn that has a reply. Ten arms were measured on all
200 official public sessions at fixed retrieval and state controls; every
alternative lost, and dropping questions entirely lost by a wide margin. The
arms, their scores, and the pins are in docs/evidence/EXP_013.md and reproduce
with `python3 scripts/qpolicy_arms.py`. They are deliberately not copied here,
where nothing would notice them going stale: an earlier copy of them in this
docstring outlived the retrieval configuration they were measured on.

The reasons the assertions exist, which do not go stale. Every named-attribute
rotation loses because `customer_reply` matches `other` against any constraint
type while a named attribute matches only its own bucket, so a named attribute
can return nothing where `other` returns two values. Asking is free, because
`evaluate()` scores the slate before it reads `ask_attribute`, so the only cost
of a question is the reply it spends. And the margin against not asking is the
largest measured in this project, but it shrinks as retrieval improves, so
requote it from the record rather than from memory.

If a change here is deliberate, rerun the arms and update the evidence record.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from needle.agent import Agent


PRODUCTS = (
    {
        "parent_asin": "BLACK_SHIRT",
        "title": "Black cotton shirt",
        "categories": ["Clothing", "Shirts"],
        "features": ["soft cotton"],
        "details": {"Color": "Black"},
        "store": "Example",
        "description": "casual button shirt",
    },
    {
        "parent_asin": "BLUE_SHOES",
        "title": "Blue running shoes",
        "categories": ["Shoes", "Running"],
        "features": ["lightweight"],
        "details": {"Color": "Blue"},
        "store": "Example",
        "description": "road running trainer",
    },
)


class QuestionPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.temporary.name) / "catalog.jsonl"
        self.catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in PRODUCTS),
            encoding="utf-8",
        )
        self.agent = Agent(self.catalog_path)
        self.agent.reset("session", {})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _asked(self) -> list[str | None]:
        return [
            self.agent.respond("session", f"black cotton shirt {turn}", turn, 10)[
                "ask_attribute"
            ]
            for turn in range(1, 11)
        ]

    def test_asks_other_on_every_answerable_turn(self) -> None:
        self.assertEqual(self._asked()[:9], ["other"] * 9)

    def test_never_goes_silent_while_a_reply_is_still_possible(self) -> None:
        # Arm C. Silence is the worst arm measured, because the customer
        # discloses nothing; arm D shows that stopping after the constraints
        # look exhausted still loses the boundary and override slices, which
        # each need a third question the agent cannot predict in advance.
        self.assertNotIn(None, self._asked()[:9])

    def test_does_not_ask_on_the_final_turn(self) -> None:
        # Turn 10 has no reply, so a question there is unobservable.
        self.assertIsNone(self._asked()[9])

    def test_policy_does_not_drift_to_a_named_attribute(self) -> None:
        # Every named-attribute arm lost: `other` matches any constraint type,
        # a named attribute matches only its own bucket and can return nothing
        # where `other` would have returned two values.
        self.assertEqual(set(self._asked()[:9]), {"other"})


if __name__ == "__main__":
    unittest.main()
