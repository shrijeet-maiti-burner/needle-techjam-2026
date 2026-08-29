from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT_ROOT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"


def main() -> None:
    kit_root = Path(os.environ.get("TECHJAM_KIT_ROOT", DEFAULT_KIT_ROOT)).resolve()
    evaluator = kit_root / "evaluator" / "local_evaluator.py"
    catalog = kit_root / "data" / "catalog.jsonl"
    dataset = kit_root / "data" / "public_set.jsonl"
    missing = [path for path in (evaluator, catalog, dataset) if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise SystemExit(f"official kit is incomplete ({formatted}); run python scripts/bootstrap.py")

    supplied = sys.argv[1:]
    if "--catalog" not in supplied:
        supplied.extend(["--catalog", str(catalog)])
    if "--dataset" not in supplied:
        supplied.extend(["--dataset", str(dataset)])
    for index, argument in enumerate(supplied):
        if argument == "--output" and index + 1 < len(supplied):
            Path(supplied[index + 1]).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        elif argument.startswith("--output="):
            Path(argument.partition("=")[2]).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit_root))
    sys.argv = [str(evaluator), *supplied]
    runpy.run_module("evaluator.local_evaluator", run_name="__main__")


if __name__ == "__main__":
    main()
