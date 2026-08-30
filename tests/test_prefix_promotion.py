"""Pin the EXP-023 promotion rules that the measured arm depends on.

`_promote` turns the `(coarse_category, disclosed prefix)` bucket from a filter
into a ranking. Three properties carry the result and none of them are visible
in the aggregate score, so they are asserted here:

* the deepest disclosure wins, because a longer prefix is strictly more
  evidence than a shorter one;
* among equally deep parses the smaller bucket wins, because it is the more
  resolved one;
* the bucket is returned whole, ordered by `rating_number` descending with a
  deterministic tie-break, because the caller walks it one product per turn and
  a non-deterministic order would make the arm unreproducible.

`scripts/emit_gate_arms.py` imports the official evaluator, which is a
development artifact and absent from CI, so these skip when the kit is not
bootstrapped. The measured runs in `docs/evidence/EXP_023.md` are the record
that the arm behaves this way end to end.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from scripts import emit_gate_arms as arms
except Exception:  # noqa: BLE001 - the kit is absent in CI
    arms = None


@unittest.skipIf(arms is None, "official participant kit is not bootstrapped")
class PromoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = (
            dict(arms._CATEGORY_INDEX),
            dict(arms._CATEGORY_SET_INDEX),
            dict(arms._PREFIX_INDEX),
            dict(arms._FIRST4_INDEX),
            dict(arms._POPULARITY),
        )
        for table in (arms._CATEGORY_INDEX, arms._CATEGORY_SET_INDEX,
                      arms._PREFIX_INDEX, arms._FIRST4_INDEX, arms._POPULARITY):
            table.clear()

    def tearDown(self) -> None:
        for table, saved in zip(
            (arms._CATEGORY_INDEX, arms._CATEGORY_SET_INDEX,
             arms._PREFIX_INDEX, arms._FIRST4_INDEX, arms._POPULARITY),
            self.saved,
        ):
            table.clear()
            table.update(saved)

    def test_bucket_is_ordered_by_popularity_descending(self) -> None:
        arms._POPULARITY.update({"A": 5.0, "B": 900.0, "C": 12.0})
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["A", "B", "C"]
        order = arms._promote(["For that, what matters is: cotton."], "shirts", True, 100)
        self.assertEqual(order, ["B", "C", "A"])

    def test_ties_break_on_asin_so_the_walk_is_reproducible(self) -> None:
        arms._POPULARITY.update({"zzz": 7.0, "aaa": 7.0, "mmm": 7.0})
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["zzz", "aaa", "mmm"]
        order = arms._promote(["For that, what matters is: cotton."], "shirts", True, 100)
        self.assertEqual(order, ["aaa", "mmm", "zzz"])

    def test_a_deeper_prefix_beats_a_shallower_one(self) -> None:
        arms._POPULARITY.update({"A": 1.0, "B": 1.0})
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["A"]
        arms._CATEGORY_INDEX[("shirts", ("cotton", "blue"))] = ["B"]
        order = arms._promote(
            ["For that, what matters is: cotton.", "For that, what matters is: blue."],
            "shirts", True, 100,
        )
        self.assertEqual(order, ["B"])

    def test_a_bucket_over_the_cap_is_not_a_shortlist_worth_walking(self) -> None:
        arms._POPULARITY.update({"A": 1.0, "B": 1.0, "C": 1.0})
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["A", "B", "C"]
        self.assertEqual(
            arms._promote(["For that, what matters is: cotton."], "shirts", True, 2), []
        )

    def test_nothing_disclosed_promotes_nothing_unless_asked(self) -> None:
        arms._POPULARITY.update({"A": 9.0, "B": 1.0})
        arms._CATEGORY_INDEX[("shirts", ())] = ["A", "B"]
        self.assertEqual(arms._promote([], "shirts", True, 100), [])
        # `catpop`, the rejected arm, is the only caller that opts in.
        self.assertEqual(
            arms._promote([], "shirts", True, 100, empty_prefix=True), ["A", "B"]
        )

    def test_the_category_key_is_required_for_the_category_index(self) -> None:
        arms._POPULARITY.update({"A": 9.0})
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["A"]
        self.assertEqual(
            arms._promote(["For that, what matters is: cotton."], "shirts", False, 100), []
        )


if __name__ == "__main__":
    unittest.main()
