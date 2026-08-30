from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from needle.catalog import DEFAULT_FIELD_WEIGHTS, CatalogIndex
from needle.contracts import TurnResponse
from needle.promotion import PrefixIndex
from needle.semantic import LexicalNormalizer, NoOpSemanticReranker
from needle.state import StateStore


LEXICAL_MODES = frozenset({"none", "normalize", "expand"})
EMISSION_MODES = frozenset({"slate", "promote"})


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
        category_strength: float = 0.0,
        signature_bucket_limit: int = 100,
        signature_index_path: str | Path | None = None,
        candidate_pool: int = 200,
        slate_size: int = 10,
        exclude_seen: bool = False,
        override_policy: str = "full_reset",
        lexical_mode: str = "none",
        correct_unmatched_terms: bool = False,
        emission_mode: str = "slate",
        release_turn: int = 8,
    ) -> None:
        if emission_mode not in EMISSION_MODES:
            raise ValueError(f"unsupported emission mode: {emission_mode}")
        if not 2 <= int(release_turn) <= 10:
            raise ValueError("release_turn must be in 2..10")
        if not 1 <= int(candidate_pool) <= 500:
            raise ValueError("candidate_pool must be in 1..500")
        if not 1 <= int(slate_size) <= 10:
            raise ValueError("slate_size must be in 1..10")
        if lexical_mode not in LEXICAL_MODES:
            raise ValueError(f"unsupported lexical mode: {lexical_mode}")
        self.catalog = CatalogIndex(
            catalog_path,
            retrieval_mode=retrieval_mode,
            query_mode=query_mode,
            field_weights=field_weights,
            popularity_strength=popularity_strength,
            category_strength=category_strength,
            signature_bucket_limit=signature_bucket_limit,
            signature_index_path=signature_index_path,
            correct_unmatched_terms=correct_unmatched_terms,
        )
        self.emission_mode = emission_mode
        self.release_turn = int(release_turn)
        self.prefix_index = (
            PrefixIndex(catalog_path) if emission_mode == "promote" else None
        )
        self.state = StateStore(override_policy=override_policy)
        self.semantic = NoOpSemanticReranker()
        self.lexical = LexicalNormalizer()
        self.lexical_mode = lexical_mode
        self.candidate_pool = int(candidate_pool)
        self.slate_size = int(slate_size)
        self.exclude_seen = bool(exclude_seen)
        self.experiment_configuration: dict[str, object] = {
            "retrieval_mode": retrieval_mode,
            "query_mode": query_mode,
            "field_weights": list(field_weights),
            "popularity_strength": float(popularity_strength),
            "category_strength": float(category_strength),
            "signature_bucket_limit": int(signature_bucket_limit),
            "signature_index_path": (
                str(self.catalog.signature_index_path)
                if self.catalog.signature_index_path is not None
                else None
            ),
            "candidate_pool": self.candidate_pool,
            "slate_size": self.slate_size,
            "exclude_seen": self.exclude_seen,
            "override_policy": override_policy,
            "lexical_mode": lexical_mode,
            "correct_unmatched_terms": bool(correct_unmatched_terms),
            "emission_mode": emission_mode,
            "release_turn": self.release_turn,
        }
        self._seen_by_version: dict[tuple[str, int], set[str]] = {}
        # What was actually *shown* to the customer, which is not the same as
        # what retrieval returned. See `_emit`.
        self._emitted: dict[tuple[str, int], set[str]] = {}
        self._opening_category: dict[str, str] = {}
        # Degradations are recorded rather than raised; an empty list is the
        # assertion that every turn took the normal path.
        self.respond_failures: list[str] = []

    def close(self) -> None:
        """Release catalog resources. Idempotent; the official harness never
        calls it, but experiment runners and tests construct many agents."""
        self.catalog.close()

    def __enter__(self) -> "Agent":
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.state.reset(session_id, user_profile)
        stale_keys = [key for key in self._seen_by_version if key[0] == session_id]
        for key in stale_keys:
            del self._seen_by_version[key]
        for key in [key for key in self._emitted if key[0] == session_id]:
            del self._emitted[key]
        self._opening_category.pop(session_id, None)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        """Answer one turn. Never raises.

        `local_evaluator.evaluate` wraps this in `except Exception` and
        substitutes an empty response, so an escaping exception costs more than
        the turn: `ask_attribute` becomes None, the simulated customer replies
        "Ask me about one specific attribute", and no constraint is disclosed
        for the rest of the session. On turn one that forfeits the session.

        The strict turn/lifecycle invariants stay in `StateStore`, where they
        catch real ordering bugs. Here they are downgraded to a degraded answer:
        retrieval is retried against the raw message alone, and only a total
        failure yields an empty slate. `respond_failures` records what happened
        so a silent degradation is still visible to the experiment record.
        """
        try:
            return self._respond(session_id, user_message, turn, top_k)
        except Exception as error:  # noqa: BLE001 - a valid turn beats any raise
            self.respond_failures.append(
                f"session={session_id} turn={turn!r}: {type(error).__name__}: {error}"
            )
            return self._degraded_response(user_message, turn, top_k)

    def _degraded_response(self, user_message: object, turn: object, top_k: object) -> TurnResponse:
        """Best-effort contract-valid turn used when the normal path fails."""
        recommendations: list[dict[str, str]] = []
        try:
            limit = self._bounded_limit(top_k)
            if limit and isinstance(user_message, str):
                candidates = self.catalog.search(user_message, limit)
                recommendations = [
                    {"parent_asin": candidate.parent_asin} for candidate in candidates[:limit]
                ]
        except Exception:  # noqa: BLE001 - the empty slate below is still valid
            recommendations = []
        ask_attribute = "other" if self._safe_turn(turn) < 10 else None
        return {
            "message": (
                "Could you tell me one more thing about what you are looking for?"
                if ask_attribute
                else "These are the closest catalog matches I have."
            ),
            "ask_attribute": ask_attribute,
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    def _emit(
        self,
        session_id: str,
        state: object,
        turn: int,
        limit: int,
        ranked: list[str],
        user_message: str,
    ) -> list[str]:
        """Which of the ranked products to actually show this turn.

        `local_evaluator.evaluate` breaks out of a session the first turn the
        target appears and freezes `reciprocal_rank` at that rank forever, so a
        rank the agent would have improved two turns later is never re-read.
        A turn of MTTC is worth 0.02; moving a hit from rank two to rank one is
        worth 0.15. Showing one product instead of ten while the belief state is
        thin therefore defers the lock, and the disclosed-prefix bucket is what
        makes each deferred turn a good guess rather than a stall.

        Ordering is never touched: this only chooses how many of the agent's own
        ranked products to serialize, and which bucket member to lead with.
        """
        assert self.prefix_index is not None
        index = self.prefix_index
        if turn == 1:
            # An override bumps `intent_version`; the category has to be
            # captured from the opening line while it is still the only message.
            self._opening_category[session_id] = index.opening_category(user_message)
        category = self._opening_category.get(session_id, "")
        messages = list(getattr(state, "messages", ()) or ())
        shortlist = index.shortlist(messages, category)

        if turn == 1 and not shortlist:
            # A browsing or boundary session discloses nothing on turn one, so
            # the deepest bucket available is the bare category. The gate emits
            # exactly one product either way, so this swaps one guess for
            # another: it cannot spend a turn that was not going to be spent and
            # it cannot cost a hit. Promoting the empty prefix on *later* turns
            # was measured and rejected (EXP_023.md): the category-sized bucket
            # is not a shortlist worth walking.
            opening = index.shortlist([], category, empty_prefix=True)
            if opening:
                return [opening[0]]

        if shortlist:
            shown = self._emitted.get((session_id, state.intent_version), set())
            if turn >= self.release_turn:
                # The release floor guarantees the hit, so the shortlist is
                # merged *ahead of* the ranked slate rather than replacing it,
                # and merged bounded: a corrupted transcript can key another
                # product's bucket, and an unbounded merge would fill every slot
                # with it and lose a target the ranking had. Half the slate is
                # reserved for the ranking's own answer.
                head = shortlist[: max(1, limit // 2)]
                merged = head + [asin for asin in ranked if asin not in set(head)]
                return merged[:limit]
            pick = next((asin for asin in shortlist if asin not in shown), None)
            if pick is not None:
                return [pick]
            # Walked out: every member has been shown and passed over.
            # Re-emitting the head spends the turn on a known-dead answer, and
            # would do so again every turn until the floor.

        confident = (
            turn >= self.release_turn
            or len(state.active_constraints()) >= 4
            # Promotion has declined: the disclosed evidence resolves to no
            # bucket. The whole case for holding is that the next turn sharpens
            # a ranking promotion can act on, so with nothing to wait for the
            # hold is pure MTTC, and on a corrupted transcript it starves the
            # session while turns remain to use.
            or (turn > 1 and not shortlist)
        )
        return ranked if confident else ranked[: max(1, min(limit, 1))]

    @staticmethod
    def _safe_turn(turn: object) -> int:
        """Turn number for messaging only; unusable values keep the question on."""
        try:
            return int(turn)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1

    def _bounded_limit(self, top_k: object) -> int:
        try:
            requested = int(top_k)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            # The contract says ten; a harness passing something unusable
            # should still get a full, valid slate rather than nothing.
            requested = 10
        return max(0, min(requested, self.slate_size, 10))

    def _respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        state = self.state.observe(session_id, user_message, turn)
        limit = self._bounded_limit(top_k)
        history_key = (session_id, state.intent_version)
        seen = self._seen_by_version.setdefault(history_key, set())
        excluded = seen if self.exclude_seen else ()
        retrieval_text = state.retrieval_text
        if self.lexical_mode == "normalize":
            retrieval_text = self.lexical.normalize(retrieval_text)
        elif self.lexical_mode == "expand":
            retrieval_text = self.lexical.expand_query(retrieval_text)
        sparse = self.catalog.search(
            retrieval_text,
            self.candidate_pool,
            messages=state.messages,
            excluded_ids=excluded,
        )
        ranked = self.semantic.rerank(sparse, retrieval_text)[:limit]
        recommendations = [candidate.parent_asin for candidate in ranked]
        if self.emission_mode == "promote":
            recommendations = self._emit(
                session_id, state, turn, limit, recommendations, user_message
            )
            # Only what the customer was actually shown may be excluded from
            # later retrieval. Marking everything *retrieved* as seen would let
            # the gate blacklist a target it deliberately withheld.
            shown = self._emitted.setdefault(history_key, set())
            shown.update(recommendations)
            self._seen_by_version[history_key] = set(shown)
        else:
            seen.update(recommendations)
        ask_attribute = "other" if self._safe_turn(turn) < 10 else None
        message = (
            "What else matters most for the item you want?"
            if ask_attribute
            else "These are the closest catalog matches for your current request."
        )
        return {
            "message": message,
            "ask_attribute": ask_attribute,
            "recommendations": [
                {"parent_asin": parent_asin} for parent_asin in recommendations
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
