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


@unittest.skipIf(arms is None, "official participant kit is not bootstrapped")
class OpeningGuessTest(unittest.TestCase):
    """The turn-one guess is a fallback, and the distinction is load-bearing.

    Promoting the empty prefix on *every* turn measured -0.110413 on the shape
    holdout with hit rate 0.9850 -> 0.8750 (EXP_023.md). Confining it to turn
    one, and only where the deeper bucket has nothing, is what makes it a swap
    of one guess for another rather than a walk down a category-sized list.
    """

    def setUp(self) -> None:
        for table in (arms._CATEGORY_INDEX, arms._CATEGORY_SET_INDEX,
                      arms._PREFIX_INDEX, arms._FIRST4_INDEX, arms._POPULARITY):
            table.clear()

    def test_a_disclosed_prefix_outranks_the_bare_category(self) -> None:
        arms._POPULARITY.update({"POPULAR": 9000.0, "MATCHED": 1.0})
        arms._CATEGORY_INDEX[("shirts", ())] = ["POPULAR", "MATCHED"]
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["MATCHED"]
        message = ["For that, what matters is: cotton."]
        # The deeper bucket answers, so the opening guess must never be reached.
        self.assertEqual(arms._promote(message, "shirts", True, 100), ["MATCHED"])

    def test_the_bare_category_answers_only_when_nothing_is_disclosed(self) -> None:
        arms._POPULARITY.update({"POPULAR": 9000.0, "OTHER": 1.0})
        arms._CATEGORY_INDEX[("shirts", ())] = ["OTHER", "POPULAR"]
        self.assertEqual(
            arms._promote([], "shirts", True, 100, empty_prefix=True),
            ["POPULAR", "OTHER"],
        )
        self.assertEqual(arms._promote([], "shirts", True, 100), [])


@unittest.skipIf(arms is None, "official participant kit is not bootstrapped")
class SurfaceRobustnessTest(unittest.TestCase):
    """The arm matches on surface text, so it has to normalize it itself.

    `SessionState.observe` folds accents for the override trigger, but the arm
    reads `user_message` and `state.messages` for its own index lookups. Before
    these, one inserted "um," or one accented category was enough to switch
    promotion off for a whole session: EXP_023.md measures the `paraphrase`
    slice going from -0.090 hit rate to -0.025 and `typo` target removal from
    0.045 to 0.005 once this normalization and the release rules are in.
    """

    def test_discourse_fillers_do_not_hide_the_marker(self) -> None:
        plain = arms._clause_parses("For that, what matters is: 100% Cotton.")
        filled = arms._clause_parses("For that, um, what matters is: 100% Cotton.")
        self.assertEqual(plain, filled)
        self.assertNotEqual(plain, [()])

    def test_multiword_fillers_are_stripped(self) -> None:
        plain = arms._clause_parses("For that, what matters is: Imported.")
        for token in ("you know", "sort of", "i guess", "to be honest"):
            with self.subTest(token=token):
                self.assertEqual(
                    arms._clause_parses(f"For that, {token}, what matters is: Imported."),
                    plain,
                )

    def test_the_opening_category_is_accent_folded(self) -> None:
        self.assertEqual(
            arms._opening_category("I'm looking for Sandàls, but I'm still exploring"),
            arms._opening_category("I'm looking for Sandals, but I'm still exploring"),
        )

    def test_a_real_constraint_containing_a_filler_word_survives(self) -> None:
        # "sort" and "kind" are stripped only as discourse markers; a value the
        # customer actually states still has to reach the index intact.
        parses = arms._clause_parses("For that, what matters is: Assorted Colors.")
        self.assertEqual(parses, [("assorted colors",)])


@unittest.skipIf(arms is None, "official participant kit is not bootstrapped")
class WalkedOutBucketTest(unittest.TestCase):
    """A bucket whose every member has been shown has nothing left to offer.

    Re-emitting its head spends the turn on a product the evaluator has already
    seen and passed over, and does so again every turn until the release floor.
    Releasing instead took MRR from 0.997500 to 1.000000 on the public set:
    all 200 sessions convert at rank one. See EXP_023.md.
    """

    def test_the_walk_visits_each_member_once_in_popularity_order(self) -> None:
        for table in (arms._CATEGORY_INDEX, arms._POPULARITY):
            table.clear()
        arms._POPULARITY.update({"HI": 900.0, "MID": 50.0, "LO": 1.0})
        arms._CATEGORY_INDEX[("shirts", ("cotton",))] = ["LO", "HI", "MID"]
        order = arms._promote(["For that, what matters is: cotton."], "shirts", True, 100)
        self.assertEqual(order, ["HI", "MID", "LO"])
        # The caller walks this list against its own `shown` set, so the
        # ordering being total and deterministic is what makes "walked out"
        # a well-defined state rather than an infinite loop on the head.
        self.assertEqual(len(order), len(set(order)))


@unittest.skipIf(arms is None, "official participant kit is not bootstrapped")
class CategoryResolutionTest(unittest.TestCase):
    """The stated category comes from a closed vocabulary, so a miss is recoverable."""

    def setUp(self) -> None:
        for table in (arms._CATEGORY_INDEX, arms._KNOWN_CATEGORIES):
            table.clear()
        for name in ("watches wrist watches", "handbags wallets totes", "shoes boots"):
            arms._CATEGORY_INDEX[(name, ())] = ["A"]
            arms._KNOWN_CATEGORIES[name] = frozenset(name.split())

    def test_an_exact_category_is_returned_unchanged(self) -> None:
        self.assertEqual(arms._resolve_category("shoes boots"), "shoes boots")

    def test_a_substituted_word_resolves_to_the_known_category(self) -> None:
        self.assertEqual(
            arms._resolve_category("wristwatches wrist watches"), "watches wrist watches"
        )

    def test_an_unknown_category_resolves_to_nothing_rather_than_a_guess(self) -> None:
        self.assertEqual(arms._resolve_category("garden hoses"), "")

    def test_a_bare_majority_is_not_enough(self) -> None:
        # One shared token out of three is not a resolution, it is a coincidence.
        self.assertEqual(arms._resolve_category("watches"), "")
