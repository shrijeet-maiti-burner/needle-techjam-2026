"""Drive six spontaneous shopping conversations through the shipped service.

This is a semantic release gate, not a score estimate.  It checks the human
constructions the released simulator does not generate: vague intent,
correction, accumulated exclusions, reordered details, budget replacement and
a full intent reset.  Every turn also has to produce a non-degraded, traced,
in-budget slate from the real catalog.

    python scripts/final_human_redteam.py
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KIT = Path(
    os.environ.get(
        "TECHJAM_KIT_ROOT",
        ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search",
    )
)
ASSET = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"
sys.path.insert(0, str(ROOT))

from storefront.service import StorefrontService, Turn  # noqa: E402


def _values(turn: Turn, group: str, attribute: str | None = None) -> set[str]:
    entries = turn.beliefs.get(group, [])
    return {
        str(entry["value"])
        for entry in entries
        if isinstance(entry, dict)
        and (attribute is None or entry.get("attribute") == attribute)
    }


def _assert_turn(turn: Turn, label: str) -> None:
    if turn.degraded:
        raise AssertionError(f"{label}: agent entered degraded fallback")
    if not turn.cards:
        raise AssertionError(f"{label}: agent returned an empty slate")
    if not turn.within_scored_budget:
        raise AssertionError(f"{label}: turn exceeded the scored budget")
    if not isinstance(turn.trace, dict) or not turn.trace.get("target_blind"):
        raise AssertionError(f"{label}: target-blind decision trace is missing")


def _drive(
    service: StorefrontService,
    label: str,
    messages: Iterable[str],
) -> Turn:
    conversation = service.start(session_id=f"human-{label}")
    final: Turn | None = None
    for message in messages:
        final = service.send(conversation.session_id, message)
        _assert_turn(final, label)
    assert final is not None
    return final


def run(service: StorefrontService) -> list[tuple[str, int, int]]:
    results: list[tuple[str, int, int]] = []

    vague = _drive(
        service,
        "vague",
        ["I need something versatile for a wedding, but I'm not sure what style."],
    )
    if "wedding" not in _values(vague, "wanted", "use_case"):
        raise AssertionError("vague: the one explicit use case was lost")
    results.append(("vague", vague.turn, len(vague.cards)))

    correction = _drive(
        service,
        "correction",
        [
            "I want a black cotton jacket.",
            "No, not black - blue works better.",
        ],
    )
    if "blue" not in _values(correction, "wanted", "color"):
        raise AssertionError("correction: replacement color was not retained")
    if "black" not in _values(correction, "excluded", "color"):
        raise AssertionError("correction: rejected color was not excluded")
    if "blue" in _values(correction, "excluded", "color"):
        raise AssertionError("correction: replacement color was also excluded")
    if "cotton" not in _values(correction, "wanted", "material"):
        raise AssertionError("correction: unrelated material was discarded")
    results.append(("correction", correction.turn, len(correction.cards)))

    exclusions = _drive(
        service,
        "exclusions",
        ["I need casual shoes, anything but black, and no leather."],
    )
    if not {"black", "leather"}.issubset(_values(exclusions, "excluded")):
        raise AssertionError("exclusions: independent exclusions did not accumulate")
    if "casual" not in _values(exclusions, "wanted", "style"):
        raise AssertionError("exclusions: positive style was lost")
    results.append(("exclusions", exclusions.turn, len(exclusions.cards)))

    ordered = _drive(
        service,
        "ordered",
        ["Cotton matters; blue would be nice; this is for a wedding."],
    )
    reordered = _drive(
        service,
        "reordered",
        ["For a wedding, blue would be nice; cotton matters."],
    )
    if _values(ordered, "wanted") != _values(reordered, "wanted"):
        raise AssertionError("reordered: equivalent details produced different beliefs")
    results.append(("reordered", reordered.turn, len(reordered.cards)))

    budget = _drive(
        service,
        "budget",
        ["Keep it under $50.", "Actually, up to $200 is fine."],
    )
    if _values(budget, "wanted", "budget") != {"200"}:
        raise AssertionError("budget: the final cap did not replace the old cap")
    results.append(("budget", budget.turn, len(budget.cards)))

    reset = _drive(
        service,
        "reset",
        [
            "I want a black cotton jacket.",
            "Actually, start over. I need white wool for winter.",
        ],
    )
    if reset.beliefs.get("intent_version") != 2:
        raise AssertionError("reset: explicit restart did not create a new intent")
    wanted = _values(reset, "wanted")
    if not {"white", "wool", "winter"}.issubset(wanted):
        raise AssertionError("reset: new intent was not retained")
    if {"black", "cotton"} & wanted:
        raise AssertionError("reset: old intent leaked into active beliefs")
    results.append(("reset", reset.turn, len(reset.cards)))

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=KIT / "data" / "catalog.jsonl")
    parser.add_argument("--signature-index", type=Path, default=ASSET)
    arguments = parser.parse_args(argv)

    if not arguments.catalog.is_file():
        raise SystemExit(
            f"catalog not found: {arguments.catalog}\n"
            "run `python scripts/bootstrap.py` first, or pass --catalog"
        )
    signature = arguments.signature_index if arguments.signature_index.is_file() else None
    with StorefrontService(arguments.catalog, signature_index_path=signature) as service:
        results = run(service)

    for label, turns, cards in results:
        print(f"{label:12} pass  turns={turns}  final_slate={cards}")
    print(f"pass: {len(results)} semantic cases, no degraded or untraced turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
