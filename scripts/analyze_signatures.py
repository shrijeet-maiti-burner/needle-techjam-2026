from __future__ import annotations

import argparse
from collections import defaultdict
import importlib
import json
import math
import statistics
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT_ROOT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="measure catalog-signature collisions and target retention")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT_ROOT)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def distribution(values: list[int] | tuple[int, ...]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "minimum": None, "median": None, "p90": None, "p99": None, "maximum": None}
    ordered = sorted(values)

    def percentile(fraction: float) -> int:
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "median": statistics.median(ordered),
        "p90": percentile(0.90),
        "p99": percentile(0.99),
        "maximum": ordered[-1],
    }


def main() -> None:
    args = parse_arguments()
    kit_root = args.kit_root.expanduser().resolve()
    catalog_path = kit_root / "data" / "catalog.jsonl"
    public_set_path = kit_root / "data" / "public_set.jsonl"
    missing = [str(path) for path in (catalog_path, public_set_path) if not path.is_file()]
    if missing:
        raise SystemExit(f"official kit is incomplete: {', '.join(missing)}")

    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit_root))
    official = importlib.import_module("evaluator.local_evaluator")
    from needle.catalog import CatalogIndex, product_signatures

    samples = official.load_jsonl(public_set_path)
    _, _, products = official.catalog_index(catalog_path)
    index = CatalogIndex(catalog_path, retrieval_mode="signature_first")
    signature_counts: defaultdict[str, int] = defaultdict(int)
    for product in products.values():
        for signature in product_signatures(product):
            signature_counts[signature] += 1
    by_depth: dict[int, list[dict[str, object]]] = {depth: [] for depth in range(1, 5)}
    failures: list[dict[str, object]] = []

    for sample in samples:
        target = str(sample["ground_truth"]["parent_asin"])
        card = official.intent_card(products[target])
        constraints = [
            *[str(value) for value in card.get("hard_constraints", [])],
            *[str(value) for value in card.get("soft_preferences", [])],
        ]
        for depth in range(1, min(4, len(constraints)) + 1):
            messages = [
                f"For that, what matters is: {constraint}."
                for constraint in constraints[:depth]
            ]
            matched, candidates = index.signature_candidates(messages)
            if target not in candidates:
                failures.append(
                    {
                        "sample_id": sample["sample_id"],
                        "depth": depth,
                        "target": target,
                        "constraints": constraints[:depth],
                        "matched_signatures": matched,
                        "bucket_size": len(candidates),
                    }
                )
            by_depth[depth].append(
                {
                    "activated": bool(matched and candidates),
                    "target_retained": target in candidates,
                    "bucket_size": len(candidates),
                }
            )

    depth_summary: dict[str, object] = {}
    for depth, records in by_depth.items():
        activated = [record for record in records if record["activated"]]
        depth_summary[str(depth)] = {
            "sample_count": len(records),
            "activated_count": len(activated),
            "activation_rate": round(len(activated) / len(records), 6) if records else 0.0,
            "target_retained_count": sum(bool(record["target_retained"]) for record in records),
            "target_retention_rate": round(
                sum(bool(record["target_retained"]) for record in records) / len(records),
                6,
            ) if records else 0.0,
            "activated_bucket_sizes": distribution(
                [int(record["bucket_size"]) for record in activated]
            ),
        }

    all_buckets = tuple(signature_counts.values())
    result = {
        "catalog_product_count": index.product_count,
        "catalog_signature_buckets": {
            **distribution(all_buckets),
            "unique_bucket_count": sum(size == 1 for size in all_buckets),
            "unique_bucket_rate": round(sum(size == 1 for size in all_buckets) / len(all_buckets), 6),
        },
        "public_target_prefixes": depth_summary,
        "target_retention_failures": failures,
        "interpretation": (
            "Target retention measures catalog-derived signatures on released target cards with "
            "one constraint represented per diagnostic message. It is a collision/retention upper "
            "bound, not a protocol score or private-score estimate."
        ),
    }
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
