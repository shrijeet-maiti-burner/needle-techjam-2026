from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from needle.contracts import ALLOWED_ASK_ATTRIBUTES


@dataclass(slots=True)
class ContractReport:
    response_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        ordered = sorted(self.latencies_ms)
        return {
            "passed": not self.violations,
            "response_count": self.response_count,
            "violation_count": len(self.violations),
            "violations": self.violations,
            "latency_ms": {
                "min": _percentile(ordered, 0.0),
                "p50": _percentile(ordered, 0.50),
                "p95": _percentile(ordered, 0.95),
                "p99": _percentile(ordered, 0.99),
                "max": _percentile(ordered, 1.0),
            },
        }


def _percentile(ordered: list[float], probability: float) -> float | None:
    if not ordered:
        return None
    rank = max(1, math.ceil(probability * len(ordered)))
    return round(ordered[rank - 1], 6)


def _display_keys(keys: set[object]) -> list[str]:
    return sorted(repr(key) for key in keys)


class ContractCheckingAgent:
    """Transparent agent proxy that records strict-contract and latency failures."""

    def __init__(self, wrapped: Any, catalog_ids: set[str]) -> None:
        self.wrapped = wrapped
        self.catalog_ids = catalog_ids
        self.report = ContractReport()

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.wrapped.reset(session_id, user_profile)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> object:
        started = time.perf_counter()
        try:
            response = self.wrapped.respond(session_id, user_message, turn, top_k)
        except Exception as error:
            self.report.violations.append(
                f"session={session_id} turn={turn}: agent raised {type(error).__name__}"
            )
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1_000
            self.report.latencies_ms.append(elapsed_ms)
            self.report.response_count += 1
        self.report.violations.extend(
            validate_response(response, self.catalog_ids, session_id=session_id, turn=turn)
        )
        return response


def validate_response(
    response: object,
    catalog_ids: set[str],
    *,
    session_id: str = "unknown",
    turn: int = 0,
) -> list[str]:
    prefix = f"session={session_id} turn={turn}"
    violations: list[str] = []
    if not isinstance(response, dict):
        return [f"{prefix}: response is not an object"]

    allowed_keys = {"message", "ask_attribute", "recommendations", "usage"}
    required_keys = {"message", "ask_attribute", "recommendations"}
    unknown_keys = set(response) - allowed_keys
    missing_keys = required_keys - set(response)
    if unknown_keys:
        violations.append(f"{prefix}: unknown response keys {_display_keys(unknown_keys)}")
    if missing_keys:
        violations.append(f"{prefix}: missing response keys {_display_keys(missing_keys)}")
    if not isinstance(response.get("message"), str):
        violations.append(f"{prefix}: message is not a string")

    ask_attribute = response.get("ask_attribute")
    if ask_attribute is not None and (
        not isinstance(ask_attribute, str)
        or ask_attribute not in ALLOWED_ASK_ATTRIBUTES
    ):
        violations.append(f"{prefix}: invalid ask_attribute {ask_attribute!r}")

    recommendations = response.get("recommendations")
    if not isinstance(recommendations, list):
        violations.append(f"{prefix}: recommendations is not a list")
    else:
        if len(recommendations) > 10:
            violations.append(f"{prefix}: recommendations contains more than 10 items")
        seen: set[str] = set()
        for index, item in enumerate(recommendations):
            location = f"{prefix} recommendation={index}"
            if not isinstance(item, dict):
                violations.append(f"{location}: item is not an object")
                continue
            item_unknown = set(item) - {"parent_asin", "score"}
            if item_unknown:
                violations.append(f"{location}: unknown keys {_display_keys(item_unknown)}")
            parent_asin = item.get("parent_asin")
            if not isinstance(parent_asin, str) or not parent_asin:
                violations.append(f"{location}: parent_asin is not a non-empty string")
                continue
            if parent_asin in seen:
                violations.append(f"{location}: duplicate parent_asin {parent_asin}")
            seen.add(parent_asin)
            if parent_asin not in catalog_ids:
                violations.append(f"{location}: unknown parent_asin {parent_asin}")
            score = item.get("score")
            if "score" in item and (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                violations.append(f"{location}: score is not numeric")

    usage = response.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            violations.append(f"{prefix}: usage is not an object")
        else:
            expected_usage_keys = {"prompt_tokens", "completion_tokens"}
            if set(usage) != expected_usage_keys:
                violations.append(f"{prefix}: usage keys must be {sorted(expected_usage_keys)}")
            for key in expected_usage_keys:
                value = usage.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    violations.append(f"{prefix}: {key} is not a non-negative integer")
    return violations
