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
from needle.language import DEFAULT as DEFAULT_LANGUAGE
from needle.language import category_mention as lexicon_category
from needle.language import detect as detect_language
from needle.language import supported as supported_languages
from needle.questions import QuestionDecision, choose_clarification
from needle.semantic import LexicalNormalizer, NoOpSemanticReranker
from needle.state import Polarity, SessionState, StateStore


LEXICAL_MODES = frozenset({"none", "normalize", "expand"})

# How many of the popularity-ordered candidates a clarifying question counts
# over. Counting a facet across tens of thousands of products would cost more
# than the question is worth; beyond this the values are still real but the
# counts are of the sample, and are not shown.
_FACET_SAMPLE = 200
_EXCLUSION_SAMPLE = 500


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
        self._language_by_session: dict[str, str] = {}
        self._pinned_language: dict[str, str] = {}
        self._lexicon_words_by_session: dict[str, str] = {}
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
        self._language_by_session.pop(session_id, None)
        self._pinned_language.pop(session_id, None)
        self._lexicon_words_by_session.pop(session_id, None)
        self._trace_by_session.pop(session_id, None)

    def set_language(self, session_id: str, language: str | None) -> None:
        """Pin the reply language for a session, or clear the pin with None.

        For a caller that already knows better than the detector: a storefront
        with an account locale, or a test. An unsupported code is ignored rather
        than raising, and detection then stands; falling back to English would
        discard what the customer actually wrote because their storefront sent
        a locale we cannot speak.
        """
        if language is None:
            self._pinned_language.pop(session_id, None)
            return
        code = str(language).strip().lower()
        if code in supported_languages():
            self._pinned_language[session_id] = code

    def _session_language(self, session_id: str, message: str) -> str:
        """The language this session is conducted in.

        Decided once, from the opening message, and then held. Detection is
        per-message and a later reply can be too short to carry evidence: "Si,
        cuero." reads as English on its own, and a customer who opened in
        Spanish should not be answered in English on turn two because their
        second message was three words long.
        """
        pinned = self._pinned_language.get(session_id)
        if pinned is not None:
            return pinned
        known = self._language_by_session.get(session_id)
        if known is not None:
            return known
        detected = detect_language(message)
        self._language_by_session[session_id] = detected
        return detected

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

    def _question_for(
        self,
        candidate_ids: Sequence[str],
        already_said: Sequence[str],
        *,
        turns_left: int,
        sampled: bool,
        excluded_values: Sequence[str],
    ) -> QuestionDecision:
        """The cost-adjusted facet worth asking about next, if there is one."""
        return choose_clarification(
            candidate_ids,
            self.catalog.clarification_facets(candidate_ids),
            already_said=already_said,
            turns_left=turns_left,
            sampled=sampled,
            excluded_values=excluded_values,
        )

    def _respect_exclusions(
        self,
        parent_asins: Sequence[str],
        state: SessionState,
    ) -> tuple[str, ...]:
        """Stably prefer candidates that do not contradict explicit exclusions.

        This is deliberately a soft partition, not a hard filter. Catalog text
        can be incomplete and language can be misparsed; conflicting products
        remain available after the compatible products instead of disappearing.
        Only a bounded prefix is inspected, so a negative preference cannot
        turn one response into a full-catalog scan.
        """
        exclusions: dict[str, set[str]] = {}
        for constraint in state.active_constraints():
            if constraint.polarity is Polarity.NEGATIVE:
                exclusions.setdefault(constraint.attribute, set()).add(constraint.value)
        ordered = tuple(parent_asins)
        if not exclusions or len(ordered) < 2:
            return ordered
        sample = ordered[:_EXCLUSION_SAMPLE]
        facets = self.catalog.clarification_facets(sample)

        def conflicts(parent_asin: str) -> int:
            product = facets.get(parent_asin, {})
            return sum(
                product.get(attribute) in values
                for attribute, values in exclusions.items()
            )

        compatible_first = tuple(sorted(sample, key=conflicts))
        return (*compatible_first, *ordered[len(sample):])

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
        language: str = DEFAULT_LANGUAGE,
    ) -> tuple[str, QuestionDecision]:
        """Record what this turn did and say it. Never raises.

        The message is not scored, so this can only ever cost a turn by throwing,
        and `evaluate` substitutes an empty response when `respond` raises. It is
        wrapped accordingly, and a failure degrades to the constant the agent
        used before rather than to no answer.
        """
        try:
            # Say back the structured beliefs first. A signature sequence is a
            # retrieval key, not necessarily a sentence fragment a person
            # would recognise: free text such as "something nice for a wedding"
            # can otherwise be repeated verbatim inside an awkward generated
            # clause. The candidate count is still described independently of
            # these values, so this does not turn a union bucket into a false
            # "N products match X" claim.
            wanted: list[str] = []
            unwanted: list[str] = []
            for constraint in state.active_constraints():
                destination = (
                    unwanted
                    if constraint.polarity is Polarity.NEGATIVE
                    else wanted
                )
                if constraint.value not in destination:
                    destination.append(constraint.value)

            # The released simulator sometimes supplies exact catalog
            # disclosures that are not members of the compact belief-state
            # vocabulary. Preserve those as a truthful fallback when the
            # structured parser found no positive value at all.
            sequences = disclosed_signature_sequences(state.retrieval_messages)
            if not wanted:
                for value in max(sequences, key=len, default=()):
                    if value not in wanted:
                        wanted.append(value)
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
                language=language,
            )
            question = QuestionDecision(
                candidate_count=len(candidate_ids),
                sampled=sampled,
                reason="the response does not ask another question",
            )
            if asking:
                already_said = [
                    *record["wanted"],
                    *(
                        constraint.attribute
                        for constraint in state.active_constraints()
                        if constraint.polarity is Polarity.POSITIVE
                    ),
                ]
                excluded_values = [
                    constraint.value
                    for constraint in state.active_constraints()
                    if constraint.polarity is Polarity.NEGATIVE
                ]
                question = self._question_for(
                    candidate_ids,
                    already_said,
                    turns_left=max(0, 10 - self._safe_turn(turn)),
                    sampled=sampled,
                    excluded_values=excluded_values,
                )
                record["options"] = (question.attribute, question.options)
            return message_for(record, asking=asking), question
        except Exception as error:  # noqa: BLE001 - a dull message beats a lost turn
            self.respond_failures.append(
                f"session={session_id} turn={turn!r}: explain: "
                f"{type(error).__name__}: {error}"
            )
            return (
                (
                    "What else matters most for the item you want?"
                    if asking
                    else "These are the closest catalog matches for your current request."
                ),
                QuestionDecision(
                    candidate_count=len(candidate_ids),
                    sampled=sampled,
                    reason=f"question policy unavailable: {type(error).__name__}",
                ),
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
            stated = opening_category_signature(user_message)
            if not stated:
                # `opening_category_signature` keys on English request grammar
                # ("I'm looking for X"). A request written in another language
                # is not unparseable, only differently ordered, so fall back to
                # the shopping lexicon, which keys on the noun instead.
                #
                # English never reaches this branch: a request either states a
                # category in that grammar or genuinely has none, and the
                # released simulator always states one. Measured across all 200
                # public sessions, every emitted message is byte-identical with
                # this branch present.
                words, _ = lexicon_category(user_message)
                if words:
                    self._lexicon_words_by_session[session_id] = words
                    stated = words
            # `resolve_category` is the catalog's own resolver and it declines
            # rather than guessing, so a lexicon noun naming several categories,
            # or none, leaves the bucket unqualified instead of wrong. That is
            # why the lexicon does not need a resolver of its own.
            self._opening_category_by_session[session_id] = self.catalog.resolve_category(stated)
        history_key = (session_id, state.intent_version)
        seen = self._seen_by_version.setdefault(history_key, set())
        seen_before = frozenset(seen)
        excluded = seen if self.exclude_seen else ()
        retrieval_text = state.retrieval_text
        category_evidence = self._opening_category_by_session.get(session_id, "")
        lexicon_words = self._lexicon_words_by_session.get(session_id, "")
        if category_evidence:
            retrieval_text = f"{retrieval_text} {category_evidence}"
        elif lexicon_words:
            # Unresolved, so useless as a bucket key, but still the only
            # statement of what the customer is shopping for. Retrieval can use
            # the words even where the closed vocabulary could not.
            retrieval_text = f"{retrieval_text} {lexicon_words}"
        if self.lexical_mode == "normalize":
            retrieval_text = self.lexical.normalize(retrieval_text)
        elif self.lexical_mode == "expand":
            retrieval_text = self.lexical.expand_query(retrieval_text)
        disclosure_order_stable = self.catalog.ordered_disclosures_stable(
            state.retrieval_messages
        )
        ordered_disclosures_safe = (
            state.intent_version == 1 and disclosure_order_stable
        )
        promoted = (
            self.catalog.rank_disclosure_bucket(
                state.retrieval_messages,
                category=category_evidence,
                allow_ordered=ordered_disclosures_safe,
                include_empty=self.promote_opening_category and turn == 1,
                limit=self.promotion_bucket_limit,
            )
            if self.promote_disclosure_bucket and limit
            else ()
        )
        promoted = self._respect_exclusions(promoted, state)
        identified = (
            self.catalog.identify_from_disclosures(
                state.retrieval_messages,
                category=self._opening_category_by_session.get(session_id, ""),
                allow_ordered=ordered_disclosures_safe,
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
                    messages=state.retrieval_messages,
                    excluded_ids=excluded,
                )
                ranked = self.semantic.rerank(sparse, retrieval_text)
                ranked_by_id = {
                    candidate.parent_asin: candidate for candidate in ranked
                }
                ranked = [
                    ranked_by_id[parent_asin]
                    for parent_asin in self._respect_exclusions(
                        tuple(ranked_by_id), state
                    )
                ]
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
        question_decision: QuestionDecision | None = None
        if self.explain:
            question_candidates = (
                tuple(promoted[:_FACET_SAMPLE])
                if promoted
                else tuple(candidate.parent_asin for candidate in sparse[:_FACET_SAMPLE])
            )
            question_sampled = (
                len(promoted) > _FACET_SAMPLE
                if promoted
                else len(sparse) > _FACET_SAMPLE
            )
            message, question_decision = self._explain_turn(
                session_id,
                language=self._session_language(session_id, user_message),
                turn=turn,
                category=category_evidence,
                state=state,
                candidates=len(promoted) if promoted else None,
                # Bounded: the bucket is popularity-ordered, and counting a
                # facet over every one of tens of thousands of products would
                # cost more than the question is worth.
                candidate_ids=question_candidates,
                sampled=question_sampled,
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
                    ordered_disclosures_safe=ordered_disclosures_safe,
                    question_decision=(
                        question_decision.as_dict()
                        if question_decision is not None
                        else None
                    ),
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
