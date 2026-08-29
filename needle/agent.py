from __future__ import annotations

from pathlib import Path

from needle.catalog import CatalogIndex
from needle.contracts import TurnResponse
from needle.semantic import NoOpSemanticReranker
from needle.state import StateStore


class Agent:
    """Strict official facade for the first end-to-end integration milestone."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog = CatalogIndex(catalog_path)
        self.state = StateStore()
        self.semantic = NoOpSemanticReranker()

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.state.reset(session_id, user_profile)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        state = self.state.observe(session_id, user_message, turn)
        limit = max(0, min(int(top_k), 10))
        sparse = self.catalog.search(state.retrieval_text, limit)
        ranked = self.semantic.rerank(sparse, state.retrieval_text)[:limit]
        ask_attribute = "other" if turn < 10 else None
        message = (
            "What else matters most for the item you want?"
            if ask_attribute
            else "These are the closest catalog matches for your current request."
        )
        return {
            "message": message,
            "ask_attribute": ask_attribute,
            "recommendations": [
                {"parent_asin": candidate.parent_asin}
                for candidate in ranked
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
