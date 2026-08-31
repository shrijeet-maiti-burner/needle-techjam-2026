"""Adversarial gate for the product-facing, multi-item shopping journey.

This does not claim a benchmark score.  It drives the real 50,000-product
catalog through human conversation shapes that the one-target simulator cannot
express and fails on state corruption, silent assumptions, unrelated products,
or missing evidence.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from needle.catalog import _flatten_values, query_terms
from storefront.service import StorefrontService


DEFAULT_KIT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
DEFAULT_INDEX = ROOT / ".artifacts" / "indexes" / "catalog-signatures.sqlite3"


def _category_ok(category: str, card: Mapping[str, object]) -> bool:
    wanted = set(query_terms(category, limit=12))
    path = " ".join(str(value) for value in _flatten_values(card.get("categories")))
    return bool(wanted.intersection(query_terms(path, limit=80)))


def run(catalog: Path, index: Path | None) -> list[str]:
    failures: list[str] = []
    with StorefrontService(
        catalog,
        signature_index_path=index if index and index.is_file() else None,
        journey_mode=True,
    ) as service:
        # Ambiguous outfit: ask rather than infer wearer, preserve alternatives,
        # confirm a user-chosen anchor, then create a separate related item.
        conversation = service.start("redteam-outfit")
        first = service.send(conversation.session_id, "I'm getting married and need a suit")
        if first.ask_attribute != "wearer":
            failures.append("outfit turn 1 did not expose unresolved wearer ambiguity")
        if not first.cards:
            failures.append("outfit turn 1 returned an empty slate")
        second = service.send(
            conversation.session_id,
            "for men; blue or white, or preferably one with both colors",
        )
        groups = second.journey["items"][0]["constraints"]
        if not any(group["operator"] == "any" and set(group["values"]) == {"blue", "white"} for group in groups):
            failures.append("blue-or-white alternatives collapsed in journey state")
        if second.cards:
            service.select(conversation.session_id, str(second.cards[0]["parent_asin"]))
        shoes = service.send(conversation.session_id, "add shoes to go along with it")
        if len(shoes.journey["items"]) != 2:
            failures.append("related shoes replaced the suit instead of creating a line item")
        if shoes.journey_trace.get("anchor_status") != "confirmed":
            failures.append("the selected suit was not used as the confirmed relation anchor")
        if not shoes.cards:
            failures.append("related-shoe turn returned an empty slate")
        for card in shoes.cards:
            if not _category_ok("shoes", card):
                failures.append(f"related-shoe turn leaked another category: {card.get('parent_asin')}")
            categories = [str(value).lower() for value in card.get("categories", [])]
            if len(categories) > 1 and categories[1] != "men":
                failures.append(f"confirmed men's journey leaked audience {categories[1]!r}")
            compatibility = card.get("compatibility")
            if not isinstance(compatibility, Mapping) or not compatibility.get("confidence"):
                failures.append(f"related product lacks confidence-labelled evidence: {card.get('parent_asin')}")

        # Direct intent, correction and explanation must preserve boundaries.
        conversation = service.start("redteam-correction")
        black = service.send(conversation.session_id, "black running shoes")
        if not black.cards or any(not _category_ok("running shoes", card) for card in black.cards):
            failures.append("direct black-running-shoes intent crossed a category boundary")
        corrected = service.send(conversation.session_id, "actually, not black - blue instead")
        item = corrected.journey["items"][0]
        live = {(group["operator"], tuple(group["values"])) for group in item["constraints"]}
        if ("not", ("black",)) not in live or ("all", ("blue",)) not in live:
            failures.append("clause-scoped black-to-blue correction was not preserved")
        before = item["constraints"]
        compared = service.send(conversation.session_id, "why is blue above white?")
        if compared.journey["items"][0]["constraints"] != before:
            failures.append("comparison operands mutated preference state")

        # Vague input must explore from the catalog rather than return nothing.
        conversation = service.start("redteam-vague")
        vague = service.send(
            conversation.session_id,
            "I don't know what I want; give me some suggestions",
        )
        if not vague.cards or not vague.journey.get("exploration"):
            failures.append("first-turn vagueness did not produce catalog exploration")

        for turn in (first, second, shoes, black, corrected, compared, vague):
            if turn.degraded:
                failures.append(f"turn {turn.turn} silently degraded")
            if not turn.journey_trace:
                failures.append(f"turn {turn.turn} lacks a journey decision trace")
            if len(turn.cards) > 10:
                failures.append(f"turn {turn.turn} exceeded the ten-product contract")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_KIT / "data" / "catalog.jsonl")
    parser.add_argument("--signature-index", type=Path, default=DEFAULT_INDEX)
    arguments = parser.parse_args()
    if not arguments.catalog.is_file():
        parser.error(f"catalog not found: {arguments.catalog}")
    failures = run(arguments.catalog, arguments.signature_index)
    if failures:
        print(f"FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PASS: multi-item, ambiguity, correction, selection, integrity and evidence gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
