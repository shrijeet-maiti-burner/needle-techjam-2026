"""Submission entry point with a catalog-bound bundled signature asset."""

from pathlib import Path

from needle.agent import Agent as CoreAgent
from needle.presets import PRIMARY_AGENT_KWARGS


SIGNATURE_INDEX = Path(__file__).with_name("assets") / "catalog-signatures.sqlite3"


class Agent(CoreAgent):
    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        super().__init__(
            catalog_path,
            signature_index_path=SIGNATURE_INDEX,
            **PRIMARY_AGENT_KWARGS,
        )


__all__ = ["Agent"]
