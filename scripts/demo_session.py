"""Print one full multi-turn session, as the official simulator drives it.

The competition's final deliverables ask for "one demonstrated multi-turn
session". This is that, and it is a real transcript rather than a staged one:
the customer messages come from `local_evaluator`'s own `initial_message`,
`customer_reply` and override injection, and the hit test is the evaluator's,
so what is printed is what the scorer saw.

Offline, no network, no model, zero tokens.

    python3 scripts/demo_session.py                          # a buying session
    python3 scripts/demo_session.py --scenario intent_override
    python3 scripts/demo_session.py --scenario boundary --sample public_0041
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("TECHJAM_KIT_ROOT", ROOT / ".artifacts/participant-kit/techjam-conversational-search"))
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(KIT))

from evaluator import local_evaluator as official  # noqa: E402

from needle.agent import Agent  # noqa: E402
from needle.presets import PRIMARY_AGENT_KWARGS  # noqa: E402

RULE = "-" * 78


def _wrap(label: str, text: str) -> str:
    body = textwrap.fill(text, width=74, subsequent_indent=" " * 11) if text else "(empty)"
    return f"  {label:<8} {body}"


def main() -> None:
    parser = argparse.ArgumentParser(description="print one scored multi-turn session")
    parser.add_argument("--scenario", default="buying",
                        choices=["buying", "browsing", "intent_override", "boundary"])
    parser.add_argument("--sample", default=None, help="a specific sample_id")
    parser.add_argument("--show", type=int, default=3, help="recommendations to print per turn")
    arguments = parser.parse_args()

    catalog_path = KIT / "data" / "catalog.jsonl"
    dataset_path = KIT / "data" / "public_set.jsonl"
    missing = [str(path) for path in (catalog_path, dataset_path) if not path.is_file()]
    if missing:
        raise SystemExit(f"official kit is incomplete ({', '.join(missing)}); run python scripts/bootstrap.py")

    samples = official.load_jsonl(str(dataset_path))
    catalog_ids, categories, products = official.catalog_index(str(catalog_path))

    if arguments.sample:
        chosen = next((s for s in samples if s["sample_id"] == arguments.sample), None)
        if chosen is None:
            raise SystemExit(f"no sample {arguments.sample!r} in the public set")
    else:
        chosen = next((s for s in samples if s["scenario_type"] == arguments.scenario), None)
        if chosen is None:
            raise SystemExit(f"no {arguments.scenario} session in the public set")

    agent = Agent(str(catalog_path), **dict(PRIMARY_AGENT_KWARGS))
    session_id = f"demo_{chosen['sample_id']}"
    agent.reset(session_id, chosen["user_profile"])

    target = str(chosen["ground_truth"]["parent_asin"])
    card, behavior = official.materialize_hidden_fields(chosen, products)
    effective = {**chosen, "intent_card": card, "behavior": behavior}
    disclosed: set[str] = set()
    boundary_used = False
    # An intent_override session cannot score before the new intent is sent;
    # the evaluator encodes that here, so the demo shows it rather than hides it.
    override_applied = chosen["scenario_type"] != "intent_override"
    message = official.initial_message(
        effective, official.coarse_category(categories.get(target, [])), disclosed
    )

    title = products.get(target, {}).get("title", "")
    print(RULE)
    print(f"  session   {chosen['sample_id']}   scenario {chosen['scenario_type']}")
    print(f"  target    {target}  {textwrap.shorten(str(title), 58)}")
    print(f"  hidden    hard={card['hard_constraints']}")
    print(f"            soft={card['soft_preferences']}")
    print(RULE)

    hit_turn = None
    for turn in range(1, official.MAX_TURNS + 1):
        response = agent.respond(session_id, message, turn, official.TOP_K)
        ranked = official.normalize_recommendations(response.get("recommendations"), catalog_ids)

        print(f"\nturn {turn}")
        print(_wrap("customer", message))
        print(_wrap("agent", str(response.get("message", ""))))
        print(_wrap("asks", str(response.get("ask_attribute"))))
        for position, parent_asin in enumerate(ranked[: arguments.show], start=1):
            marker = "  <-- target" if parent_asin == target else ""
            name = textwrap.shorten(str(products.get(parent_asin, {}).get("title", "")), 46)
            print(f"    {position:>2}. {parent_asin}  {name}{marker}")
        if len(ranked) > arguments.show:
            print(f"        ... {len(ranked) - arguments.show} more, {len(ranked)} scored in total")

        if override_applied and target in ranked:
            hit_turn = turn
            print(f"\n  HIT on turn {turn} at rank {ranked.index(target) + 1}. Session ends here:")
            print("  the evaluator breaks on the first appearance and never re-reads the rank.")
            break
        if not override_applied:
            print("  (not scorable yet: the override has not been sent)")

        if turn == official.MAX_TURNS:
            break
        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            message = str(override.get("message", "Actually, please ignore my earlier preference."))
        else:
            message, boundary_used = official.customer_reply(
                effective, response.get("ask_attribute"), disclosed, boundary_used
            )

    print()
    print(RULE)
    if hit_turn is None:
        print("  MISS: the target never entered the scored slate within 10 turns.")
    else:
        turns_to_conversion = float(hit_turn)
        print(f"  turns to conversion {turns_to_conversion:.0f}   "
              f"session score contribution "
              f"{0.50 + 0.30 * (1.0 / (ranked.index(target) + 1)) + 0.20 * (11 - turns_to_conversion) / 10:.4f}")
    print("  tokens 0, no network, no model.")
    print(RULE)


if __name__ == "__main__":
    main()
