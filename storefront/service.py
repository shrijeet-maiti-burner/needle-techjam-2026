"""Live conversation sessions against the selected primary agent.

This is the interactive counterpart to `scripts/needle_lens.py`. The lens
replays released public samples through the official simulator to certify what
the agent decided; this drives the same agent from free text a person types, so
the team can test behaviour the 200 released sessions never produce.

Three rules hold it to the same standard as the rest of the repo:

*One policy.* The agent is constructed from `PRIMARY_AGENT_KWARGS`. There is no
demo-only ranking path. An operator may override a keyword for exploration, and
when they do `deviations` reports it and the interface says so, because an
unlabelled second policy is how a demo starts disagreeing with the score.

*Degradation is never silent.* `Agent.respond` cannot raise by design -- the
evaluator replaces the whole response when it does, forfeiting the turn -- so a
failure shows up only as a slightly worse answer. `respond_failures` is read
after every turn and reported, the same check the bundle rehearsal was missing.

*Optional features are detected, not required.* Grounded messages and the lens
trace are being reviewed on separate branches. Rather than import either, the
constructor asks `Agent.__init__` what it accepts, so this runs unchanged on
`main` today and lights the extra fields up if and when those land.
"""
from __future__ import annotations

import inspect
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from needle.agent import Agent
from needle.catalog import extract_category_terms, product_clarification_facets, query_terms
from needle.language import DEFAULT as DEFAULT_LANGUAGE
from needle.language import category_mention as language_category_mention
from needle.language import category_terms as language_category_terms
from needle.language import detect as detect_language
from needle.language import phrases as language_phrases
from needle.language import supported as supported_languages

# Endonyms, so the control reads in the language it selects rather than naming
# it in English. Any code the language module gains and this map lacks falls
# back to the code itself, which is why `get` is used at the call site.
LANGUAGE_LABELS = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "hi": "हिन्दी",
    "ja": "日本語",
    "zh": "中文",
}
from needle.presets import PRIMARY_AGENT_KWARGS
from needle.questions import QuestionDecision, clarification_board
from needle.state import ConstraintStatus, Polarity

from storefront.catalog_view import CatalogView
from storefront.compatibility import RerankResult, rerank_products
from storefront.journey import (
    DeterministicJourneyPlanner,
    JourneyAction,
    ShoppingPlan,
    alternative_queries,
    journey_beliefs,
    query_for,
)

# The evaluator and `StateStore` both accept at most ten turns. The interface
# stops there too: sending an eleventh message would exercise the agent's
# degraded-response guard rather than the selected policy shown on screen.
SCORED_TURN_BUDGET = 10

# Sessions are held for their belief state. This bounds a long-lived server;
# the least recently used conversation is dropped, not the newest.
MAX_LIVE_SESSIONS = 64

# Optional agent keywords this service turns on when the installed Agent accepts
# them. Each is default-off upstream, so absence is the normal case and never an
# error. The interface renders both the grounded message and the compact
# target-blind decision receipt; neither is an unused diagnostic here.
OPTIONAL_AGENT_KWARGS: Mapping[str, object] = {"explain": True, "trace_enabled": True}

_WEARER_QUESTIONS: Mapping[str, str] = {
    "es": "¿Para quién es?",
    "fr": "Pour qui est-ce ?",
    "de": "Für wen ist es?",
    "hi": "यह किसके लिए है?",
    "ja": "誰向けですか。",
    "zh": "是给谁的？",
}


@dataclass(slots=True)
class Turn:
    """One exchange, as the interface renders it."""

    turn: int
    user_message: str
    message: str
    ask_attribute: str | None
    cards: list[dict[str, object]]
    latency_ms: float
    degraded: bool
    beliefs: dict[str, object]
    within_scored_budget: bool
    trace: dict[str, object] | None = None
    journey: dict[str, object] | None = None
    journey_trace: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "turn": self.turn,
            "user_message": self.user_message,
            "message": self.message,
            "ask_attribute": self.ask_attribute,
            "cards": self.cards,
            "latency_ms": round(self.latency_ms, 3),
            "degraded": self.degraded,
            "beliefs": self.beliefs,
            "within_scored_budget": self.within_scored_budget,
        }
        if self.trace is not None:
            payload["trace"] = self.trace
        if self.journey is not None:
            payload["journey"] = self.journey
        if self.journey_trace is not None:
            payload["journey_trace"] = self.journey_trace
        return payload


@dataclass(slots=True)
class Conversation:
    session_id: str
    profile: dict[str, object] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)
    journey: ShoppingPlan | None = None

    @property
    def next_turn(self) -> int:
        return len(self.turns) + 1


class StorefrontService:
    """Thread-safe session manager over a single shared `Agent`.

    One agent serves every conversation. `Agent` keys all mutable state by
    `session_id` -- belief state, seen-item history and the opening category are
    per-session dictionaries -- so concurrent sessions do not interfere.

    Sharing it across the HTTP server's handler threads takes more than a lock.
    `CatalogIndex` opens one `sqlite3.Connection`, and a connection is bound to
    the thread that created it: using it from another raises `ProgrammingError`
    however carefully the callers are serialised. A lock provides mutual
    exclusion, not thread affinity, and those are different properties.

    So every call that can reach SQLite is submitted to a single-worker
    executor, which gives both at once -- one owner thread for the connection
    and one call at a time. The agent is also *constructed* on that thread, so
    the connection is never created anywhere else.

    This was not a theoretical concern: before the executor, every turn served
    over HTTP raised inside `respond`, was absorbed by its never-raise guard and
    came back as an empty slate in half a millisecond. The only reason it was
    not shipped that way is that `respond_failures` is read after every turn.
    """

    def __init__(
        self,
        catalog_path: str | Path,
        *,
        signature_index_path: str | Path | None = None,
        overrides: Mapping[str, object] | None = None,
        max_sessions: int = MAX_LIVE_SESSIONS,
        journey_mode: bool = False,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        if not self.catalog_path.is_file():
            raise FileNotFoundError(f"catalog not found: {self.catalog_path}")
        self.signature_index_path = (
            Path(signature_index_path) if signature_index_path else None
        )
        self.overrides = dict(overrides or {})
        self.max_sessions = max(1, int(max_sessions))
        self.journey_mode = bool(journey_mode)

        self.view = CatalogView(self.catalog_path)
        self.journey_planner = DeterministicJourneyPlanner(
            self._journey_category_mentions,
            self.view.audience_mentions,
        )
        self._agent: Agent | None = None
        self._conversations: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.RLock()
        self._owner = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="needle-agent"
        )
        self._failures_seen = 0
        self.construction_seconds: float | None = None
        self.agent_kwargs, self.enabled_optional = self._resolve_kwargs()

    # -- configuration -------------------------------------------------------

    def _resolve_kwargs(self) -> tuple[dict[str, object], list[str]]:
        """Primary preset, plus any optional keyword the installed Agent accepts."""
        kwargs: dict[str, object] = dict(PRIMARY_AGENT_KWARGS)
        accepted = set(inspect.signature(Agent.__init__).parameters)
        enabled = [name for name in OPTIONAL_AGENT_KWARGS if name in accepted]
        for name in enabled:
            kwargs[name] = OPTIONAL_AGENT_KWARGS[name]
        if self.signature_index_path is not None:
            kwargs["signature_index_path"] = self.signature_index_path
        # An override is applied last and only for a keyword the Agent accepts,
        # so a stale flag fails loudly here rather than at construction.
        for name, value in self.overrides.items():
            if name not in accepted:
                raise ValueError(f"agent does not accept override: {name}")
            kwargs[name] = value
        return kwargs, enabled

    @property
    def deviations(self) -> dict[str, dict[str, object]]:
        """Keywords whose effective value differs from the primary preset.

        Empty means the interface is driving exactly the scored configuration.
        The optional feature keywords are excluded: they are additive channels
        that upstream tests assert leave the recommendations byte-identical.
        """
        differences: dict[str, dict[str, object]] = {}
        for name, value in self.agent_kwargs.items():
            if name in self.enabled_optional or name == "signature_index_path":
                continue
            if name not in PRIMARY_AGENT_KWARGS:
                differences[name] = {"primary": None, "effective": value}
            elif PRIMARY_AGENT_KWARGS[name] != value:
                differences[name] = {
                    "primary": PRIMARY_AGENT_KWARGS[name],
                    "effective": value,
                }
        return differences

    # -- agent ---------------------------------------------------------------

    def _owned(self, call, /, *args: object) -> Any:
        """Run `call` on the thread that owns the agent's SQLite connection."""
        return self._owner.submit(call, *args).result()

    def _build_agent(self) -> Agent:
        if self._agent is None:
            started = time.perf_counter()
            self._agent = Agent(self.catalog_path, **self.agent_kwargs)
            self.construction_seconds = time.perf_counter() - started
        return self._agent

    @property
    def agent(self) -> Agent:
        """The shared agent, constructed on its owner thread on first use.

        Reading attributes of the returned object off-thread is safe; every
        method that can touch SQLite is routed through `_owned` instead.
        """
        if self._agent is None:
            self._owned(self._build_agent)
        assert self._agent is not None
        return self._agent

    def _close_agent(self) -> None:
        if self._agent is not None:
            close = getattr(self._agent, "close", None)
            if callable(close):
                close()
            self._agent = None

    def close(self) -> None:
        with self._lock:
            if self._agent is not None:
                self._owned(self._close_agent)
        self._owner.shutdown(wait=True)

    def __enter__(self) -> "StorefrontService":
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    # -- sessions ------------------------------------------------------------

    def start(
        self,
        session_id: str | None = None,
        profile: Mapping[str, object] | None = None,
        language: str | None = None,
    ) -> Conversation:
        """Open a session, optionally pinned to one of the supported languages.

        Detection from the first message still works and is what the scored
        path relies on. This exists because a reviewer cannot discover that the
        agent answers in seven languages by looking at an English page, and
        typing Japanese to find out is not a discovery path.
        """

        identifier = str(session_id or f"storefront-{uuid.uuid4().hex[:12]}")
        requested = str(language or "").strip().lower()
        if requested and requested not in supported_languages():
            raise ValueError(f"unsupported language: {language!r}")
        with self._lock:
            agent = self.agent
            self._owned(agent.reset, identifier, dict(profile or {}))
            plan = ShoppingPlan(identifier) if self.journey_mode else None
            if plan is not None and requested:
                plan.language = requested
            if requested:
                set_language = getattr(agent, "set_language", None)
                if callable(set_language):
                    self._owned(set_language, identifier, requested)
            conversation = Conversation(
                identifier,
                dict(profile or {}),
                journey=plan,
            )
            self._conversations[identifier] = conversation
            self._conversations.move_to_end(identifier)
            while len(self._conversations) > self.max_sessions:
                self._conversations.popitem(last=False)
            return conversation

    def conversation(self, session_id: str) -> Conversation | None:
        with self._lock:
            found = self._conversations.get(session_id)
            if found is not None:
                self._conversations.move_to_end(session_id)
            return found

    def send(self, session_id: str, user_message: str) -> Turn:
        """Run one turn and return everything the interface needs to draw it."""
        text = str(user_message or "").strip()
        if not text:
            raise ValueError("message is empty")
        with self._lock:
            conversation = self.conversation(session_id)
            if conversation is None:
                conversation = self.start(session_id)
            turn_number = conversation.next_turn
            if turn_number > SCORED_TURN_BUDGET:
                raise ValueError(
                    "ten-turn budget exhausted; start a new conversation"
                )
            if self.journey_mode:
                return self._send_journey(conversation, text, turn_number)
            agent = self.agent

            started = time.perf_counter()
            response = self._owned(agent.respond, session_id, text, turn_number, 10)
            latency_ms = (time.perf_counter() - started) * 1000.0

            failures = list(getattr(agent, "respond_failures", ()))
            degraded = len(failures) > self._failures_seen
            self._failures_seen = len(failures)

            beliefs = self._beliefs(session_id)
            terms = self._evidence_terms(session_id, beliefs, text)
            identifiers = [
                str(item.get("parent_asin", ""))
                for item in response.get("recommendations", [])
            ]
            cards = [
                card.as_dict()
                for card in self.view.cards(
                    identifiers,
                    terms=terms,
                    stale_terms=self._stale_terms(beliefs),
                )
            ]
            turn = Turn(
                turn=turn_number,
                user_message=text,
                message=str(response.get("message", "")),
                ask_attribute=response.get("ask_attribute"),
                cards=cards,
                latency_ms=latency_ms,
                degraded=degraded,
                beliefs=beliefs,
                within_scored_budget=turn_number <= SCORED_TURN_BUDGET,
                trace=self._trace(session_id),
            )
            conversation.turns.append(turn)
            return turn

    def select(self, session_id: str, parent_asin: str) -> dict[str, object]:
        """Confirm one currently displayed product as the active line-item anchor."""

        identifier = str(parent_asin or "").strip()
        if not self.journey_mode:
            raise ValueError("product selection is available only in journey mode")
        with self._lock:
            conversation = self.conversation(session_id)
            if conversation is None or conversation.journey is None:
                raise ValueError("unknown session")
            item = conversation.journey.active_item
            if item is None or identifier not in item.last_ids:
                raise ValueError("product is not in the active line item's current slate")
            item.selected_id = identifier
            product = self.view.raw(identifier) or {}
            audience = self.view.audience(product)
            if item.audience is None and audience:
                item.audience = audience
            return {
                "selected_id": identifier,
                "journey": conversation.journey.as_dict(),
            }

    def _send_journey(
        self,
        conversation: Conversation,
        text: str,
        turn_number: int,
    ) -> Turn:
        """Product-facing orchestration over isolated measured-agent sessions.

        The scored Agent is still the candidate generator.  Journey mode owns
        only state that the one-target evaluator has no way to represent:
        multiple line items, alternatives and cross-item relations.
        """

        plan = conversation.journey
        if plan is None:
            plan = ShoppingPlan(conversation.session_id)
            conversation.journey = plan
        detected_language = detect_language(text)
        if (
            plan.language == DEFAULT_LANGUAGE
            and detected_language in supported_languages()
            and detected_language != DEFAULT_LANGUAGE
        ):
            plan.language = detected_language
        decision = self.journey_planner.observe(plan, text, turn_number)
        item = plan.active_item
        assert item is not None
        _, customer_category = language_category_mention(text)
        if customer_category and item.item_id in decision.created_item_ids:
            item.label = customer_category
        agent = self.agent

        if item.local_turn == 0:
            self._owned(agent.reset, item.agent_session_id, conversation.profile)
        set_language = getattr(agent, "set_language", None)
        if callable(set_language):
            self._owned(set_language, item.agent_session_id, plan.language)
        item.local_turn += 1
        retrieval_text = query_for(plan, item)

        started = time.perf_counter()
        response = self._owned(
            agent.respond,
            item.agent_session_id,
            retrieval_text,
            item.local_turn,
            10,
        )
        base_ids = [
            str(candidate.get("parent_asin", ""))
            for candidate in response.get("recommendations", [])
            if isinstance(candidate, Mapping)
        ]
        related = plan.item(item.related_item_id)
        anchor_id = None
        relation_terms: list[str] = []
        if related is not None:
            anchor_id = related.selected_id or next(iter(related.last_ids), None)
        if anchor_id:
            anchor = self.view.raw(anchor_id)
            if anchor is not None:
                categories = anchor.get("categories")
                if isinstance(categories, list) and len(categories) > 1:
                    relation_terms.extend(query_terms(str(categories[1]), limit=4))
                relation_terms.extend(
                    product_clarification_facets(anchor).get(name, "")
                    for name in ("style", "use_case")
                )
                relation_terms = [term for term in relation_terms if term]
        ranked_sources: list[Sequence[str]] = [base_ids]
        for query in alternative_queries(plan, item):
            category_seeds = (
                self.view.common_categories(6)
                if item.category == "item"
                else [item.category]
            )
            variants = [query, *category_seeds]
            variants.extend(f"{query} {term}" for term in relation_terms)
            variants.extend(
                f"{category} {term}"
                for category in category_seeds
                for term in relation_terms
            )
            for relation_query in dict.fromkeys(variant.strip() for variant in variants):
                candidates = self._owned(
                    lambda q=relation_query: agent.catalog.search(
                        q,
                        120,
                        messages=(q,),
                        excluded_ids=(),
                    )
                )
                ranked_sources.append(
                    [candidate.parent_asin for candidate in candidates]
                )
        candidate_ids = self._reciprocal_rank_merge(ranked_sources, limit=500)

        reranked = rerank_products(
            self.view,
            plan,
            item,
            candidate_ids,
            anchor_id=anchor_id,
            enforce_anchor_audience=bool(
                related is not None and (related.selected_id or related.audience)
            ),
            explore=decision.exploration,
            limit=10,
        )
        identifiers = [product.parent_asin for product in reranked.products]
        item.last_ids = identifiers

        beliefs = journey_beliefs(plan)
        terms = self._journey_evidence_terms(plan, item)
        cards = [
            card.as_dict()
            for card in self.view.cards(
                identifiers,
                terms=terms,
                stale_terms=self._stale_terms(beliefs),
            )
        ]
        by_id = {product.parent_asin: product for product in reranked.products}
        for card in cards:
            ranked = by_id.get(str(card.get("parent_asin", "")))
            if ranked is None:
                continue
            card["journey_score"] = ranked.score
            card["constraint_evidence"] = {
                "matched": ranked.matched_constraints,
                "total": ranked.total_constraints,
            }
            if ranked.compatibility is not None:
                card["compatibility"] = ranked.compatibility.as_dict()

        failures = list(getattr(agent, "respond_failures", ()))
        degraded = len(failures) > self._failures_seen
        self._failures_seen = len(failures)
        latency_ms = (time.perf_counter() - started) * 1000.0
        trace = self._trace(item.agent_session_id)
        question_message, question_decision = self._journey_question(
            plan,
            item,
            identifiers,
            trace,
            anchor_id=anchor_id,
            turn_number=turn_number,
            language=plan.language,
        )
        message = self._journey_message(
            plan,
            item,
            decision.action,
            reranked,
            anchor_id=anchor_id,
            anchor_confirmed=bool(related is not None and related.selected_id),
            question_message=question_message,
            language=plan.language,
        )
        journey_trace = {
            "candidate_sources": len(ranked_sources),
            "merged_candidates": len(candidate_ids),
            "filtered_candidates": len(reranked.filtered_ids),
            "released_candidates": len(identifiers),
            "rerank_reason": reranked.reason,
            "anchor_id": anchor_id,
            "anchor_status": (
                "confirmed"
                if related is not None and related.selected_id
                else "top proposal"
                if anchor_id
                else "none"
            ),
            "question": question_decision,
            "llm_used": False,
            "fallback": "deterministic catalog planner",
        }
        turn = Turn(
            turn=turn_number,
            user_message=text,
            message=message,
            ask_attribute=(
                str(question_decision.get("attribute"))
                if question_decision.get("asks")
                else response.get("ask_attribute")
            ),
            cards=cards,
            latency_ms=latency_ms,
            degraded=degraded,
            beliefs=beliefs,
            within_scored_budget=turn_number <= SCORED_TURN_BUDGET,
            trace=trace,
            journey=plan.as_dict(),
            journey_trace=journey_trace,
        )
        conversation.turns.append(turn)
        return turn

    @staticmethod
    def _reciprocal_rank_merge(
        sources: Sequence[Sequence[str]],
        *,
        limit: int,
    ) -> list[str]:
        """Deterministic union that gives every alternative a path to rank."""

        scores: dict[str, float] = {}
        first_seen: dict[str, tuple[int, int]] = {}
        for source_index, source in enumerate(sources):
            weight = 1.35 if source_index == 0 else 1.0
            for rank, identifier in enumerate(source, start=1):
                if not identifier:
                    continue
                scores[identifier] = scores.get(identifier, 0.0) + weight / (20.0 + rank)
                first_seen.setdefault(identifier, (source_index, rank))
        return [
            identifier
            for identifier, _ in sorted(
                scores.items(),
                key=lambda row: (-row[1], first_seen[row[0]], row[0]),
            )[: max(0, int(limit))]
        ]

    def _journey_category_mentions(self, text: str) -> list[str]:
        """Catalog categories named directly or through the language overlay."""

        mentions = self.view.category_mentions(text)
        translated = language_category_terms(text)
        if translated:
            mentions.extend(self.view.category_mentions(translated))
        return list(dict.fromkeys(mentions))

    @staticmethod
    def _journey_evidence_terms(plan: ShoppingPlan, item: object) -> list[str]:
        terms: list[str] = []
        terms.extend(query_terms(getattr(item, "category", ""), limit=12))
        terms.extend(query_terms(" ".join(plan.global_context), limit=20))
        for group in getattr(item, "constraints", ()):
            for value in group.values:
                terms.extend(query_terms(value, limit=12))
        return list(dict.fromkeys(terms))[:40]

    @staticmethod
    def _journey_message(
        plan: ShoppingPlan,
        item: object,
        action: JourneyAction,
        reranked: RerankResult,
        *,
        anchor_id: str | None,
        anchor_confirmed: bool,
        question_message: str,
        language: str,
    ) -> str:
        label = str(getattr(item, "label", "this item")).lower()
        # An item the customer has not named yet carries the placeholder label
        # "Current item", which is a fine heading in the plan rail and a bad
        # noun in a sentence: "I updated the current item line item" is the
        # first thing the wedding journey says. Every sentence below therefore
        # has a phrasing that does not need a product word.
        unnamed = str(getattr(item, "category", "")) == "item" or label in {
            "current item",
            "this item",
        }
        if not reranked.products:
            missing = "nothing" if unnamed else f"no {label}"
            return (
                f"I kept every stated requirement, but the catalog has {missing} "
                "that satisfies all of them. Which requirement may I relax?"
            )
        if language != DEFAULT_LANGUAGE:
            say = language_phrases(language)
            evidence = [
                *plan.global_context,
                *(
                    value
                    for group in getattr(item, "positive_groups", lambda: ())()
                    for value in group.values
                ),
            ]
            if evidence:
                prefix = say["going_on"].format(
                    values=f" {say['and']} ".join(dict.fromkeys(evidence)),
                    category=label,
                )
            else:
                prefix = say["start"].format(category=label)
        elif anchor_id:
            prefix = (
                f"I ranked these {label} against "
                f"{'your selected item' if anchor_confirmed else 'the current top match'} "
                "using the compatibility evidence available in the catalog."
            )
        elif action is JourneyAction.EXPLORE:
            prefix = (
                f"I found {len(reranked.products)} varied "
                f"{'catalog matches' if unnamed else f'matches for your {label} search'}."
            )
        elif action is JourneyAction.CREATE and len(plan.items) > 1:
            prefix = (
                f"I added {'another item' if unnamed else label} "
                "without losing the rest of your plan."
            )
        else:
            prefix = (
                f"I found {len(reranked.products)} strong catalog matches "
                f"{'for your search' if unnamed else f'for your {label} search'}."
            )
        suffix = question_message.strip()
        return f"{prefix} {suffix}".strip()

    def _journey_question(
        self,
        plan: ShoppingPlan,
        item: object,
        candidate_ids: Sequence[str],
        trace: Mapping[str, object] | None,
        *,
        anchor_id: str | None,
        turn_number: int,
        language: str,
    ) -> tuple[str, dict[str, object]]:
        """Ask the catalog question with the most journey-level information.

        The benchmark trace remains a valid fallback, but its question was
        chosen for one hidden target.  Journey mode recomputes the board over
        the products it actually released.  For a related item, a facet whose
        real options contain the anchor's own value is preferred: that makes
        the question about the relationship without encoding outfit pairs.
        """

        facets = {
            identifier: product_clarification_facets(self.view.raw(identifier) or {})
            for identifier in candidate_ids
        }
        said = [
            *getattr(item, "messages", ()),
            *plan.global_context,
            *(
                value
                for group in getattr(item, "constraints", ())
                for value in group.values
            ),
        ]
        excluded = [
            value
            for group in getattr(item, "negative_groups", lambda: ())()
            for value in group.values
        ]
        asked: list[str] = getattr(item, "asked_facets", [])

        def remember(payload: dict[str, object]) -> dict[str, object]:
            """A facet already put to this customer is not a better question the
            second time. Without this the wedding journey asks "which wearer"
            five turns running, because the slate shrinks under every answer and
            the same facet keeps winning on the new numbers."""
            attribute = str(payload.get("attribute") or "")
            if payload.get("asks") and attribute and attribute not in asked:
                asked.append(attribute)
            raw_options = payload.get("options")
            if payload.get("asks") and attribute and isinstance(raw_options, (list, tuple)):
                values = [
                    str(option[0]).strip().lower()
                    for option in raw_options
                    if isinstance(option, (list, tuple)) and option and str(option[0]).strip()
                ]
                if values:
                    getattr(item, "offered_values", {})[attribute] = values
            return payload

        board = clarification_board(
            candidate_ids,
            facets,
            already_said=said,
            already_asked=asked,
            turns_left=max(0, SCORED_TURN_BUDGET - turn_number),
            excluded_values=excluded,
        )
        selected: QuestionDecision | None = None
        audience_question = (
            None
            if "wearer" in asked
            else self._audience_question(item, candidate_ids, turn_number)
        )
        anchor_facets: Mapping[str, str] = {}
        if anchor_id:
            anchor_facets = product_clarification_facets(self.view.raw(anchor_id) or {})

        if audience_question is not None:
            payload = remember(audience_question)
            return self._render_question(payload, language=language), payload

        if board:
            def relationship_value(decision: QuestionDecision) -> tuple[int, float, float, str]:
                option_values = {value for value, _ in decision.options}
                anchor_value = anchor_facets.get(decision.attribute, "")
                direct_anchor_evidence = int(
                    decision.attribute in {"style", "use_case", "color", "material"}
                    and bool(anchor_value and anchor_value in option_values)
                )
                global_evidence = int(bool(option_values.intersection(plan.global_context)))
                return (
                    direct_anchor_evidence,
                    global_evidence,
                    decision.net_value,
                    decision.attribute,
                )

            if anchor_id:
                relationship_board = [
                    decision
                    for decision in board
                    if decision.attribute in {"style", "use_case", "color", "material"}
                ]
                selected = (
                    max(relationship_board, key=relationship_value)
                    if relationship_board
                    else None
                )
            else:
                selected = board[0]
            if selected is not None and not selected.asks:
                selected = None

        if selected is not None:
            payload = selected.as_dict()
            payload["source"] = "released-candidate clarification board"
            payload["relationship_aware"] = bool(anchor_id)
            # The questions this one beat, with the numbers that decided it.
            # A ranked board is the whole argument for asking anything at all,
            # and it was being computed and thrown away every turn.
            payload["alternatives"] = [
                decision.as_dict()
                for decision in board
                if decision.attribute != selected.attribute
            ][:3]
            return self._render_question(remember(payload), language=language), payload

        if anchor_id:
            payload = {
                "asks": False,
                "source": "relationship-aware stop decision",
                "reason": "no unanswered compatibility facet improves the released candidates",
                "relationship_aware": True,
            }
            return "", payload

        fallback = self._trace_question_decision(trace)
        fallback_attribute = (
            str(fallback.get("attribute") or "")
            if isinstance(fallback, Mapping)
            else ""
        )
        if fallback is None or fallback_attribute in asked:
            payload = {
                "asks": False,
                "source": "catalog stop decision",
                "reason": "no unanswered catalog facet divides the released candidates",
            }
            return "", payload
        payload = dict(fallback)
        payload["source"] = "single-target policy fallback"
        payload["relationship_aware"] = False
        return self._render_question(remember(payload), language=language), payload

    def _audience_question(
        self,
        item: object,
        candidate_ids: Sequence[str],
        turn_number: int,
    ) -> dict[str, object] | None:
        """Ask for wearer only when the released slate genuinely spans audiences."""

        if getattr(item, "audience", None):
            return None
        counts: dict[str, int] = {}
        for identifier in candidate_ids:
            product = self.view.raw(identifier) or {}
            audience = self.view.audience(product)
            if audience:
                counts[audience] = counts.get(audience, 0) + 1
        if len(counts) < 2:
            return None
        total = len(candidate_ids)
        known_count = sum(counts.values())
        unknown_count = max(0, total - known_count)
        expected_remaining = (
            sum(size * size for size in counts.values()) + unknown_count * unknown_count
        ) / max(1, total)
        expected_reduction = max(0.0, 1.0 - expected_remaining / max(1, total))
        interaction_cost = 1.0 / (max(0, SCORED_TURN_BUDGET - turn_number) + 1.0)
        net_value = expected_reduction - interaction_cost
        if net_value <= 0.0:
            return None
        return {
            "attribute": "wearer",
            "options": tuple(sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:4]),
            "candidate_count": total,
            "known_count": known_count,
            "unknown_count": unknown_count,
            "distinct_answer_groups": len(counts) + int(bool(unknown_count)),
            "expected_remaining": round(expected_remaining, 6),
            "expected_candidate_reduction": round(expected_reduction, 6),
            "catalog_coverage": round(known_count / max(1, total), 6),
            "interaction_cost": round(interaction_cost, 6),
            "net_value": round(net_value, 6),
            "asks": True,
            "reason": "audience ambiguity divides the released catalog slate",
            "source": "catalog audience board",
            "relationship_aware": False,
        }

    @staticmethod
    def _trace_question_decision(
        trace: Mapping[str, object] | None,
    ) -> Mapping[str, object] | None:
        if not isinstance(trace, Mapping):
            return None
        policy = trace.get("question_policy")
        if not isinstance(policy, Mapping):
            return None
        decision = policy.get("human_message_decision")
        return decision if isinstance(decision, Mapping) and decision.get("asks") else None

    @staticmethod
    def _render_question(
        decision: Mapping[str, object],
        *,
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        attribute = str(decision.get("attribute") or "detail").replace("_", " ")
        raw_options = decision.get("options")
        options: list[str] = []
        if isinstance(raw_options, (list, tuple)):
            for option in raw_options[:4]:
                if isinstance(option, (list, tuple)) and len(option) >= 2:
                    options.append(f"{option[0]} ({option[1]})")
        choices = ", ".join(options)
        if language != DEFAULT_LANGUAGE:
            say = language_phrases(language)
            facet = say.get(attribute, attribute)
            prompt = (
                _WEARER_QUESTIONS[language]
                if attribute == "wearer" and language in _WEARER_QUESTIONS
                else say["choose"].format(facet=facet)
            )
            return (
                f"{prompt} {choices} -- {say['or_other']}{say['stop']}"
                if choices
                else prompt
            )
        prompt = "Who will wear it?" if attribute == "wearer" else f"Which {attribute} matters most?"
        return (
            f"{prompt} {choices}. You can also answer outside these options."
            if choices
            else prompt
        )

    # -- introspection -------------------------------------------------------

    def _beliefs(self, session_id: str) -> dict[str, object]:
        """Active and superseded constraints, as the belief panel renders them.

        Read defensively: this reaches into the agent's state store, which is
        another owner's module, and a shape change there must degrade the panel
        rather than break the turn that already succeeded.
        """
        empty: dict[str, object] = {
            "wanted": [],
            "excluded": [],
            "superseded": [],
            "intent_version": 1,
        }
        try:
            state = self.agent.state._sessions[session_id]  # noqa: SLF001
        except Exception:  # noqa: BLE001 - a missing panel beats a lost turn
            return empty
        try:
            wanted: list[dict[str, object]] = []
            excluded: list[dict[str, object]] = []
            for constraint in state.active_constraints():
                record = {
                    "attribute": constraint.attribute,
                    "value": constraint.value,
                    "turn": constraint.turn,
                }
                if constraint.polarity is Polarity.NEGATIVE:
                    excluded.append(record)
                else:
                    wanted.append(record)
            superseded = [
                {
                    "attribute": constraint.attribute,
                    "value": constraint.value,
                    "turn": constraint.turn,
                }
                for constraint in state.constraints
                if constraint.status is not ConstraintStatus.ACTIVE
                or constraint.intent_version != state.intent_version
            ]
            return {
                "wanted": wanted,
                "excluded": excluded,
                "superseded": superseded,
                "intent_version": int(state.intent_version),
            }
        except Exception:  # noqa: BLE001
            return empty

    @staticmethod
    def _stale_terms(beliefs: Mapping[str, object]) -> list[str]:
        """Terms from superseded constraints that no active constraint restates.

        The subtraction matters. An override that supersedes `leather` and then
        restates it -- which `retract_stated` does whenever the customer keeps a
        value across the change of mind -- must not mark that value stale; only
        a value the belief state genuinely abandoned qualifies.
        """
        def values(key: str) -> list[str]:
            entries = beliefs.get(key)
            if not isinstance(entries, list):
                return []
            return [
                str(entry.get("value", ""))
                for entry in entries
                if isinstance(entry, Mapping)
            ]

        live: set[str] = set()
        for key in ("wanted", "excluded"):
            for value in values(key):
                live.update(query_terms(value, limit=20))
        stale: set[str] = set()
        for value in values("superseded"):
            stale.update(query_terms(value, limit=20))
        return sorted(stale - live)

    def _evidence_terms(
        self,
        session_id: str,
        beliefs: Mapping[str, object],
        fallback: str,
    ) -> list[str]:
        """Terms a card may cite: what the customer actually told us.

        The sources are the belief state's constraint values and the opening
        category, both of which `needle` extracts itself. That is the semantic
        answer to "why is this here", and it excludes the scaffolding of a
        message -- "for that, what matters is" -- by construction rather than by
        filtering.

        Filtering the full message by document frequency was tried first and is
        wrong in an instructive way. `what` sits on 1968 of the 50000 released
        products and `leather` on 7503, so any threshold that drops the first
        drops the second: conversational words are *rare* in product text, which
        is the same mechanism that made filler words score high in EXP-010.
        Corpus frequency cannot separate scaffolding from content here, and a
        written-down stopword list would only hold for the phrasings I thought
        of.

        Superseded values are included deliberately. They are still in the text
        retrieval reads under `retract_stated`, and `matched_terms` marks them
        stale -- hiding them would make the card agree with the belief panel by
        concealing the disagreement rather than by resolving it.
        """
        terms: list[str] = []
        for key in ("wanted", "excluded", "superseded"):
            entries = beliefs.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, Mapping):
                    terms.extend(query_terms(str(entry.get("value", "")), limit=12))
        try:
            state = self.agent.state._sessions[session_id]  # noqa: SLF001
            terms.extend(extract_category_terms(state.messages))
        except Exception:  # noqa: BLE001 - the category is a bonus, not the source
            pass
        if not terms:
            # Turn one of a free-text conversation often discloses nothing the
            # constraint extractor recognises. The message itself is then the
            # only honest source, and it is the customer's own words.
            terms = query_terms(fallback, limit=20)
        return list(dict.fromkeys(terms))[:40]

    def _trace(self, session_id: str) -> dict[str, object] | None:
        """The target-blind trace rendered for the turn just run, when enabled."""
        if not self.agent_kwargs.get("trace_enabled"):
            return None
        try:
            reader = getattr(self.agent, "trace_for", None)
            if callable(reader):
                recorded = reader(session_id)
                if recorded:
                    latest = recorded[-1]
                    if isinstance(latest, Mapping):
                        return dict(latest)
                return None

            # Compatibility with the short-lived review shape that exposed a
            # public mapping instead of ``trace_for``. The selected Agent uses
            # the method above; keeping this read-only fallback costs nothing
            # and lets the storefront degrade across a partially merged tree.
            traces = getattr(self.agent, "traces", None)
            if isinstance(traces, Mapping):
                recorded = traces.get(session_id)
                if isinstance(recorded, list) and recorded:
                    return dict(recorded[-1])
                if isinstance(recorded, Mapping):
                    return dict(recorded)
        except Exception:  # noqa: BLE001 - a missing trace never costs the turn
            return None
        return None

    # -- interface metadata --------------------------------------------------

    @property
    def index_fallback(self) -> str | None:
        """Why the bundled signature index was rejected, if it was.

        `CatalogIndex` rebuilds in process rather than raising when the asset is
        missing, corrupt, bound to another catalog or written at a schema the
        loader no longer reads. That is the right behaviour -- raising would
        abort before any session runs -- but it is silent, and a rejected asset
        costs tens of seconds of construction while the score stays identical.
        Reporting it is the whole reason the interface has a configuration
        panel. Returns `None` before the agent has been constructed.
        """
        if self._agent is None:
            return None
        reason = getattr(self._agent.catalog, "signature_index_fallback", None)
        return str(reason) if reason else None

    def describe(self) -> dict[str, Any]:
        """Static facts the interface shows in its header and config panel."""
        return {
            "catalog_path": str(self.catalog_path),
            "product_count": self.view.product_count,
            "signature_index": (
                str(self.signature_index_path) if self.signature_index_path else None
            ),
            "construction_seconds": (
                round(self.construction_seconds, 3)
                if self.construction_seconds is not None
                else None
            ),
            "index_fallback": self.index_fallback,
            "optional_features": sorted(self.enabled_optional),
            "deviations": self.deviations,
            "mode": "journey" if self.journey_mode else "benchmark",
            "scored_turn_budget": SCORED_TURN_BUDGET,
            "suggestions": self.view.common_categories(6),
            # The interface offers these as session languages. It asks the
            # language module rather than carrying its own list, so a language
            # added there appears here without a second edit.
            "languages": [
                {"code": code, "label": LANGUAGE_LABELS.get(code, code)}
                for code in supported_languages()
            ],
        }
