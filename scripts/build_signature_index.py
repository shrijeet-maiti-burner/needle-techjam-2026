from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search" / "data" / "catalog.jsonl"
DEFAULT_OUTPUT = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="build a catalog-bound exact-signature index")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    sys.path.insert(0, str(ROOT))
    from needle.catalog import build_signature_index

    result = build_signature_index(args.catalog, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
