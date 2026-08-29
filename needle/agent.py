from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from needle.catalog import DEFAULT_FIELD_WEIGHTS, CatalogIndex
from needle.contracts import TurnResponse
from needle.semantic import NoOpSemanticReranker
from needle.state import StateStore


class Agent:
    """Strict official facade for the first end-to-end integration milestone."""

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        retrieval_mode: str = "sparse",
        query_mode: str = "any",
        field_weights: Sequence[float] = DEFAULT_FIELD_WEIGHTS,
        popularity_strength: float = 0.0,
        signature_bucket_limit: int = 100,
        signature_index_path: str | Path | None = None,
        candidate_pool: int = 200,
        slate_size: int = 10,
        exclude_seen: bool = False,
        override_policy: str = "full_reset",
    ) -> None:
        if not 1 <= int(candidate_pool) <= 500:
            raise ValueError("candidate_pool must be in 1..500")
        if not 1 <= int(slate_size) <= 10:
            raise ValueError("slate_size must be in 1..10")
        self.catalog = CatalogIndex(
            catalog_path,
            retrieval_mode=retrieval_mode,
            query_mode=query_mode,
            field_weights=field_weights,
            popularity_strength=popularity_strength,
            signature_bucket_limit=signature_bucket_limit,
            signature_index_path=signature_index_path,
        )
        self.state = StateStore(override_policy=override_policy)
        self.semantic = NoOpSemanticReranker()
        self.candidate_pool = int(candidate_pool)
        self.slate_size = int(slate_size)
        self.exclude_seen = bool(exclude_seen)
        self._seen_by_version: dict[tuple[str, int], set[str]] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.state.reset(session_id, user_profile)
        stale_keys = [key for key in self._seen_by_version if key[0] == session_id]
        for key in stale_keys:
            del self._seen_by_version[key]

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        state = self.state.observe(session_id, user_message, turn)
        limit = max(0, min(int(top_k), self.slate_size, 10))
        history_key = (session_id, state.intent_version)
        seen = self._seen_by_version.setdefault(history_key, set())
        excluded = seen if self.exclude_seen else ()
        sparse = self.catalog.search(
            state.retrieval_text,
            self.candidate_pool,
            messages=state.messages,
            excluded_ids=excluded,
        )
        ranked = self.semantic.rerank(sparse, state.retrieval_text)[:limit]
        seen.update(candidate.parent_asin for candidate in ranked)
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
