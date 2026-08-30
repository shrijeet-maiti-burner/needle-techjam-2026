"""Pin the per-session decomposition the popularity sweep is analysed with.

`recommended_technical_score` is reported as an aggregate, so two arms can only
be compared set against set unless the score is written as a mean over sessions.
It is one, exactly:

    score_i = 0.50 * hit_i + 0.30 * reciprocal_rank_i + 0.20 * (11 - ttc_i) / 10

Efficiency is `(11 - mttc) / 10` clipped to [0, 1], and `mttc` is the mean of
`ttc_i`, which lies in [1, 11] because a miss counts as `MAX_TURNS + 1`. The clip
therefore never binds and the mean passes through. If it ever did bind, the
decomposition would be wrong and the paired analysis with it, so the clip is
asserted here rather than assumed.

These tests carry the algebra, not the official evaluator, which is a
development artifact and absent from CI. `popularity_sweep.py --self-check`
compares the same decomposition against the evaluator's own arithmetic on every
real run.
"""
from __future__ import annotations

import statistics
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_sweep import paired_differences, sign_test  # noqa: E402
from scripts.popularity_sweep import session_score  # noqa: E402


def session(sample_id: str, first_hit_turn: int | None) -> dict:
    """A session row shaped like the evaluator's, scored consistently."""
    return {
        "sample_id": sample_id,
        "scenario_type": "buying",
        "hit": first_hit_turn is not None,
        "first_hit_turn": first_hit_turn,
        "reciprocal_rank": 0.0 if first_hit_turn is None else 1.0 / first_hit_turn,
    }


def official_score(sessions: list[dict]) -> float:
    """The evaluator's aggregate arithmetic, from `metric_summary` and `evaluate`."""
    hit_rate = sum(int(item["hit"]) for item in sessions) / len(sessions)
    mrr = statistics.fmean(item["reciprocal_rank"] for item in sessions)
    mttc = statistics.fmean(
        11 if item["first_hit_turn"] is None else item["first_hit_turn"] for item in sessions
    )
    efficiency = max(0.0, min(1.0, (11.0 - mttc) / 10.0))
    return 0.50 * hit_rate + 0.30 * mrr + 0.20 * efficiency


class SessionScoreTest(unittest.TestCase):
    def test_mean_reproduces_the_aggregate_score(self) -> None:
        sessions = [
            session("a", 1),
            session("b", 4),
            session("c", None),
            session("d", 10),
            session("e", 2),
        ]
        mean = statistics.fmean(session_score(item) for item in sessions)
        self.assertAlmostEqual(mean, official_score(sessions), places=12)

    def test_bounds_are_a_perfect_and_an_empty_session(self) -> None:
        self.assertAlmostEqual(session_score(session("a", 1)), 1.0, places=12)
        self.assertAlmostEqual(session_score(session("a", None)), 0.0, places=12)

    def test_efficiency_clip_never_binds(self) -> None:
        # Every session missing gives the worst possible mttc; every session
        # hitting at turn one gives the best. Neither reaches the clip.
        for sessions in ([session("a", None)], [session("a", 1)]):
            mttc = statistics.fmean(
                11 if item["first_hit_turn"] is None else item["first_hit_turn"] for item in sessions
            )
            self.assertGreaterEqual((11.0 - mttc) / 10.0, 0.0)
            self.assertLessEqual((11.0 - mttc) / 10.0, 1.0)

    def test_a_miss_costs_a_full_turn_budget(self) -> None:
        hit_at_ten = session_score(session("a", 10))
        miss = session_score(session("a", None))
        self.assertGreater(hit_at_ten, miss)


class PairedDifferenceTest(unittest.TestCase):
    def test_pairs_by_sample_id_not_by_position(self) -> None:
        left = [session("a", 1), session("b", 5)]
        right = [session("b", 5), session("a", 3)]
        differences = paired_differences(left, right)
        self.assertAlmostEqual(differences[0], session_score(session("a", 1)) - session_score(session("a", 3)))
        self.assertAlmostEqual(differences[1], 0.0)

    def test_identical_arms_difference_to_zero(self) -> None:
        arm = [session("a", 1), session("b", None), session("c", 7)]
        self.assertEqual(paired_differences(arm, list(reversed(arm))), [0.0, 0.0, 0.0])

    def test_unpairable_arms_are_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            paired_differences([session("a", 1)], [session("z", 1)])

    def test_duplicate_sample_ids_are_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            paired_differences([session("a", 1)], [session("a", 1), session("a", 2)])


if __name__ == "__main__":
    unittest.main()


class SignTestTest(unittest.TestCase):
    """The sign test reports direction over the sessions that changed at all."""

    def test_even_split_is_not_evidence(self) -> None:
        self.assertAlmostEqual(sign_test(50, 50), 1.0, places=6)

    def test_lopsided_split_is_evidence(self) -> None:
        self.assertLess(sign_test(10, 40), 0.001)

    def test_no_discordant_sessions_is_not_evidence(self) -> None:
        self.assertEqual(sign_test(0, 0), 1.0)

    def test_direction_does_not_change_the_p_value(self) -> None:
        self.assertAlmostEqual(sign_test(303, 361), sign_test(361, 303), places=12)

    def test_large_counts_do_not_overflow(self) -> None:
        # 2 ** trials stops converting to float well before this, so the ratio
        # has to be taken in log space. A whole run was lost to that once.
        self.assertLess(sign_test(473, 624), 0.001)
        self.assertGreater(sign_test(473, 624), 0.0)
