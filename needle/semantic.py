from __future__ import annotations

from collections.abc import Sequence

from needle.contracts import Candidate


class NoOpSemanticReranker:
    """Offline-safe integration boundary used until a semantic experiment passes its gate."""

    def rerank(self, candidates: Sequence[Candidate], query: str) -> list[Candidate]:
        del query
        return list(candidates)
