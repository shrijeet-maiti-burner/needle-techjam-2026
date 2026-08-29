"""EXP-013 question-policy arms against the official evaluator.

Reproduces docs/evidence/EXP_013.md. Every arm holds retrieval, state, and
slate configuration fixed and varies only `ask_attribute` selection, except the
two arms that additionally withhold uninformative customer replies from the
retrieval query (labelled below).

The arms are applied by wrapping `Agent.respond` after the shipped call, so the
slate an arm emits is byte-identical to the shipped agent's slate at the same
message history. Nothing here is imported by the agent or the submission.

    python3 scripts/qpolicy_arms.py            # all arms
    python3 scripts/qpolicy_arms.py A C        # named arms only
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("TECHJAM_KIT_ROOT", ROOT / ".artifacts/participant-kit/techjam-conversational-search"))
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(KIT))

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl  # noqa: E402

import needle.agent as needle_agent  # noqa: E402
import needle.state as needle_state  # noqa: E402


# Fixed controls. Only `ask_attribute` selection varies between arms.
BASE_KWARGS: dict[str, object] = {
    "retrieval_mode": "signature_first",
    "signature_bucket_limit": 100,
    "popularity_strength": 0.20,
    "override_policy": "retract_stated",
    "exclude_seen": True,
    "slate_size": 10,
    "lexical_mode": "none",
}

# The two released simulator replies that disclose nothing about the target.
UNINFORMATIVE_REPLY_RE = re.compile(
    r"^I don'?t have (?:an additional preference for|a preference for)\b"
    r"|^Those options are not quite right yet\b",
    re.IGNORECASE,
)

# Buckets `classify_constraint` can emit, in descending public frequency:
# feature 404, material 302, color 60, style 19, size 11, use_case 4.
BY_FREQUENCY = ("feature", "material", "color", "style", "size", "use_case")
ANSWERABLE = ("budget", "material", "color", "size", "style", "use_case", "feature")

BASE_OBSERVE = needle_state.SessionState.observe
BASE_RESPOND = needle_agent.Agent.respond


def _policy(arm: str, turn: int) -> str | None:
    """Return the `ask_attribute` an arm asks on `turn`, or None to stay silent."""
    if turn >= 10:
        return None  # turn 10 has no reply, so the question is unobservable
    if arm in ("A", "B"):
        return "other"
    if arm == "C":
        return None
    if arm == "D":
        return "other" if turn <= 2 else None
    if arm in ("E", "G"):
        return ANSWERABLE[(turn - 1) % len(ANSWERABLE)]
    if arm == "F":
        return "other" if turn <= 2 else ANSWERABLE[(turn - 3) % len(ANSWERABLE)]
    if arm == "H":
        return ("feature", "material", "feature", "material")[turn - 1] if turn <= 4 else "other"
    if arm == "I":
        return BY_FREQUENCY[turn - 1] if turn <= len(BY_FREQUENCY) else "other"
    if arm == "J":
        return ("feature", "material")[turn - 1] if turn <= 2 else "other"
    raise ValueError(f"unknown arm {arm!r}")


ARMS: dict[str, tuple[str, bool]] = {
    # arm: (description, withhold uninformative replies from the query)
    "A": ("repeated `other` (shipped)", False),
    "B": ("repeated `other`, uninformative replies withheld", True),
    "C": ("never ask (no-question control)", False),
    "D": ("`other` x2, then stop asking", False),
    "E": ("fixed rotation over all 7 answerable buckets", False),
    "F": ("`other` x2, then bucket rotation", False),
    "G": ("bucket rotation, uninformative replies withheld", True),
    "H": ("answerability-ordered feature/material", False),
    "I": ("frequency-ordered rotation", False),
    "J": ("`feature`, `material`, then `other`", False),
}


def _install(arm: str, withhold: bool) -> None:
    def observe(self, user_message: str, turn: int) -> None:
        if withhold and UNINFORMATIVE_REPLY_RE.search(user_message.strip()):
            if not 1 <= turn <= 10:
                raise ValueError(f"turn must be in 1..10, received {turn}")
            self.last_turn = turn  # the turn happened; its text carries nothing
            return
        BASE_OBSERVE(self, user_message, turn)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int):
        response = BASE_RESPOND(self, session_id, user_message, turn, top_k)
        response["ask_attribute"] = _policy(arm, turn)
        return response

    needle_state.SessionState.observe = observe
    needle_agent.Agent.respond = respond


def _restore() -> None:
    needle_state.SessionState.observe = BASE_OBSERVE
    needle_agent.Agent.respond = BASE_RESPOND


def main() -> None:
    catalog = KIT / "data/catalog.jsonl"
    dataset = KIT / "data/public_set.jsonl"
    missing = [path for path in (catalog, dataset) if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise SystemExit(f"official kit is incomplete ({formatted}); run python scripts/bootstrap.py")

    samples = load_jsonl(str(dataset))
    catalog_ids, categories, products = catalog_index(str(catalog))
    selected = [arm.upper() for arm in sys.argv[1:]] or list(ARMS)

    for arm in selected:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm!r}; choose from {', '.join(ARMS)}")
        description, withhold = ARMS[arm]
        _install(arm, withhold)
        started = time.time()
        try:
            agent = needle_agent.Agent(str(catalog), **BASE_KWARGS)
            result = evaluate(agent, samples, catalog_ids, categories, products)
        finally:
            _restore()
        override = result["scenario_metrics"].get("intent_override", {})
        boundary = result["scenario_metrics"].get("boundary", {})
        print(
            f"{arm} {description:52s} "
            f"score={result['recommended_technical_score']:.6f} "
            f"hr={result['hit_rate_at_10']:.4f} mrr={result['mrr']:.6f} "
            f"mttc={result['mttc']:.3f} override_hr={override.get('hit_rate_at_10', 0):.3f} "
            f"boundary_hr={boundary.get('hit_rate_at_10', 0):.3f} "
            f"({time.time() - started:.0f}s)",
            flush=True,
        )


if __name__ == "__main__":
    main()
