"""Build the catalog-bound exact-signature asset.

`build_signature_index` refuses to overwrite, which is right for a library: an
index is 65MB and silently clobbering one is not a decision a function should
make on its own. It is wrong for the release path, though, because the
schema is versioned and the asset is not tracked.

When `SIGNATURE_INDEX_SCHEMA_VERSION` moves, every asset built before the bump
is stale, `CatalogIndex` rejects it and rebuilds in process, and the bundler
refuses to ship it and prints "rebuild it with scripts/build_signature_index.py".
Running that command then failed with "signature index already exists", so the
remediation the release path prints did not work and left the stale asset in
place. This CLI closes that loop: it inspects what is already there and replaces
it only when it is stale, which is the case the message is talking about.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search" / "data" / "catalog.jsonl"
DEFAULT_OUTPUT = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="build a catalog-bound exact-signature index")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even when the existing index already matches",
    )
    return parser.parse_args()


def _existing_metadata(path: Path) -> dict[str, str] | None:
    """Metadata of an index already at `path`, or None if there is nothing
    readable there. An unreadable file counts as stale rather than as an
    error: it cannot be what the agent needs, so it should be replaced."""
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        return dict(connection.execute("SELECT key, value FROM metadata"))
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def main() -> None:
    args = parse_arguments()
    sys.path.insert(0, str(ROOT))
    from needle.catalog import (
        SIGNATURE_INDEX_SCHEMA_VERSION,
        _facet_rules_fingerprint,
        build_signature_index,
        sha256_file,
    )

    catalog = args.catalog.resolve()
    output = args.output.resolve()
    if not catalog.is_file():
        raise SystemExit(f"catalog not found: {catalog}; run scripts/bootstrap.py")

    existing = _existing_metadata(output)
    if existing is not None:
        current = (
            existing.get("schema_version") == SIGNATURE_INDEX_SCHEMA_VERSION
            and existing.get("catalog_sha256") == sha256_file(catalog)
            and existing.get("facet_parser_sha256") == _facet_rules_fingerprint()
        )
        if current and not args.force:
            print(json.dumps({
                "path": str(output),
                "rebuilt": False,
                "reason": "already current",
                "schema_version": SIGNATURE_INDEX_SCHEMA_VERSION,
            }, indent=2, sort_keys=True))
            return
        reason = "forced" if current else (
            f"stale: schema {existing.get('schema_version')!r} against "
            f"{SIGNATURE_INDEX_SCHEMA_VERSION!r}, catalog "
            f"{'bound' if existing.get('catalog_sha256') == sha256_file(catalog) else 'unbound'}, "
            f"parser {'current' if existing.get('facet_parser_sha256') == _facet_rules_fingerprint() else 'stale'}"
        )
        print(f"replacing existing index ({reason})", file=sys.stderr)
        output.unlink()

    result = build_signature_index(catalog, output)
    print(json.dumps({**result, "rebuilt": True}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
