"""Evaluate on deterministic catalog targets disjoint from the public set.

This is a transfer diagnostic, not a private-score estimator. It reuses the
released simulator and public scenario/profile distributions while selecting
targets solely from catalog rows that never appear as released ground truth.
No selected identifier is written to the report.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import importlib
import json
import math
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT_ROOT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
UNIFORM_SELECTION_VERSION = "catalog-disjoint-v1"
MATCHED_SELECTION_VERSION = "catalog-matched-v1"
GENERIC_CATEGORIES = frozenset(
    {
        "clothing",
        "clothing shoes jewelry",
        "clothing shoes and jewelry",
        "women",
        "men",
        "girls",
        "boys",
    }
)


def _stable_order(
    values: Iterable[str],
    seed: str,
    selection_version: str = UNIFORM_SELECTION_VERSION,
) -> list[str]:
    return sorted(
        values,
        key=lambda value: hashlib.sha256(
            f"{selection_version}\0{seed}\0{value}".encode()
        ).digest(),
    )


def build_proxy_samples(
    catalog_ids: Iterable[str],
    public_samples: Sequence[Mapping[str, Any]],
    *,
    sample_count: int,
    seed: str,
) -> tuple[list[dict[str, object]], str]:
    """Build target-disjoint samples with released marginal distributions."""

    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    if not public_samples:
        raise ValueError("public_samples must not be empty")

    public_targets = {
        str(sample.get("ground_truth", {}).get("parent_asin", ""))
        for sample in public_samples
    }
    eligible = _stable_order(
        (str(parent_asin) for parent_asin in catalog_ids if str(parent_asin) not in public_targets),
        seed,
    )
    if sample_count > len(eligible):
        raise ValueError(f"sample_count exceeds {len(eligible)} disjoint catalog targets")

    scenario_cycle = [str(sample["scenario_type"]) for sample in public_samples]
    profile_cycle = [dict(sample["user_profile"]) for sample in public_samples]
    profile_offset = int.from_bytes(hashlib.sha256(f"profile\0{seed}".encode()).digest()[:4], "big")

    samples: list[dict[str, object]] = []
    selected = eligible[:sample_count]
    for index, parent_asin in enumerate(selected):
        samples.append(
            {
                "sample_id": f"proxy_{index + 1:05d}",
                "scenario_type": scenario_cycle[index % len(scenario_cycle)],
                "user_profile": profile_cycle[(index + profile_offset) % len(profile_cycle)],
                "ground_truth": {"parent_asin": parent_asin},
            }
        )
    selection_sha256 = hashlib.sha256("\n".join(selected).encode()).hexdigest()
    return samples, selection_sha256


def _rating_number(product: Mapping[str, Any]) -> int:
    try:
        return max(0, int(product.get("rating_number") or 0))
    except (TypeError, ValueError):
        return 0


def _has_price(product: Mapping[str, Any]) -> bool:
    return product.get("price") not in (None, "")


def _category_key(product: Mapping[str, Any]) -> str:
    values = product.get("categories") or []
    if not isinstance(values, list):
        values = [values]
    normalized: list[str] = []
    for value in values:
        words = " ".join(
            part.lower()
            for part in "".join(
                character if character.isalnum() else " " for character in str(value)
            ).split()
        )
        if words and words not in GENERIC_CATEGORIES:
            normalized.append(words)
    # Catalog category paths run broad-to-specific. The first non-generic
    # value is stable enough to match product families without creating tiny,
    # leaf-level pools that immediately exhaust.
    return normalized[0] if normalized else "other"


def _quantile_boundaries(values: Sequence[int], bins: int = 10) -> tuple[int, ...]:
    if not values:
        raise ValueError("cannot derive rating strata without public targets")
    ordered = sorted(values)
    return tuple(
        ordered[min(len(ordered) - 1, math.ceil(len(ordered) * index / bins) - 1)]
        for index in range(1, bins)
    )


def _distribution(products: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    ratings = [_rating_number(product) for product in products]
    if not ratings:
        return {
            "sample_count": 0,
            "rating_median": 0,
            "rating_p25": 0,
            "rating_p75": 0,
            "priced_fraction": 0.0,
        }
    quartiles = statistics.quantiles(ratings, n=4) if len(ratings) >= 2 else [ratings[0]] * 3
    return {
        "sample_count": len(products),
        "rating_median": statistics.median(ratings),
        "rating_p25": quartiles[0],
        "rating_p75": quartiles[2],
        "priced_fraction": round(sum(_has_price(product) for product in products) / len(products), 6),
    }


def build_matched_proxy_samples(
    products: Mapping[str, Mapping[str, Any]],
    public_samples: Sequence[Mapping[str, Any]],
    *,
    sample_count: int,
    seed: str,
) -> tuple[list[dict[str, object]], str, dict[str, object]]:
    """Build disjoint targets matched on observable catalog-level strata.

    Matching uses only product metadata available to every participant. Public
    target identifiers define the excluded set and the empirical strata, but
    are never emitted. Selection is without replacement and falls back from
    category/rating/price to broader catalog-derived pools when a stratum is
    exhausted.
    """

    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    if not public_samples:
        raise ValueError("public_samples must not be empty")
    if sample_count > len(public_samples):
        raise ValueError(
            "matched sample_count cannot exceed the public panel size; use "
            "multiple seeds or uniform mode for a larger tail diagnostic"
        )

    public_targets = [
        str(sample.get("ground_truth", {}).get("parent_asin", ""))
        for sample in public_samples
    ]
    missing = [parent_asin for parent_asin in public_targets if parent_asin not in products]
    if missing:
        raise ValueError("a public target is missing from the catalog")
    excluded = frozenset(public_targets)
    eligible_ids = [parent_asin for parent_asin in products if parent_asin not in excluded]
    if sample_count > len(eligible_ids):
        raise ValueError(f"sample_count exceeds {len(eligible_ids)} disjoint catalog targets")

    public_products = [products[parent_asin] for parent_asin in public_targets]
    boundaries = _quantile_boundaries([_rating_number(product) for product in public_products])

    def features(parent_asin: str) -> tuple[str, int, bool]:
        product = products[parent_asin]
        return (
            _category_key(product),
            bisect.bisect_right(boundaries, _rating_number(product)),
            _has_price(product),
        )

    pools: dict[tuple[object, ...], list[str]] = defaultdict(list)
    for parent_asin in eligible_ids:
        category, rating_bin, priced = features(parent_asin)
        keys = (
            ("exact", category, rating_bin, priced),
            ("category-rating", category, rating_bin),
            ("rating-price", rating_bin, priced),
            ("rating", rating_bin),
            ("category", category),
            ("all",),
        )
        for key in keys:
            pools[key].append(parent_asin)
    for key, values in pools.items():
        pools[key] = _stable_order(
            values,
            f"{seed}\0{'|'.join(map(str, key))}",
            MATCHED_SELECTION_VERSION,
        )

    cursors: Counter[tuple[object, ...]] = Counter()
    used: set[str] = set()

    def take(key: tuple[object, ...]) -> str | None:
        values = pools.get(key, [])
        cursor = cursors[key]
        while cursor < len(values) and values[cursor] in used:
            cursor += 1
        cursors[key] = cursor + 1
        return values[cursor] if cursor < len(values) else None

    scenario_cycle = [str(sample["scenario_type"]) for sample in public_samples]
    profile_cycle = [dict(sample["user_profile"]) for sample in public_samples]
    profile_offset = int.from_bytes(hashlib.sha256(f"profile\0{seed}".encode()).digest()[:4], "big")
    fallback_counts: Counter[str] = Counter()
    category_matches = 0
    selected: list[str] = []
    samples: list[dict[str, object]] = []
    for index in range(sample_count):
        reference_id = public_targets[index % len(public_targets)]
        category, rating_bin, priced = features(reference_id)
        choices = (
            ("exact", category, rating_bin, priced),
            ("category-rating", category, rating_bin),
            ("rating-price", rating_bin, priced),
            ("rating", rating_bin),
            ("category", category),
            ("all",),
        )
        selected_id: str | None = None
        selected_level = ""
        for key in choices:
            selected_id = take(key)
            if selected_id is not None:
                selected_level = str(key[0])
                break
        if selected_id is None:
            raise RuntimeError("matched proxy exhausted every fallback pool")
        used.add(selected_id)
        selected.append(selected_id)
        fallback_counts[selected_level] += 1
        category_matches += int(_category_key(products[selected_id]) == category)
        samples.append(
            {
                "sample_id": f"proxy_{index + 1:05d}",
                "scenario_type": scenario_cycle[index % len(scenario_cycle)],
                "user_profile": profile_cycle[(index + profile_offset) % len(profile_cycle)],
                "ground_truth": {"parent_asin": selected_id},
            }
        )

    selection_sha256 = hashlib.sha256("\n".join(selected).encode()).hexdigest()
    metadata: dict[str, object] = {
        "rating_quantile_boundaries": list(boundaries),
        "fallback_counts": dict(fallback_counts),
        "category_match_fraction": round(category_matches / sample_count, 6),
        "reference_distribution": _distribution(public_products),
        "selected_distribution": _distribution([products[parent_asin] for parent_asin in selected]),
    }
    return samples, selection_sha256, metadata


def _load_symbol(specifier: str) -> type:
    module_name, separator, symbol_name = specifier.partition(":")
    if not separator or not module_name or not symbol_name:
        raise ValueError("agent must use module:Class syntax")
    symbol: Any = importlib.import_module(module_name)
    for part in symbol_name.split("."):
        symbol = getattr(symbol, part)
    if not isinstance(symbol, type):
        raise TypeError(f"agent symbol is not a class: {specifier}")
    return symbol


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="catalog-disjoint transfer diagnostic")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--agent", default="starter.agent:Agent")
    parser.add_argument("--agent-kwargs", default="{}")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT_ROOT)
    parser.add_argument("--output-root", type=Path, default=ROOT / "results" / "unseen-proxy")
    parser.add_argument("--sample-count", type=int, default=1000)
    parser.add_argument("--seed", default="0")
    parser.add_argument("--selection-mode", choices=("uniform", "matched"), default="uniform")
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_arguments()
    if not args.experiment_id or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for character in args.experiment_id
    ):
        raise SystemExit("experiment id must contain only uppercase letters, digits, and hyphens")
    try:
        agent_kwargs = json.loads(args.agent_kwargs)
    except json.JSONDecodeError as error:
        raise SystemExit(f"agent kwargs is not valid JSON: {error}") from error
    if not isinstance(agent_kwargs, dict):
        raise SystemExit("agent kwargs must decode to an object")

    dirty = [line for line in _git("status", "--porcelain=v1", "--untracked-files=all").splitlines() if line]
    if dirty and not args.allow_dirty:
        raise SystemExit("working tree is dirty; commit or pass --allow-dirty for a diagnostic run")

    kit_root = args.kit_root.expanduser().resolve()
    evaluator_path = kit_root / "evaluator" / "local_evaluator.py"
    catalog_path = kit_root / "data" / "catalog.jsonl"
    public_path = kit_root / "data" / "public_set.jsonl"
    missing = [str(path) for path in (evaluator_path, catalog_path, public_path) if not path.is_file()]
    if missing:
        raise SystemExit(f"official kit is incomplete: {', '.join(missing)}")

    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit_root))
    official = importlib.import_module("evaluator.local_evaluator")
    from needle.evaluation import ContractCheckingAgent

    public_samples = official.load_jsonl(public_path)
    catalog_ids, categories, products = official.catalog_index(catalog_path)
    selection_metadata: dict[str, object] = {}
    if args.selection_mode == "matched":
        samples, selection_sha256, selection_metadata = build_matched_proxy_samples(
            products,
            public_samples,
            sample_count=args.sample_count,
            seed=args.seed,
        )
    else:
        samples, selection_sha256 = build_proxy_samples(
            catalog_ids,
            public_samples,
            sample_count=args.sample_count,
            seed=args.seed,
        )
    agent = _load_symbol(args.agent)(catalog_path=catalog_path, **agent_kwargs)
    checked_agent = ContractCheckingAgent(agent, catalog_ids)
    result = official.evaluate(checked_agent, samples, catalog_ids, categories, products)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    commit = _git("rev-parse", "HEAD")
    output_dir = args.output_root.resolve() / args.experiment_id / f"{timestamp}-{commit[:8]}"
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = {key: value for key, value in result.items() if key != "sessions"}
    record = {
        "schema_version": 1,
        "recorded_at_utc": timestamp,
        "git": {"commit": commit, "branch": _git("branch", "--show-current"), "dirty": bool(dirty)},
        "agent": {"specifier": args.agent, "kwargs": agent_kwargs},
        "proxy": {
            "selection_version": (
                MATCHED_SELECTION_VERSION
                if args.selection_mode == "matched"
                else UNIFORM_SELECTION_VERSION
            ),
            "selection_mode": args.selection_mode,
            "seed": args.seed,
            "sample_count": len(samples),
            "selection_sha256": selection_sha256,
            "public_target_count_excluded": len(public_samples),
            "scenario_counts": dict(Counter(str(sample["scenario_type"]) for sample in samples)),
            "claim_limit": "transfer diagnostic only; not a private-score estimate",
            **selection_metadata,
        },
        "official_artifacts": {
            "evaluator_sha256": _sha256(evaluator_path),
            "catalog_sha256": _sha256(catalog_path),
            "public_set_sha256": _sha256(public_path),
        },
        "summary": summary,
        "contract": checked_agent.report.as_dict(),
    }
    (output_dir / "record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_directory": str(output_dir), **summary, "contract": record["contract"]}, indent=2))
    if not record["contract"]["passed"]:
        raise SystemExit("strict contract validation failed; inspect record.json")


if __name__ == "__main__":
    main()
