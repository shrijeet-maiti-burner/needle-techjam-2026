from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path

from needle.catalog import (
    DEFAULT_FIELD_WEIGHTS,
    CatalogIndex,
    disclosed_signature_sequences,
    opening_category_signature,
)
from needle.contracts import TurnResponse
from needle.explain import message_for, turn_record
from needle.questions import clarifying_options
from needle.semantic import LexicalNormalizer, NoOpSemanticReranker
from needle.state import Polarity, StateStore


LEXICAL_MODES = frozenset({"none", "normalize", "expand"})

# How many of the popularity-ordered candidates a clarifying question counts
# over. Counting a facet across tens of thousands of products would cost more
# than the question is worth; beyond this the values are still real but the
# counts are of the sample, and are not shown.
_FACET_SAMPLE = 400


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
        correction_scope: str = "all",
        identify_from_disclosures: bool = False,
        adaptive_slate: bool = False,
        early_slate_size: int = 1,
        full_slate_turn: int = 5,
        full_slate_constraints: int = 4,
        explain: bool = False,
        promote_disclosure_bucket: bool = False,
        promotion_bucket_limit: int = 50_000,
        promote_opening_category: bool = False,
        trace_enabled: bool = False,
    ) -> None:
        if not 1 <= int(candidate_pool) <= 500:
            raise ValueError("candidate_pool must be in 1..500")
        if not 1 <= int(slate_size) <= 10:
            raise ValueError("slate_size must be in 1..10")
        if lexical_mode not in LEXICAL_MODES:
            raise ValueError(f"unsupported lexical mode: {lexical_mode}")
        if not 1 <= int(early_slate_size) <= 10:
            raise ValueError("early_slate_size must be in 1..10")
        if not 1 <= int(full_slate_turn) <= 10:
            raise ValueError("full_slate_turn must be in 1..10")
        if not 1 <= int(full_slate_constraints) <= 20:
            raise ValueError("full_slate_constraints must be in 1..20")
        if not 1 <= int(promotion_bucket_limit) <= 50_000:
            raise ValueError("promotion_bucket_limit must be in 1..50000")
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
            correction_scope=correction_scope,
        )
        self.state = StateStore(override_policy=override_policy)
        self.semantic = NoOpSemanticReranker()
        self.lexical = LexicalNormalizer()
        self.lexical_mode = lexical_mode
        self.candidate_pool = int(candidate_pool)
        self.slate_size = int(slate_size)
        self.exclude_seen = bool(exclude_seen)
        self.identify_from_disclosures = bool(identify_from_disclosures)
        self.adaptive_slate = bool(adaptive_slate)
        self.early_slate_size = int(early_slate_size)
        self.full_slate_turn = int(full_slate_turn)
        self.full_slate_constraints = int(full_slate_constraints)
        self.explain = bool(explain)
        self.promote_disclosure_bucket = bool(promote_disclosure_bucket)
        self.promotion_bucket_limit = int(promotion_bucket_limit)
        self.promote_opening_category = bool(promote_opening_category)
        self.trace_enabled = bool(trace_enabled)
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
            "correction_scope": correction_scope,
            "identify_from_disclosures": self.identify_from_disclosures,
            "adaptive_slate": self.adaptive_slate,
            "early_slate_size": self.early_slate_size,
            "full_slate_turn": self.full_slate_turn,
            "full_slate_constraints": self.full_slate_constraints,
            "explain": self.explain,
            "promote_disclosure_bucket": self.promote_disclosure_bucket,
            "promotion_bucket_limit": self.promotion_bucket_limit,
            "promote_opening_category": self.promote_opening_category,
            "trace_enabled": self.trace_enabled,
        }
        self._seen_by_version: dict[tuple[str, int], set[str]] = {}
        self._opening_category_by_session: dict[str, str] = {}
        self._trace_by_session: dict[str, list[dict[str, object]]] = {}
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
        self._opening_category_by_session.pop(session_id, None)
        self._trace_by_session.pop(session_id, None)

    def trace_for(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return an isolated copy of optional faithful runtime traces."""

        return tuple(copy.deepcopy(self._trace_by_session.get(session_id, ())))

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

    def _options_for(
        self, candidate_ids: Sequence[str], already_said: Sequence[str]
    ) -> tuple[str, tuple[tuple[str, int], ...]]:
        """The facet worth asking about next, from the products still in play."""
        if not candidate_ids:
            return "", ()
        return clarifying_options(
            candidate_ids,
            self.catalog.clarification_facets(candidate_ids),
            already_said=already_said,
        )

    def _explain_turn(
        self,
        session_id: str,
        *,
        turn: int,
        category: str,
        state: object,
        candidates: int | None,
        candidate_ids: Sequence[str] = (),
        sampled: bool = False,
        identified: bool,
        emitted: Sequence[str],
        withheld: bool,
        asking: bool,
    ) -> str:
        """Record what this turn did and say it. Never raises.

        The message is not scored, so this can only ever cost a turn by throwing,
        and `evaluate` substitutes an empty response when `respond` raises. It is
        wrapped accordingly, and a failure degrades to the constant the agent
        used before rather than to no answer.
        """
        try:
            # The values the *bucket* keyed on, not just the belief state's
            # active constraints: after an override the two diverge, and naming
            # the smaller set makes a correct count look inconsistent with the
            # previous turn's. The longest sequence is the maximal disclosure
            # under the most likely parse.
            wanted: list[str] = []
            sequences = disclosed_signature_sequences(state.messages)
            for value in max(sequences, key=len, default=()):
                if value not in wanted:
                    wanted.append(value)
            unwanted: list[str] = []
            for constraint in state.active_constraints():
                if constraint.polarity is Polarity.NEGATIVE:
                    if constraint.value not in unwanted:
                        unwanted.append(constraint.value)
                elif not wanted and constraint.value not in wanted:
                    wanted.append(constraint.value)
            record = turn_record(
                turn=turn,
                category=category,
                wanted=wanted,
                unwanted=unwanted,
                candidates=candidates,
                identified=identified,
                emitted=emitted,
                withheld=withheld,
                sampled=sampled,
            )
            if asking:
                record["options"] = self._options_for(candidate_ids, record["wanted"])
            return message_for(record, asking=asking)
        except Exception as error:  # noqa: BLE001 - a dull message beats a lost turn
            self.respond_failures.append(
                f"session={session_id} turn={turn!r}: explain: "
                f"{type(error).__name__}: {error}"
            )
            return (
                "What else matters most for the item you want?"
                if asking
                else "These are the closest catalog matches for your current request."
            )

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
        if turn == 1:
            self._opening_category_by_session[session_id] = opening_category_signature(
                user_message
            )
        history_key = (session_id, state.intent_version)
        seen = self._seen_by_version.setdefault(history_key, set())
        seen_before = frozenset(seen)
        excluded = seen if self.exclude_seen else ()
        retrieval_text = state.retrieval_text
        category_evidence = self._opening_category_by_session.get(session_id, "")
        if category_evidence:
            retrieval_text = f"{retrieval_text} {category_evidence}"
        if self.lexical_mode == "normalize":
            retrieval_text = self.lexical.normalize(retrieval_text)
        elif self.lexical_mode == "expand":
            retrieval_text = self.lexical.expand_query(retrieval_text)
        promoted = (
            self.catalog.rank_disclosure_bucket(
                state.messages,
                category=category_evidence,
                allow_ordered=state.intent_version == 1,
                include_empty=self.promote_opening_category and turn == 1,
                limit=self.promotion_bucket_limit,
            )
            if self.promote_disclosure_bucket and limit
            else ()
        )
        identified = (
            self.catalog.identify_from_disclosures(
                state.messages,
                category=self._opening_category_by_session.get(session_id, ""),
                allow_ordered=state.intent_version == 1,
            )
            if self.identify_from_disclosures and limit
            else None
        )
        if identified is not None:
            recommendation_ids = [identified]
            output_limit = min(limit, 1)
            sparse = []
            decision_path = "unique_identification"
        else:
            output_limit = limit
            if (
                self.adaptive_slate
                and turn < self.full_slate_turn
                and len(state.active_constraints()) < self.full_slate_constraints
            ):
                output_limit = min(output_limit, self.early_slate_size)
            recommendation_ids = [
                parent_asin
                for parent_asin in promoted
                if parent_asin not in excluded
            ][:output_limit]
            sparse = []
            if len(recommendation_ids) < output_limit:
                sparse = self.catalog.search(
                    retrieval_text,
                    self.candidate_pool,
                    messages=state.messages,
                    excluded_ids=excluded,
                )
                ranked = self.semantic.rerank(sparse, retrieval_text)
                promoted_set = set(recommendation_ids)
                recommendation_ids.extend(
                    candidate.parent_asin
                    for candidate in ranked
                    if candidate.parent_asin not in promoted_set
                )
                recommendation_ids = recommendation_ids[:output_limit]
            decision_path = (
                "evidence_bucket_promotion"
                if recommendation_ids and promoted and recommendation_ids[0] in promoted
                else "sparse_fallback"
            )
        # Only serialized products were shown. Withheld products must remain
        # eligible on the next turn or an adaptive slate can blacklist its own
        # eventual rank-one answer.
        seen.update(recommendation_ids)
        ask_attribute = "other" if self._safe_turn(turn) < 10 else None
        message = (
            "What else matters most for the item you want?"
            if ask_attribute
            else "These are the closest catalog matches for your current request."
        )
        if self.explain:
            message = self._explain_turn(
                session_id,
                turn=turn,
                category=category_evidence,
                state=state,
                candidates=len(promoted) if promoted else None,
                # Bounded: the bucket is popularity-ordered, and counting a
                # facet over every one of tens of thousands of products would
                # cost more than the question is worth.
                candidate_ids=tuple(promoted[:_FACET_SAMPLE]),
                sampled=len(promoted) > _FACET_SAMPLE if promoted else False,
                identified=identified is not None,
                emitted=recommendation_ids,
                withheld=len(recommendation_ids) < limit,
                asking=ask_attribute is not None,
            )
        response: TurnResponse = {
            "message": message,
            "ask_attribute": ask_attribute,
            "recommendations": [
                {"parent_asin": parent_asin}
                for parent_asin in recommendation_ids
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
        if self.trace_enabled:
            try:
                from needle.lens import build_turn_trace

                trace = build_turn_trace(
                    catalog=self.catalog,
                    state=state,
                    turn=turn,
                    retrieval_text=retrieval_text,
                    category=category_evidence,
                    promoted=promoted,
                    identified=identified,
                    sparse=sparse,
                    recommendations=recommendation_ids,
                    output_limit=output_limit,
                    seen_before=seen_before,
                    decision_path=decision_path,
                    response=response,
                    promotion_limit=self.promotion_bucket_limit,
                    include_empty=self.promote_opening_category and turn == 1,
                )
            except Exception as error:  # noqa: BLE001 - tracing is non-operative
                trace = {
                    "trace_version": "needle-lens-v1",
                    "target_blind": True,
                    "turn": int(turn),
                    "trace_error": f"{type(error).__name__}: {error}",
                    "response": copy.deepcopy(response),
                }
            self._trace_by_session.setdefault(session_id, []).append(trace)
        return response
