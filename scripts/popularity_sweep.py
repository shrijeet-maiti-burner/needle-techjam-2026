"""Sweep `popularity_strength` across independently drawn control sets.

The first sweep in `docs/evidence/EXP_006_SHAPES.md` drew two 600-session
controls, at seeds 29 and 13, and they disagreed about whether 0.00 or 0.10 is
better: +0.000300 one way, -0.002148 the other. That spread was recorded as a
noise floor of roughly 0.003 for a 600-session draw, which left the decision
between 0.00 and 0.10 unresolved and the shipped value chosen conservatively
rather than measured.

Comparing whole-set aggregates across seeds is the weakest available test,
because it measures the variance of the absolute score under a fresh draw of
targets rather than the variance of the difference between two arms. The two
arms run over the same sessions, so the comparison is paired: every session
appears in both. This script keeps the per-session rows the official evaluator
already returns so the difference can be tested that way.

`recommended_technical_score` is an exact mean of a per-session quantity:

    score_i = 0.50 * hit_i + 0.30 * reciprocal_rank_i + 0.20 * (11 - ttc_i) / 10

where `ttc_i` is `first_hit_turn`, or 11 when the session never hits. Efficiency
is `(11 - mttc) / 10` clipped to [0, 1], and `mttc` is the mean of `ttc_i` over
sessions, which lies in [1, 11], so the clip never binds and the mean survives.
Averaging `score_i` therefore reproduces the reported score, which
`--self-check` verifies against the evaluator's own arithmetic on every run.

Datasets come from the committed builder, shelled out rather than reimplemented,
so what is swept is exactly what `build_shape_holdout.py` produces:

    python3 scripts/popularity_sweep.py --seeds 5 17 41 97 --count 600 \
        --strengths 0.00 0.10 0.20 \
        --output .artifacts/sweeps/popularity-seeds.json

Read the result with `scripts/analyze_sweep.py`. Both the datasets and the
output are development artifacts under `.artifacts/`. Neither is committed and
neither is shipped.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("TECHJAM_KIT_ROOT", ROOT / ".artifacts/participant-kit/techjam-conversational-search"))

# The official kit is a development artifact and is absent from CI, so it is
# imported inside the functions that sweep rather than at module scope. That
# keeps `session_score` importable by the tests and by `analyze_sweep.py`, which
# reads a finished payload and needs no evaluator.
MAX_TURNS_MISS = 11.0


def _official():
    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(KIT))
    from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl

    return catalog_index, evaluate, load_jsonl


def session_score(session: dict) -> float:
    """Per-session contribution to `recommended_technical_score`."""
    turns_to_hit = session["first_hit_turn"]
    ttc = MAX_TURNS_MISS if turns_to_hit is None else float(turns_to_hit)
    return (
        0.50 * float(session["hit"])
        + 0.30 * float(session["reciprocal_rank"])
        + 0.20 * (11.0 - ttc) / 10.0
    )


def build_control(seed: int, count: int, output: Path) -> Path:
    """Draw a same-shape different-target control through the committed builder."""
    if output.is_file():
        return output
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_shape_holdout.py"),
            "--control",
            "--seed",
            str(seed),
            "--count",
            str(count),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return output


def run_arm(dataset: Path, strength: float, catalog: Path, index: tuple) -> dict[str, Any]:
    _, evaluate, load_jsonl = _official()
    from needle.agent import Agent
    from needle.presets import PRIMARY_AGENT_KWARGS
    from starter.agent import default_index

    catalog_ids, categories, products = index
    kwargs = {**PRIMARY_AGENT_KWARGS, "popularity_strength": strength}
    agent = Agent(catalog, signature_index_path=default_index(), **kwargs)
    started = time.perf_counter()
    result = evaluate(agent, load_jsonl(dataset), catalog_ids, categories, products)
    elapsed = time.perf_counter() - started
    sessions = result.pop("sessions")
    return {
        "strength": strength,
        "summary": result,
        "sessions": sessions,
        "seconds": round(elapsed, 3),
    }


def self_check(run: dict[str, Any]) -> float:
    """Largest gap between the paired per-session mean and the reported score."""
    mean = sum(session_score(item) for item in run["sessions"]) / len(run["sessions"])
    return abs(mean - float(run["summary"]["recommended_technical_score"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[5, 17, 41, 97])
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument("--strengths", type=float, nargs="+", default=[0.00, 0.10, 0.20])
    parser.add_argument("--catalog", type=Path, default=KIT / "data/catalog.jsonl")
    parser.add_argument("--dataset-root", type=Path, default=ROOT / ".artifacts/holdout")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/sweeps/popularity-seeds.json")
    parser.add_argument(
        "--extra-dataset",
        type=Path,
        action="append",
        default=[],
        help="sweep an existing dataset as well, labelled by its file stem",
    )
    arguments = parser.parse_args()

    catalog_index, _, _ = _official()
    from needle.presets import PRIMARY_AGENT_KWARGS

    arguments.dataset_root.mkdir(parents=True, exist_ok=True)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)

    datasets: list[tuple[str, Path]] = []
    for seed in arguments.seeds:
        path = arguments.dataset_root / f"control_seed{seed}_n{arguments.count}.jsonl"
        datasets.append((f"control seed {seed}", build_control(seed, arguments.count, path)))
    for path in arguments.extra_dataset:
        datasets.append((path.stem, path))

    index = catalog_index(str(arguments.catalog))
    runs: list[dict[str, Any]] = []
    for label, dataset in datasets:
        for strength in arguments.strengths:
            run = run_arm(dataset, strength, arguments.catalog, index)
            run["dataset"] = label
            run["dataset_path"] = str(dataset)
            runs.append(run)
            print(
                f"{label:20s} popularity {strength:.2f}  "
                f"score {run['summary']['recommended_technical_score']:.6f}  "
                f"hr {run['summary']['hit_rate_at_10']:.4f}  "
                f"mrr {run['summary']['mrr']:.6f}  "
                f"({run['seconds']:.0f}s, self-check {self_check(run):.2e})",
                flush=True,
            )

    payload = {
        "count": arguments.count,
        "seeds": arguments.seeds,
        "strengths": arguments.strengths,
        "agent_kwargs": {key: value for key, value in PRIMARY_AGENT_KWARGS.items() if key != "popularity_strength"},
        "runs": runs,
    }
    arguments.output.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    print(f"wrote {len(runs)} runs to {arguments.output}")


if __name__ == "__main__":
    main()
