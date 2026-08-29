from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


AskAttribute = Literal[
    "category",
    "material",
    "color",
    "size",
    "style",
    "brand",
    "budget",
    "feature",
    "use_case",
    "other",
]

ALLOWED_ASK_ATTRIBUTES = frozenset(
    {
        "category",
        "material",
        "color",
        "size",
        "style",
        "brand",
        "budget",
        "feature",
        "use_case",
        "other",
    }
)


class RecommendationPayload(TypedDict):
    parent_asin: str


class UsagePayload(TypedDict):
    prompt_tokens: int
    completion_tokens: int


class TurnResponse(TypedDict):
    message: str
    ask_attribute: AskAttribute | None
    recommendations: list[RecommendationPayload]
    usage: UsagePayload


@dataclass(frozen=True, slots=True)
class Candidate:
    """Minimum candidate fields required by the H6 integration path."""

    parent_asin: str
    sparse_score: float
