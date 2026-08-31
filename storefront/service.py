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
from typing import Any, Mapping

from needle.agent import Agent
from needle.catalog import extract_category_terms, query_terms
from needle.presets import PRIMARY_AGENT_KWARGS
from needle.state import ConstraintStatus, Polarity

from storefront.catalog_view import CatalogView

# The evaluator and `StateStore` both accept at most ten turns. The interface
# stops there too: sending an eleventh message would exercise the agent's
# degraded-response guard rather than the selected policy shown on screen.
SCORED_TURN_BUDGET = 10

# Sessions are held for their belief state. This bounds a long-lived server;
# the least recently used conversation is dropped, not the newest.
MAX_LIVE_SESSIONS = 64

# Optional agent keywords this service will pass if the installed Agent accepts
# them. Each is default-off upstream, so absence is the normal case and never an
# error. `explain` is PR #24 (grounded customer message); `trace_enabled` is
# PR #25 (target-blind decision trace).
OPTIONAL_AGENT_KWARGS: Mapping[str, object] = {"explain": True, "trace_enabled": True}


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
        return payload


@dataclass(slots=True)
class Conversation:
    session_id: str
    profile: dict[str, object] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)

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
    ) -> None:
        self.catalog_path = Path(catalog_path)
        if not self.catalog_path.is_file():
            raise FileNotFoundError(f"catalog not found: {self.catalog_path}")
        self.signature_index_path = (
            Path(signature_index_path) if signature_index_path else None
        )
        self.overrides = dict(overrides or {})
        self.max_sessions = max(1, int(max_sessions))

        self.view = CatalogView(self.catalog_path)
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
    ) -> Conversation:
        identifier = str(session_id or f"storefront-{uuid.uuid4().hex[:12]}")
        with self._lock:
            agent = self.agent
            self._owned(agent.reset, identifier, dict(profile or {}))
            conversation = Conversation(identifier, dict(profile or {}))
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
        """The lens trace for the turn just run, when the installed Agent emits one."""
        if "trace_enabled" not in self.enabled_optional:
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
        except Exception:  # noqa: BLE001
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
            "scored_turn_budget": SCORED_TURN_BUDGET,
            "suggestions": self.view.common_categories(6),
        }
