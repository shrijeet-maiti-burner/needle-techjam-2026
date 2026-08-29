from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping


EXPLICIT_OVERRIDE_RE = re.compile(
    r"\b(?:ignore my earlier preference|ignore what i said|changed my mind|instead i need|actually,? instead)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class SessionState:
    session_id: str
    user_profile: dict[str, object]
    messages: list[str] = field(default_factory=list)
    intent_version: int = 1
    last_turn: int = 0

    def observe(self, user_message: str, turn: int) -> None:
        if not 1 <= turn <= 10:
            raise ValueError(f"turn must be in 1..10, received {turn}")
        if turn <= self.last_turn:
            raise ValueError(f"turn must increase for session {self.session_id}")
        if EXPLICIT_OVERRIDE_RE.search(user_message):
            self.intent_version += 1
            self.messages.clear()
        self.messages.append(user_message)
        self.last_turn = turn

    @property
    def retrieval_text(self) -> str:
        return " ".join(self.messages)


class StateStore:
    """Small H6 lifecycle boundary; richer constraint state belongs behind this API."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def reset(self, session_id: str, user_profile: Mapping[str, object]) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty")
        self._sessions[session_id] = SessionState(session_id, dict(user_profile))

    def observe(self, session_id: str, user_message: str, turn: int) -> SessionState:
        try:
            state = self._sessions[session_id]
        except KeyError as error:
            raise RuntimeError("reset must be called before respond") from error
        state.observe(user_message, turn)
        return state
