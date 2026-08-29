"""Slice metrics and baseline-vs-perturbed comparison for EXP-010.

Scoring mirrors the official ``metric_summary``: a miss contributes turn 11 to
MTTC and reciprocal rank 0. ``target_recall`` is the share of sessions where the
target appeared in *any* turn's scored top-K, which separates "retrieval never
surfaced it" from "the override guard withheld the hit".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from robustness.session import SessionOutcome

_MISS_TURN = 11


def _metrics(outcomes: Sequence[SessionOutcome]) -> dict[str, object]:
    count = len(outcomes)
    if count == 0:
        return {
            "n": 0,
            "changed_n": 0,
            "hr_at_10": 0.0,
            "mrr": 0.0,
            "mttc": None,
            "target_recall": 0.0,
        }
    return {
        "n": count,
        "changed_n": sum(1 for outcome in outcomes if outcome.changed),
        "hr_at_10": round(sum(1 for o in outcomes if o.hit) / count, 6),
        "mrr": round(sum(o.reciprocal_rank for o in outcomes) / count, 6),
        "mttc": round(
            sum(o.first_hit_turn if o.first_hit_turn is not None else _MISS_TURN for o in outcomes)
            / count,
            6,
        ),
        "target_recall": round(sum(1 for o in outcomes if o.target_in_pool) / count, 6),
    }


def summarize(outcomes: Sequence[SessionOutcome]) -> dict[str, dict[str, object]]:
    """Per-slice metrics, plus per-scenario metrics inside each slice."""
    by_slice: dict[str, list[SessionOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_slice[outcome.slice].append(outcome)

    report: dict[str, dict[str, object]] = {}
    for name, group in sorted(by_slice.items()):
        by_scenario: dict[str, list[SessionOutcome]] = defaultdict(list)
        for outcome in group:
            by_scenario[outcome.scenario_type].append(outcome)
        report[name] = {
            "meaning": group[0].meaning.value,
            "overall": _metrics(group),
            "by_scenario": {
                scenario: _metrics(members) for scenario, members in sorted(by_scenario.items())
            },
        }
    return report


def compare(
    baseline: Sequence[SessionOutcome],
    perturbed: Sequence[SessionOutcome],
) -> dict[str, dict[str, object]]:
    """Per perturbed slice: metrics, deltas vs baseline, and target-removal rate.

    ``target_removal_rate`` is computed only over samples the perturbation
    actually changed, and counts a removal as: baseline surfaced the target in
    some turn, the perturbed run never did.
    """
    baseline_by_id = {outcome.sample_id: outcome for outcome in baseline}
    baseline_metrics = _metrics(baseline)

    by_slice: dict[str, list[SessionOutcome]] = defaultdict(list)
    for outcome in perturbed:
        by_slice[outcome.slice].append(outcome)

    result: dict[str, dict[str, object]] = {}
    for name, group in sorted(by_slice.items()):
        perturbed_metrics = _metrics(group)
        considered = 0
        removed = 0
        recovered = 0
        for outcome in group:
            reference = baseline_by_id.get(outcome.sample_id)
            if reference is None or not outcome.changed:
                continue
            considered += 1
            if reference.target_in_pool and not outcome.target_in_pool:
                removed += 1
            elif not reference.target_in_pool and outcome.target_in_pool:
                recovered += 1
        result[name] = {
            "meaning": group[0].meaning.value,
            "baseline": baseline_metrics,
            "perturbed": perturbed_metrics,
            "delta": {
                key: round(
                    float(perturbed_metrics[key]) - float(baseline_metrics[key]), 6
                )
                for key in ("hr_at_10", "mrr", "mttc", "target_recall")
                if baseline_metrics[key] is not None and perturbed_metrics[key] is not None
            },
            "effective_n": considered,
            "target_removal_rate": round(removed / considered, 6) if considered else None,
            "target_recovery_rate": round(recovered / considered, 6) if considered else None,
        }
    return result


def gate_failures(
    comparison: dict[str, dict[str, object]],
    *,
    max_target_removal_rate: float = 0.0,
    max_preserving_hr_drop: float = 0.02,
) -> list[str]:
    """Preregistered EXP-010 gates. Returns a list of human-readable failures.

    - no slice may raise target-removal above ``max_target_removal_rate``;
    - a meaning-preserving slice may not drop HR@10 by more than
      ``max_preserving_hr_drop``;
    - a meaning-changing slice must actually change the metrics (a slice that
      leaves everything identical is not exercising anything).
    """
    failures: list[str] = []
    for name, entry in comparison.items():
        removal = entry.get("target_removal_rate")
        if isinstance(removal, (int, float)) and removal > max_target_removal_rate:
            failures.append(f"{name}: target_removal_rate {removal} > {max_target_removal_rate}")

        delta = entry.get("delta", {})
        hr_delta = delta.get("hr_at_10") if isinstance(delta, dict) else None
        if entry.get("meaning") == "meaning_preserving":
            if isinstance(hr_delta, (int, float)) and hr_delta < -max_preserving_hr_drop:
                failures.append(
                    f"{name}: meaning-preserving HR@10 dropped {hr_delta} (limit -{max_preserving_hr_drop})"
                )
        elif entry.get("meaning") == "meaning_changing":
            if isinstance(delta, dict) and delta and all(value == 0 for value in delta.values()):
                failures.append(f"{name}: meaning-changing slice left every metric unchanged")
    return failures
