"""Build a held-out session set whose targets look like real targets.

The existing holdouts draw targets close to uniformly from the catalog, and
that is the wrong instrument for judging a popularity prior. Measured on the
released data:

    set              n      median rating_number   has price
    public 200       200                    6846       0.890
    shape holdout    200                       3       0.075
    control seed13   600                      12       0.188
    whole catalog  50000                      12       0.211

Public targets are roughly 500x more reviewed than a uniform draw and carry a
price four times as often. That is not a quirk of the public split: targets are
real purchase records, and purchased products are popular and well described, so
the private targets are drawn from the same kind of population. Judging a
popularity prior against uniformly sampled targets therefore measures a harder
task than the one being scored, and will reject the prior whether or not it
transfers.

This samples targets to match the public targets' `rating_number` decile
distribution, keeping the scenario mix and the eligibility properties every
public target has (features and details present), and excluding every public
target so the sets stay disjoint.

    python3 scripts/build_matched_holdout.py --count 600 --seed 13 \
        --output .artifacts/holdout/matched_seed13_n600.jsonl

The output is a development artifact. It is not shipped and not committed.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("TECHJAM_KIT_ROOT", ROOT / ".artifacts/participant-kit/techjam-conversational-search"))
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(KIT))

from evaluator.local_evaluator import catalog_index, load_jsonl  # noqa: E402

# The released mix, from the competition specification.
SCENARIO_MIX = (("buying", 0.40), ("browsing", 0.40), ("intent_override", 0.15), ("boundary", 0.05))
TAGS = ("fit", "comfort", "durability", "style", "material", "weather", "warmth", "performance")
FREQUENCY = ("1-2 prior purchases", "3-4 prior purchases", "5+ prior purchases")


def _rating(product: dict) -> float:
    value = product.get("rating_number")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _eligible(product: dict) -> bool:
    # Every public target has both; treat it as the eligibility filter.
    return product.get("features") not in (None, "", [], {}) and product.get("details") not in (None, "", [], {})


def _profile(rng: random.Random) -> dict:
    tags = rng.sample(TAGS, k=rng.choice((2, 3)))
    rating = rng.choice((1.0, 2.5, 3.0, 3.5, 4.0, 5.0))
    style = "usually positive" if rating >= 4 else ("critical" if rating <= 2 else "mixed")
    return {
        "average_prior_rating": rating,
        "preference_tags": tags,
        "purchase_frequency": rng.choice(FREQUENCY),
        "rating_style": style,
        "summary": f"Prior purchases emphasize {', '.join(tags)}; ratings are {style}.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="popularity-matched held-out sessions")
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    catalog_path = KIT / "data" / "catalog.jsonl"
    public_path = KIT / "data" / "public_set.jsonl"
    _, _, products = catalog_index(str(catalog_path))
    public = load_jsonl(str(public_path))
    public_targets = {str(sample["ground_truth"]["parent_asin"]) for sample in public}

    # The distribution to match, as decile edges of the public targets.
    reference = sorted(_rating(products[target]) for target in public_targets if target in products)
    edges = [reference[int(len(reference) * fraction / 10)] for fraction in range(1, 10)]

    pool: dict[int, list[str]] = {index: [] for index in range(10)}
    for parent_asin, product in products.items():
        if parent_asin in public_targets or not _eligible(product):
            continue
        pool[bisect.bisect_right(edges, _rating(product))].append(parent_asin)
    for bucket in pool.values():
        bucket.sort()

    rng = random.Random(arguments.seed)
    scenarios: list[str] = []
    for name, share in SCENARIO_MIX:
        scenarios.extend([name] * round(arguments.count * share))
    while len(scenarios) < arguments.count:
        scenarios.append("buying")
    scenarios = scenarios[: arguments.count]
    rng.shuffle(scenarios)

    chosen: list[str] = []
    used: set[str] = set()
    # One target per decile in round robin, so the sample reproduces the
    # reference distribution rather than merely its median.
    for index in range(arguments.count):
        bucket = pool[index % 10]
        if not bucket:
            bucket = next(b for b in pool.values() if b)
        candidate = bucket[rng.randrange(len(bucket))]
        guard = 0
        while candidate in used and guard < 50:
            candidate = bucket[rng.randrange(len(bucket))]
            guard += 1
        used.add(candidate)
        chosen.append(candidate)

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8") as handle:
        for index, (target, scenario) in enumerate(zip(chosen, scenarios), start=1):
            handle.write(json.dumps({
                "sample_id": f"matched_{index:04d}",
                "scenario_type": scenario,
                "category_bucket": "clothing",
                "difficulty_bucket": "matched",
                "ground_truth": {"parent_asin": target},
                "user_profile": _profile(rng),
            }) + "\n")

    drawn = [_rating(products[target]) for target in chosen]
    priced = sum(1 for target in chosen if products[target].get("price") not in (None, "")) / len(chosen)
    print(f"wrote {arguments.output}  n={len(chosen)}")
    print(f"  median rating_number  reference {statistics.median(reference):.0f}  drawn {statistics.median(drawn):.0f}")
    print(f"  has price             reference "
          f"{sum(1 for t in public_targets if t in products and products[t].get('price') not in (None, '')) / len(public_targets):.3f}"
          f"  drawn {priced:.3f}")
    print(f"  disjoint from public: {not (set(chosen) & public_targets)}")


if __name__ == "__main__":
    main()
