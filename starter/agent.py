"""Development adapter kept at the official evaluator import path."""

import os
from pathlib import Path

from needle.agent import Agent as CoreAgent
from needle.presets import PRIMARY_AGENT_KWARGS


DEFAULT_INDEX = (
    Path(__file__).resolve().parents[1]
    / ".artifacts"
    / "indexes"
    / "catalog-signatures.sqlite3"
)


class Agent(CoreAgent):
    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        index_path = Path(os.environ.get("NEEDLE_SIGNATURE_INDEX", DEFAULT_INDEX))
        super().__init__(
            catalog_path,
            signature_index_path=index_path,
            **PRIMARY_AGENT_KWARGS,
        )


__all__ = ["Agent"]
