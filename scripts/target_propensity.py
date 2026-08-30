"""EXP-024: catalog-only target-propensity prior.

The released target labels may reveal broad sampling tendencies, but they do
not justify a product-identity lookup table.  This experiment therefore fits a
small pairwise linear model over participant-visible, non-textual catalog
metadata.  It is used only to reorder the promotion bucket on turn one.

The public headline is out-of-fold: every scored public session is evaluated
with coefficients fitted without that session.  A full-data model is also run
on three target-disjoint matched panels.  Neither public identifiers nor text
tokens are model features or serialized output.

    python scripts/target_propensity.py \
        --output .artifacts/experiments/exp-024.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
DEFAULT_ASSET = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"

FEATURE_NAMES = (
    "log_rating_number",
    "average_rating",
    "has_price",
    "log_price",
    "available_year",
    "has_available_date",
    "log_feature_count",
    "log_detail_count",
    "log_title_length",
    "log_description_length",
    "category_depth",
    "log_store_frequency",
)


def _number(value: object) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _available_year(product: Mapping[str, object]) -> int:
    details = product.get("details")
    if not isinstance(details, Mapping):
        return 0
    match = re.search(r"(?:19|20)\d{2}", str(details.get("Date First Available", "")))
    return int(match.group()) if match is not None else 0


def _sequence_length(value: object) -> int:
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return len(value)
    return int(value not in (None, ""))


def _description_length(value: object) -> int:
    if isinstance(value, list):
        return sum(len(str(item)) for item in value)
    return len(str(value)) if value not in (None, "") else 0


def metadata_features(
    product: Mapping[str, object],
    *,
    store_frequency: int,
) -> tuple[float, ...]:
    """Return the complete allowlisted feature vector.

    Product identifiers, title/store tokens, categories, feature text, and
    every session field are deliberately absent.  Counts and lengths measure
    catalog completeness without encoding product identity.
    """

    year = _available_year(product)
    price = max(0.0, _number(product.get("price")))
    return (
        math.log1p(max(0.0, _number(product.get("rating_number")))),
        max(0.0, min(5.0, _number(product.get("average_rating")))),
        float(product.get("price") not in (None, "")),
        math.log1p(price),
        float(year),
        float(year > 0),
        math.log1p(_sequence_length(product.get("features"))),
        math.log1p(_sequence_length(product.get("details"))),
        math.log1p(len(str(product.get("title") or ""))),
        math.log1p(_description_length(product.get("description"))),
        float(_sequence_length(product.get("categories"))),
        math.log1p(max(0, int(store_frequency))),
    )


@dataclass(frozen=True, slots=True)
class FeatureTable:
    values: dict[str, tuple[float, ...]]
    scale: tuple[float, ...]

    def standardized(self, parent_asin: str) -> tuple[float, ...]:
        raw = self.values[parent_asin]
        return tuple(value / scale for value, scale in zip(raw, self.scale))


def build_feature_table(products: Mapping[str, Mapping[str, object]]) -> FeatureTable:
    stores = Counter(
        str(product.get("store") or "").strip().casefold()
        for product in products.values()
    )
    values = {
        parent_asin: metadata_features(
            product,
            store_frequency=stores[str(product.get("store") or "").strip().casefold()],
        )
        for parent_asin, product in products.items()
    }
    columns = tuple(zip(*values.values()))
    # Pairwise differences cancel feature means.  Scaling alone keeps gradient
    # magnitudes comparable without baking public-label statistics into the
    # transform.
    scale = tuple(
        statistics.pstdev(column) or 1.0
        for column in columns
    )
    return FeatureTable(values=values, scale=scale)


@dataclass(frozen=True, slots=True)
class PairwiseLinearModel:
    weights: tuple[float, ...]

    def score(self, features: Sequence[float]) -> float:
        return sum(weight * value for weight, value in zip(self.weights, features))


def _stable_sample(values: Iterable[str], *, seed: str, limit: int) -> list[str]:
    return sorted(
        values,
        key=lambda value: hashlib.sha256(f"{seed}\0{value}".encode()).digest(),
    )[:limit]


def _sigmoid_negative(margin: float) -> float:
    """Return sigmoid(-margin) without overflow."""

    if margin >= 0:
        exponential = math.exp(-margin)
        return exponential / (1.0 + exponential)
    exponential = math.exp(margin)
    return 1.0 / (1.0 + exponential)


def fit_pairwise_model(
    samples: Sequence[Mapping[str, Any]],
    *,
    products: Mapping[str, Mapping[str, object]],
    features: FeatureTable,
    buckets: Mapping[tuple[str, str], Sequence[str]],
    positive_ids: frozenset[str],
    epochs: int = 160,
    negatives_per_positive: int = 64,
    learning_rate: float = 0.35,
    l2: float = 0.02,
) -> PairwiseLinearModel:
    """Fit deterministic pairwise logistic regression against bucket peers."""

    from needle.catalog import card_signature_sequence, coarse_category_signature

    pairs: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
    for sample in samples:
        target = str(sample["ground_truth"]["parent_asin"])
        product = products[target]
        category = coarse_category_signature(product.get("categories"))
        sequence = card_signature_sequence(dict(product))
        bucket_kind = sequence[0] if sample["scenario_type"] == "buying" and sequence else ""
        candidates = [
            parent_asin
            for parent_asin in buckets[(category, bucket_kind)]
            if parent_asin != target and parent_asin not in positive_ids
        ]
        # The rank-one decision is made against the popularity head.  Keep half
        # the negatives from that hard boundary and half as a deterministic
        # coverage sample from the rest of the bucket.
        hard_limit = negatives_per_positive // 2
        hard = sorted(
            candidates,
            key=lambda parent_asin: (
                -_number(products[parent_asin].get("rating_number")),
                parent_asin,
            ),
        )[:hard_limit]
        remaining = (parent_asin for parent_asin in candidates if parent_asin not in set(hard))
        sampled = _stable_sample(
            remaining,
            seed=str(sample.get("sample_id", target)),
            limit=negatives_per_positive - len(hard),
        )
        positive = features.standardized(target)
        pairs.extend((positive, features.standardized(parent_asin)) for parent_asin in (*hard, *sampled))

    if not pairs:
        raise ValueError("no pairwise training examples")
    weights = [0.0] * len(FEATURE_NAMES)
    # Start from the catalog's already-strong monotone popularity prior; the
    # optimizer must justify every departure from it.
    weights[FEATURE_NAMES.index("log_rating_number")] = 1.0
    rng = random.Random("exp-024-pair-order")
    for epoch in range(epochs):
        rng.shuffle(pairs)
        gradient = [0.0] * len(weights)
        for positive, negative in pairs:
            difference = tuple(left - right for left, right in zip(positive, negative))
            margin = sum(weight * value for weight, value in zip(weights, difference))
            residual = _sigmoid_negative(margin)
            for index, value in enumerate(difference):
                gradient[index] += residual * value
        step = learning_rate / math.sqrt(epoch + 1.0)
        count = float(len(pairs))
        for index in range(len(weights)):
            weights[index] += step * (gradient[index] / count - l2 * weights[index])
    return PairwiseLinearModel(tuple(weights))


def build_buckets(
    products: Mapping[str, Mapping[str, object]],
) -> dict[tuple[str, str], tuple[str, ...]]:
    from needle.catalog import card_signature_sequence, coarse_category_signature

    buckets: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for parent_asin, product in products.items():
        category = coarse_category_signature(product.get("categories"))
        buckets[(category, "")].append(parent_asin)
        sequence = card_signature_sequence(dict(product))
        if sequence:
            buckets[(category, sequence[0])].append(parent_asin)
    return {
        key: tuple(sorted(values))
        for key, values in buckets.items()
    }


def stratified_folds(
    samples: Sequence[Mapping[str, Any]],
    *,
    count: int,
) -> tuple[tuple[int, ...], ...]:
    if count < 2:
        raise ValueError("fold count must be at least two")
    folds: list[list[int]] = [[] for _ in range(count)]
    grouped: defaultdict[str, list[int]] = defaultdict(list)
    for index, sample in enumerate(samples):
        grouped[str(sample["scenario_type"])].append(index)
    for scenario, indices in sorted(grouped.items()):
        ordered = sorted(
            indices,
            key=lambda index: hashlib.sha256(
                f"{scenario}\0{samples[index]['sample_id']}".encode()
            ).digest(),
        )
        for offset, index in enumerate(ordered):
            folds[offset % count].append(index)
    return tuple(tuple(sorted(fold)) for fold in folds)


class PropensityAgent:
    """Experiment-only wrapper that changes turn-one promotion ordering."""

    def __init__(
        self,
        catalog_path: str | Path,
        *,
        feature_table: FeatureTable,
        model: PairwiseLinearModel,
        signature_index_path: str | Path,
    ) -> None:
        from needle.agent import Agent
        from needle.presets import PRIMARY_AGENT_KWARGS

        self.agent = Agent(
            catalog_path,
            **{
                **PRIMARY_AGENT_KWARGS,
                "signature_index_path": signature_index_path,
            },
        )
        original = self.agent.catalog.rank_disclosure_bucket

        def ranked(messages: Iterable[str], **kwargs: object) -> tuple[str, ...]:
            candidates = original(messages, **kwargs)
            if not bool(kwargs.get("include_empty")) or len(candidates) < 2:
                return candidates
            return tuple(
                sorted(
                    candidates,
                    key=lambda parent_asin: (
                        -model.score(feature_table.standardized(parent_asin)),
                        parent_asin,
                    ),
                )
            )

        self.agent.catalog.rank_disclosure_bucket = ranked  # type: ignore[method-assign]

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.agent.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return self.agent.respond(session_id, user_message, turn, top_k)

    def close(self) -> None:
        self.agent.close()


def _aggregate_sessions(sessions: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    from evaluator.local_evaluator import metric_summary

    overall = metric_summary(list(sessions))
    mttc = float(overall["mttc"])
    efficiency = max(0.0, min(1.0, (11.0 - mttc) / 10.0))
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[str(session["scenario_type"])].append(dict(session))
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(
            0.50 * float(overall["hit_rate_at_10"])
            + 0.30 * float(overall["mrr"])
            + 0.20 * efficiency,
            6,
        ),
        "scenario_metrics": {
            name: metric_summary(items)
            for name, items in sorted(grouped.items())
        },
    }


def _evaluate(
    samples: Sequence[Mapping[str, Any]],
    *,
    catalog_path: Path,
    catalog_ids: set[str],
    categories: dict[str, list[str]],
    products: dict[str, dict],
    feature_table: FeatureTable,
    model: PairwiseLinearModel,
    signature_index_path: Path,
) -> dict[str, object]:
    from evaluator.local_evaluator import evaluate

    agent = PropensityAgent(
        catalog_path,
        feature_table=feature_table,
        model=model,
        signature_index_path=signature_index_path,
    )
    try:
        return evaluate(agent, list(samples), catalog_ids, categories, products)
    finally:
        agent.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="catalog-only target-propensity experiment")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT)
    parser.add_argument("--asset", type=Path, default=DEFAULT_ASSET)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    kit = arguments.kit_root.resolve()
    catalog_path = kit / "data" / "catalog.jsonl"
    public_path = kit / "data" / "public_set.jsonl"
    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit))

    from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
    from needle.agent import Agent
    from needle.presets import PRIMARY_AGENT_KWARGS
    from scripts.run_unseen_proxy import build_matched_proxy_samples

    public = load_jsonl(public_path)
    catalog_ids, categories, products = catalog_index(catalog_path)
    feature_table = build_feature_table(products)
    buckets = build_buckets(products)
    public_targets = frozenset(
        str(sample["ground_truth"]["parent_asin"])
        for sample in public
    )

    baseline_agent = Agent(
        catalog_path,
        **{
            **PRIMARY_AGENT_KWARGS,
            "signature_index_path": arguments.asset.resolve(),
        },
    )
    try:
        baseline = evaluate(baseline_agent, public, catalog_ids, categories, products)
    finally:
        baseline_agent.close()

    folds = stratified_folds(public, count=arguments.folds)
    oof_sessions: list[dict] = []
    fold_records: list[dict[str, object]] = []
    all_indices = frozenset(range(len(public)))
    for fold_number, test_indices in enumerate(folds):
        test_set = frozenset(test_indices)
        train = [public[index] for index in sorted(all_indices - test_set)]
        test = [public[index] for index in test_indices]
        model = fit_pairwise_model(
            train,
            products=products,
            features=feature_table,
            buckets=buckets,
            positive_ids=public_targets,
        )
        result = _evaluate(
            test,
            catalog_path=catalog_path,
            catalog_ids=catalog_ids,
            categories=categories,
            products=products,
            feature_table=feature_table,
            model=model,
            signature_index_path=arguments.asset.resolve(),
        )
        oof_sessions.extend(result["sessions"])
        fold_records.append({
            "fold": fold_number,
            "sample_count": len(test),
            "weights": dict(zip(FEATURE_NAMES, model.weights)),
            "metrics": {
                key: result[key]
                for key in ("hit_rate_at_10", "mrr", "mttc", "recommended_technical_score")
            },
        })
    oof = _aggregate_sessions(oof_sessions)

    final_model = fit_pairwise_model(
        public,
        products=products,
        features=feature_table,
        buckets=buckets,
        positive_ids=public_targets,
    )
    proxy_records: list[dict[str, object]] = []
    for seed in ("20260830", "20260831", "20260901"):
        proxy, selection_sha, metadata = build_matched_proxy_samples(
            products,
            public,
            sample_count=200,
            seed=seed,
        )
        result = _evaluate(
            proxy,
            catalog_path=catalog_path,
            catalog_ids=catalog_ids,
            categories=categories,
            products=products,
            feature_table=feature_table,
            model=final_model,
            signature_index_path=arguments.asset.resolve(),
        )
        proxy_records.append({
            "seed": seed,
            "selection_sha256": selection_sha,
            "selection_metadata": metadata,
            "metrics": {
                key: result[key]
                for key in ("hit_rate_at_10", "mrr", "mttc", "recommended_technical_score")
            },
        })

    record = {
        "experiment_id": "EXP-024",
        "status": "evaluation_only",
        "feature_allowlist": list(FEATURE_NAMES),
        "identity_or_text_features": False,
        "baseline": {
            key: baseline[key]
            for key in ("hit_rate_at_10", "mrr", "mttc", "recommended_technical_score")
        },
        "public_out_of_fold": oof,
        "folds": fold_records,
        "full_model_weights": dict(zip(FEATURE_NAMES, final_model.weights)),
        "matched_disjoint": proxy_records,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "baseline": record["baseline"],
        "public_out_of_fold": record["public_out_of_fold"],
        "matched_disjoint": [
            {"seed": item["seed"], **item["metrics"]}
            for item in proxy_records
        ],
        "full_model_weights": record["full_model_weights"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
