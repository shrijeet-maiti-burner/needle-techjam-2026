"""Paired analysis of a `popularity_sweep.py` result.

The first sweep compared whole-set aggregates across two seeds and found them
disagreeing by 0.002148 and 0.000300, which was recorded as a noise floor of
roughly 0.003 for a 600-session draw. That number is the spread of the absolute
score under a fresh draw of targets. It is the wrong scale against which to
judge a difference between two arms, and it is far too wide, because both arms
run over the same sessions: the draw is common to them and cancels.

This reads the per-session rows and differences the arms session by session, so
what is estimated is the mean of the paired difference and the uncertainty of
that mean. Both are reported alongside the between-seed spread of each arm's
absolute score, which is what makes the difference in scale visible.

    python3 scripts/analyze_sweep.py .artifacts/sweeps/popularity-seeds.json

Reported per comparison: the paired mean difference, its standard error, a
normal-approximation 95% interval, a bootstrap 95% interval resampling sessions,
and a sign count over the sessions the two arms actually score differently. The
bootstrap makes no normality assumption, which matters because the per-session
score is bounded and lumpy; agreement between the two intervals is a check that
the approximation holds, not a second result.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Sequence

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.popularity_sweep import session_score  # noqa: E402


def paired_differences(left: list[dict], right: list[dict]) -> list[float]:
    """Per-session score(left) - score(right), aligned by sample id."""
    right_by_id = {item["sample_id"]: item for item in right}
    if len(right_by_id) != len(right):
        raise SystemExit("duplicate sample ids; sessions cannot be paired")
    missing = [item["sample_id"] for item in left if item["sample_id"] not in right_by_id]
    if missing:
        raise SystemExit(f"{len(missing)} sessions are not present in both arms")
    return [session_score(item) - session_score(right_by_id[item["sample_id"]]) for item in left]


def bootstrap_interval(values: Sequence[float], resamples: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    count = len(values)
    means = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(count):
            total += values[rng.randrange(count)]
        means.append(total / count)
    means.sort()
    low = means[int(0.025 * resamples)]
    high = means[min(resamples - 1, int(0.975 * resamples))]
    return low, high


def sign_test(better: int, worse: int) -> float:
    """Exact two-sided binomial p over the sessions the arms score differently.

    The mean difference is dominated by a few sessions that swing by up to a
    whole point, because a session either finds the target or does not. This
    asks the weaker but steadier question: among sessions that changed at all,
    did more of them get worse than better? It reports direction, not size, and
    a direction with a negligible size is exactly what a prior at low strength
    is expected to have.
    """
    trials = better + worse
    if trials == 0:
        return 1.0
    tail = min(better, worse)
    cumulative = sum(math.comb(trials, index) for index in range(tail + 1))
    # Numerator and denominator both overflow a float long before they cancel:
    # at 1097 discordant sessions 2**trials will not convert, while the ratio it
    # forms is an ordinary probability. Divide in log space instead.
    return min(1.0, math.exp(math.log(2.0) + math.log(cumulative) - trials * math.log(2.0)))


def describe(values: Sequence[float], resamples: int, seed: int) -> dict[str, float]:
    mean = statistics.fmean(values)
    standard_error = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    low, high = bootstrap_interval(values, resamples, seed)
    positive = sum(1 for value in values if value > 0)
    negative = sum(1 for value in values if value < 0)
    return {
        "n": len(values),
        "mean": mean,
        "standard_error": standard_error,
        "normal_low": mean - 1.96 * standard_error,
        "normal_high": mean + 1.96 * standard_error,
        "bootstrap_low": low,
        "bootstrap_high": high,
        "better": positive,
        "worse": negative,
        "tied": len(values) - positive - negative,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=Path, nargs="?", default=ROOT / ".artifacts/sweeps/popularity-seeds.json")
    parser.add_argument("--resamples", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--control-prefix", default="control seed")
    arguments = parser.parse_args()

    payload = json.loads(arguments.payload.read_text(encoding="utf-8"))
    runs: dict[tuple[str, float], dict] = {
        (run["dataset"], float(run["strength"])): run for run in payload["runs"]
    }
    datasets = list(dict.fromkeys(run["dataset"] for run in payload["runs"]))
    strengths = sorted({float(run["strength"]) for run in payload["runs"]})

    print("## Reported score by set and strength\n")
    header = "strength  " + "".join(f"{name:>22s}" for name in datasets)
    print(header)
    for strength in strengths:
        row = f"  {strength:.2f}    "
        for name in datasets:
            run = runs.get((name, strength))
            row += f"{run['summary']['recommended_technical_score']:22.6f}" if run else f"{'--':>22s}"
        print(row)

    controls = [name for name in datasets if name.startswith(arguments.control_prefix)]
    if len(controls) > 1:
        print("\n## Between-seed spread of the absolute score (the old noise floor)\n")
        for strength in strengths:
            scores = [
                runs[(name, strength)]["summary"]["recommended_technical_score"]
                for name in controls
                if (name, strength) in runs
            ]
            print(
                f"  {strength:.2f}  min {min(scores):.6f}  max {max(scores):.6f}  "
                f"range {max(scores) - min(scores):.6f}  sd {statistics.stdev(scores):.6f}"
            )

    comparisons = [(strengths[index], strengths[index - 1]) for index in range(1, len(strengths))]
    if len(strengths) > 2:
        comparisons.append((strengths[-1], strengths[0]))

    def report(label: str, differences: list[float]) -> None:
        stats = describe(differences, arguments.resamples, arguments.seed)
        print(
            f"  {label:20s} n {stats['n']:5d}  mean {stats['mean']:+.6f}  "
            f"se {stats['standard_error']:.6f}  "
            f"95% [{stats['bootstrap_low']:+.6f}, {stats['bootstrap_high']:+.6f}]  "
            f"{int(stats['worse'])} worse / {int(stats['better'])} better  "
            f"p {sign_test(int(stats['better']), int(stats['worse'])):.5f}"
        )

    for left, right in comparisons:
        print(f"\n## Paired difference, popularity {left:.2f} minus {right:.2f}\n")
        pooled: list[float] = []
        for name in datasets:
            if (name, left) not in runs or (name, right) not in runs:
                continue
            differences = paired_differences(runs[(name, left)]["sessions"], runs[(name, right)]["sessions"])
            report(name, differences)
            if name in controls:
                pooled.extend(differences)
        if pooled:
            print()
            report("pooled controls", pooled)


if __name__ == "__main__":
    main()
