"""Run the EXP-010 robustness slice comparison against the public set.

Not a leaderboard run: it reports how the agent degrades under controlled
meaning-preserving and meaning-changing perturbation, using the official
simulator's own message generation. Needs the bootstrapped participant kit.

    python scripts/bootstrap.py
    python scripts/run_robustness.py --agent starter.agent:Agent
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT_ROOT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
OFFICIAL_SOURCE_COMMIT = "34078351e1c3615e5505a2e829600b56a542e462"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _load_symbol(specifier: str) -> type:
    module_name, separator, symbol_name = specifier.partition(":")
    if not separator or not module_name or not symbol_name:
        raise ValueError("agent must use module:Class syntax")
    symbol = importlib.import_module(module_name)
    for part in symbol_name.split("."):
        symbol = getattr(symbol, part)
    if not isinstance(symbol, type):
        raise TypeError(f"agent symbol is not a class: {specifier}")
    return symbol


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EXP-010 robustness slice comparison")
    parser.add_argument("--agent", default="starter.agent:Agent")
    parser.add_argument("--agent-kwargs", default="{}", help="JSON object for the agent constructor")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT_ROOT)
    parser.add_argument("--output-root", type=Path, default=ROOT / "results" / "robustness")
    parser.add_argument("--seed", default="0")
    parser.add_argument(
        "--slices",
        default="",
        help="comma-separated slice names; default runs the full catalogue",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_arguments()

    dirty = [line for line in _git("status", "--porcelain=v1", "--untracked-files=all").splitlines() if line]
    if dirty and not args.allow_dirty:
        raise SystemExit("working tree is dirty; commit or pass --allow-dirty for a diagnostic run")

    try:
        agent_kwargs = json.loads(args.agent_kwargs)
    except json.JSONDecodeError as error:
        raise SystemExit(f"agent kwargs is not valid JSON: {error}") from error
    if not isinstance(agent_kwargs, dict):
        raise SystemExit("agent kwargs must decode to an object")

    kit_root = args.kit_root.expanduser().resolve()
    evaluator_path = kit_root / "evaluator" / "local_evaluator.py"
    catalog_path = kit_root / "data" / "catalog.jsonl"
    dataset_path = kit_root / "data" / "public_set.jsonl"
    missing = [str(path) for path in (evaluator_path, catalog_path, dataset_path) if not path.is_file()]
    if missing:
        raise SystemExit(f"official kit is incomplete: {', '.join(missing)}; run scripts/bootstrap.py")

    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit_root))

    from evaluator import local_evaluator as official

    from robustness.report import compare, gate_failures, summarize
    from robustness.session import official_simulator, run_slice
    from robustness.slices import BY_NAME, DEFAULT_SLICES

    if args.slices:
        requested = [name.strip() for name in args.slices.split(",") if name.strip()]
        unknown = [name for name in requested if name not in BY_NAME]
        if unknown:
            raise SystemExit(f"unknown slices: {', '.join(unknown)}")
        specs = [BY_NAME["exact_surface"]] + [BY_NAME[name] for name in requested if name != "exact_surface"]
    else:
        specs = list(DEFAULT_SLICES)

    samples = official.load_jsonl(dataset_path)
    catalog_ids, categories, products = official.catalog_index(catalog_path)
    simulator = official_simulator()
    agent = _load_symbol(args.agent)(catalog_path=catalog_path, **agent_kwargs)

    all_outcomes = []
    baseline_outcomes = []
    for spec in specs:
        outcomes = run_slice(
            agent,
            samples,
            spec,
            catalog_ids=catalog_ids,
            categories=categories,
            products=products,
            simulator=simulator,
            seed=args.seed,
        )
        all_outcomes.extend(outcomes)
        if spec.name == "exact_surface":
            baseline_outcomes = outcomes

    perturbed = [outcome for outcome in all_outcomes if outcome.slice != "exact_surface"]
    comparison = compare(baseline_outcomes, perturbed)
    failures = gate_failures(comparison)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    commit = _git("rev-parse", "HEAD")
    output_dir = args.output_root.resolve() / f"{timestamp}-{commit[:8]}"
    output_dir.mkdir(parents=True, exist_ok=False)

    record = {
        "schema_version": 1,
        "recorded_at_utc": timestamp,
        "command": subprocess.list2cmdline([sys.executable, *sys.argv]),
        "git": {"commit": commit, "branch": _git("branch", "--show-current"), "dirty": bool(dirty)},
        "agent": {"specifier": args.agent, "kwargs": agent_kwargs},
        "seed": args.seed,
        "official_artifacts": {
            "upstream_commit": OFFICIAL_SOURCE_COMMIT,
            "evaluator_sha256": _sha256(evaluator_path),
            "catalog_sha256": _sha256(catalog_path),
            "public_set_sha256": _sha256(dataset_path),
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "slices_run": [spec.name for spec in specs],
        "summary": summarize(all_outcomes),
        "comparison": comparison,
        "gate_failures": failures,
    }
    (output_dir / "report.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps({"output_directory": str(output_dir), "gate_failures": failures}, indent=2))
    if failures:
        raise SystemExit("robustness gates failed; inspect report.json")


if __name__ == "__main__":
    main()
