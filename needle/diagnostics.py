from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from needle.agent import Agent
from needle.contracts import TurnResponse


def surface_noise(message: str) -> str:
    """Deterministic case, Unicode, whitespace, and punctuation variation."""
    normalized = unicodedata.normalize("NFD", message.upper())
    without_punctuation = re.sub(r"[^\w\s$]", " ", normalized)
    return "  " + re.sub(r"\s+", "   ", without_punctuation).strip() + "  "


def template_paraphrase(message: str) -> str:
    """Paraphrase released simulator templates while preserving their facts."""
    transformed = re.sub(
        r"\bI(?:'|’)m looking for\s+(.+?)(?=[.]|$)",
        r"I'm after \1",
        message,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(
        r"\bA key requirement is:\s*",
        "I absolutely need ",
        transformed,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(
        r"\bFor that, what matters is:\s*",
        "The important details are ",
        transformed,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(
        r"\bActually, ignore my earlier preference\. What I need is:\s*(.+?)(?=[.]|$)",
        r"I've changed my mind about that earlier preference. I need \1 now",
        transformed,
        flags=re.IGNORECASE,
    )
    transformed = re.sub(
        r"\bI don't have (?:an additional|a) preference for (\w+); please use your judgment\.",
        r"I have no strong feelings about \1; decide for me.",
        transformed,
        flags=re.IGNORECASE,
    )
    return transformed.replace("; ", " and ")


PERTURBATIONS: dict[str, Callable[[str], str]] = {
    "surface": surface_noise,
    "paraphrase": template_paraphrase,
}


class PerturbedAgent:
    """Evaluation-only wrapper for deterministic input robustness checks."""

    def __init__(self, *, perturbation_mode: str, **agent_kwargs: object) -> None:
        try:
            self.transform = PERTURBATIONS[perturbation_mode]
        except KeyError as error:
            raise ValueError(f"unsupported perturbation mode: {perturbation_mode}") from error
        self.agent = Agent(**agent_kwargs)

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.agent.reset(session_id, user_profile)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> TurnResponse:
        return self.agent.respond(
            session_id,
            self.transform(user_message),
            turn,
            top_k,
        )
