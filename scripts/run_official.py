"""Run the extracted submission with the unmodified official evaluator."""
from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path


BUNDLE_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kit-root",
        type=Path,
        required=True,
        help="extracted TechJam participant-kit root",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results.json"),
        help="official evaluator output path (default: results.json)",
    )
    arguments = parser.parse_args()

    kit = arguments.kit_root.expanduser().resolve()
    evaluator = kit / "evaluator" / "local_evaluator.py"
    catalog = kit / "data" / "catalog.jsonl"
    dataset = kit / "data" / "public_set.jsonl"
    required = (evaluator, catalog, dataset)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("participant kit is incomplete; missing: " + ", ".join(missing))

    output = arguments.output.expanduser()
    if not output.is_absolute():
        output = (Path.cwd() / output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # The organizer kit also contains starter/agent.py. Running from its root
    # can therefore evaluate the weak starter by accident. Put this extracted
    # bundle first, then execute the organizer's evaluator file byte-for-byte.
    # The evaluator receives its ordinary CLI arguments and writes its ordinary
    # results.json; no organizer file is copied or modified.
    sys.path.insert(0, str(BUNDLE_ROOT))
    sys.argv = [
        str(evaluator),
        "--catalog",
        str(catalog),
        "--dataset",
        str(dataset),
        "--output",
        str(output),
    ]
    runpy.run_path(str(evaluator), run_name="__main__")


if __name__ == "__main__":
    main()
