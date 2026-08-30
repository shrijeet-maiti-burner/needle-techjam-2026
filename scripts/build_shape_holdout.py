"""Build a held-out session set from catalog card shapes the public set omits.

All 200 public targets produce an `intent_card` with exactly four constraints.
Across the full 50,000-product catalog the shapes are:

    4 constraints, well-formed override   48122   96.24%   the only public shape
    3 constraints, well-formed override    1150    2.30%
    3 constraints, degenerate override      463    0.93%
    2 constraints, degenerate override      265    0.53%

Degenerate means `soft_preferences[-1] == hard_constraints[0]`, so the
preference the customer "retracts" at the override is the requirement they
replace it with. It follows from `soft_preferences = cleaned[2:4] or cleaned[:1]`
and therefore never occurs on a four-constraint card.

Drawing 200 targets uniformly and seeing zero non-four shapes has probability
about 0.0004, so the public targets were filtered to well-formed cards. The
private set has 800 disjoint targets and no published guarantee of that filter.

This writes a dataset in `public_set.jsonl` format whose targets are drawn only
from the omitted shapes and are disjoint from every public target, so the agent
can be run against session shapes it has never been measured on.

    python3 scripts/build_shape_holdout.py --output .artifacts/holdout/shapes.jsonl

The output is a development artifact. It is not shipped and not committed.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("TECHJAM_KIT_ROOT", ROOT / ".artifacts/participant-kit/techjam-conversational-search"))
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(KIT))

from evaluator.local_evaluator import intent_card  # noqa: E402

# Official public proportions: buying 40%, browsing 40%, intent_override 15%,
# boundary 5%. Held at the same mix so the only difference from public is card
# shape.
SCENARIO_MIX = (
    ("buying", 0.40),
    ("browsing", 0.40),
    ("intent_override", 0.15),
    ("boundary", 0.05),
)

# Reused verbatim from the public set so profiles are not a second variable.
PROFILES = (
    {
        "average_prior_rating": 5.0,
        "preference_tags": ["fit", "comfort", "durability"],
        "purchase_frequency": "3-4 prior purchases",
        "rating_style": "usually positive",
        "summary": "Prior purchases emphasize fit, comfort, durability; ratings are usually positive.",
    },
    {
        "average_prior_rating": 3.5,
        "preference_tags": ["value", "style"],
        "purchase_frequency": "1-2 prior purchases",
        "rating_style": "mixed",
        "summary": "Prior purchases emphasize value, style; ratings are mixed.",
    },
)


def card_shape(product: dict) -> tuple[int, bool]:
    """Constraint count and whether the override would be degenerate."""
    card = intent_card(product)
    hard = card["hard_constraints"]
    soft = card["soft_preferences"]
    degenerate = bool(soft and hard and soft[-1] == hard[0])
    return len(hard) + len(soft), degenerate


# The three shapes the public set never exercises, sampled in equal thirds so
# the common one does not swamp the other two.
OMITTED_SHAPES = ((3, False), (3, True), (2, True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=str(KIT / "data/catalog.jsonl"))
    parser.add_argument("--public", default=str(KIT / "data/public_set.jsonl"))
    parser.add_argument("--output", default=str(ROOT / ".artifacts/holdout/shapes.jsonl"))
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=13)
    arguments = parser.parse_args()

    public_targets = {
        str(json.loads(line)["ground_truth"]["parent_asin"])
        for line in Path(arguments.public).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    by_shape: dict[tuple[int, bool], list[str]] = {shape: [] for shape in OMITTED_SHAPES}
    with Path(arguments.catalog).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            product = json.loads(line)
            parent_asin = str(product.get("parent_asin", ""))
            if not parent_asin or parent_asin in public_targets:
                continue
            shape = card_shape(product)
            if shape in by_shape:
                by_shape[shape].append(parent_asin)

    rng = random.Random(arguments.seed)
    quota = arguments.count // len(OMITTED_SHAPES)
    chosen: list[str] = []
    used: dict[tuple[int, bool], int] = {}
    for index, shape in enumerate(OMITTED_SHAPES):
        pool = by_shape[shape]
        rng.shuffle(pool)
        # The last shape absorbs the remainder so the total is exact.
        want = quota if index < len(OMITTED_SHAPES) - 1 else arguments.count - len(chosen)
        if len(pool) < want:
            raise SystemExit(
                f"shape {shape} has {len(pool)} eligible targets, wanted {want}"
            )
        used[shape] = want
        chosen.extend(pool[:want])
    rng.shuffle(chosen)

    scenarios: list[str] = []
    for name, share in SCENARIO_MIX:
        scenarios.extend([name] * round(share * arguments.count))
    while len(scenarios) < arguments.count:
        scenarios.append("browsing")
    scenarios = scenarios[: arguments.count]

    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for index, (parent_asin, scenario) in enumerate(zip(chosen, scenarios), start=1):
            handle.write(
                json.dumps(
                    {
                        "category_bucket": "clothing",
                        "difficulty_bucket": "hard",
                        "ground_truth": {"parent_asin": parent_asin},
                        "sample_id": f"holdout_{index:04d}",
                        "scenario_type": scenario,
                        "user_profile": PROFILES[index % len(PROFILES)],
                    }
                )
                + "\n"
            )

    print(f"wrote {arguments.count} sessions to {output}")
    for shape in OMITTED_SHAPES:
        count, degenerate = shape
        label = "degenerate override" if degenerate else "well-formed override"
        print(
            f"  {count} constraints, {label:20s} "
            f"eligible {len(by_shape[shape]):5d}  used {used[shape]:3d}"
        )
    print("  target overlap with public: 0")


if __name__ == "__main__":
    main()
