"""Development adapter kept at the official evaluator import path."""

import os
from pathlib import Path

from needle.agent import Agent as CoreAgent
from needle.presets import PRIMARY_AGENT_KWARGS


_ROOT = Path(__file__).resolve().parents[1]

# The evaluator imports `starter.agent.Agent`, so this is the path that actually
# runs. Prefer the asset that ships inside the bundle; fall back to the local
# development build, which is under `.artifacts/` and therefore gitignored and
# absent from any bundle. Neither is required: `CatalogIndex` rebuilds the
# signatures in memory when the index is missing or does not match the catalog.
BUNDLED_INDEX = _ROOT / "submission" / "assets" / "catalog-signatures.sqlite3"
DEVELOPMENT_INDEX = _ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"
DEFAULT_INDEX = BUNDLED_INDEX if BUNDLED_INDEX.is_file() else DEVELOPMENT_INDEX


def default_index() -> Path | None:
    """First index that exists, or None to rebuild from the catalog."""
    override = os.environ.get("NEEDLE_SIGNATURE_INDEX")
    if override:
        return Path(override)
    for candidate in (BUNDLED_INDEX, DEVELOPMENT_INDEX):
        if candidate.is_file():
            return candidate
    return None


class Agent(CoreAgent):
    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        super().__init__(
            catalog_path,
            signature_index_path=default_index(),
            **PRIMARY_AGENT_KWARGS,
        )


__all__ = ["Agent"]
