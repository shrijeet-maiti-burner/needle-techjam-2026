"""EXP-019 companion: the ceiling any emission policy can reach.

Tuning `late_turn` by sweeping is guessing at a policy whose value is fully
determined by one trajectory per session: where the target sits in the agent's
ranked list, turn by turn. This records that trajectory once, then evaluates
emission policies against it offline, including the oracle that knows the answer.

The trajectory is produced under the k=1 walk, so `exclude_seen` behaves exactly
as it does in the measured arm. The session is never cut short: the loop runs all
ten turns and records the target's rank each turn, which is sound because
`customer_reply` and the override injection depend on `ask_attribute`, the
disclosed set and the turn number, never on the slate.

    python3 scripts/emit_oracle.py
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("TECHJAM_KIT_ROOT", ROOT / ".artifacts/participant-kit/techjam-conversational-search"))
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(KIT))

from evaluator import local_evaluator as official  # noqa: E402

import needle.agent as needle_agent  # noqa: E402
import needle.catalog as needle_catalog  # noqa: E402

from needle.presets import PRIMARY_AGENT_KWARGS  # noqa: E402

MAX_TURNS = official.MAX_TURNS
TOP_K = official.TOP_K

BASE_EXTRACT = needle_catalog.extract_query_signatures


def _extract_all_spans(messages):
    """Full-span extraction, as selected in EXP-019."""
    import re

    signatures: list[str] = []
    for message in messages:
        marker = needle_catalog.SIGNATURE_MARKER_RE.search(message)
        if marker:
            for span in marker.group(1).split(";"):
                cleaned = re.sub(r"\s+now\s*[.!?]*\s*$", "", span, flags=re.IGNORECASE)
                signature = needle_catalog.canonical_signature(cleaned)
                if signature:
                    signatures.append(signature)
        material = needle_catalog.MATERIAL_RE.search(message)
        if material:
            signatures.append(needle_catalog.canonical_signature(material.group(1)))
        color = needle_catalog.COLOR_RE.search(message)
        if color:
            signatures.append(needle_catalog.canonical_signature(f"color: {color.group(1)}"))
    return tuple(dict.fromkeys(signatures))


def trajectories(agent, samples, catalog_ids, categories, products) -> list[dict]:
    """Per session: the target's rank in the ranked slate on each turn.

    `None` for a turn where the target is outside the top ten. `earliest` is the
    first turn a hit could legally be recorded, which for `intent_override` is
    the override turn, since the scorer ignores earlier appearances.
    """
    records: list[dict] = []
    for sample in samples:
        session_id = f"oracle_{sample['sample_id']}"
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = official.materialize_hidden_fields(sample, products)
        effective = {**sample, "intent_card": card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        message = official.initial_message(effective, official.coarse_category(categories.get(target, [])), disclosed)

        ranks: list[int | None] = []
        shown: set[str] = set()
        for turn in range(1, MAX_TURNS + 1):
            response = agent.respond(session_id, message, turn, TOP_K)
            ranked = official.normalize_recommendations(response.get("recommendations"), catalog_ids)
            position = ranked.index(target) + 1 if target in ranked else None
            ranks.append(position if override_applied else None)

            # Reproduce the k=1 walk's exclusion so the trajectory matches the
            # arm: only the single product the customer was shown is excluded.
            if ranked:
                shown.add(ranked[0])
            state = agent.state._sessions[session_id]
            agent._seen_by_version[(session_id, state.intent_version)] = set(shown)

            if turn == MAX_TURNS:
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
        records.append({"sample_id": sample["sample_id"], "scenario_type": sample["scenario_type"], "ranks": ranks})
    return records


def score(sessions: list[tuple[bool, float, int]]) -> float:
    """`sessions` is (hit, reciprocal_rank, turns_to_conversion)."""
    count = len(sessions)
    hit_rate = sum(1 for hit, _, _ in sessions if hit) / count
    mrr = statistics.fmean(rr for _, rr, _ in sessions)
    mttc = statistics.fmean(float(ttc) for _, _, ttc in sessions)
    efficiency = max(0.0, min(1.0, (11.0 - mttc) / 10.0))
    return 0.50 * hit_rate + 0.30 * mrr + 0.20 * efficiency


def evaluate_policy(records: list[dict], release: int) -> list[tuple[bool, float, int]]:
    """Emit one product per turn until `release`, then the full slate."""
    out = []
    for record in records:
        result = (False, 0.0, 11)
        for turn, position in enumerate(record["ranks"], start=1):
            if position is None:
                continue
            if turn >= release:
                result = (True, 1.0 / position, turn)
                break
            if position == 1:
                result = (True, 1.0, turn)
                break
        out.append(result)
    return out


def oracle(records: list[dict]) -> list[tuple[bool, float, int]]:
    """Best value any emission policy could extract from each trajectory.

    A policy may emit the target alone on any turn it is ranked (scoring rank 1),
    or emit the full slate (scoring its actual rank). Emitting it alone is never
    worse, so the ceiling is a rank-1 hit on the earliest turn it appears.
    """
    out = []
    for record in records:
        result = (False, 0.0, 11)
        for turn, position in enumerate(record["ranks"], start=1):
            if position is not None:
                result = (True, 1.0, turn)
                break
        out.append(result)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="emission-policy ceiling")
    parser.add_argument("--dataset", type=Path, default=KIT / "data/public_set.jsonl")
    arguments = parser.parse_args()

    needle_catalog.extract_query_signatures = _extract_all_spans
    catalog = KIT / "data/catalog.jsonl"
    samples = official.load_jsonl(str(arguments.dataset))
    catalog_ids, categories, products = official.catalog_index(str(catalog))
    agent = needle_agent.Agent(str(catalog), **dict(PRIMARY_AGENT_KWARGS))

    records = trajectories(agent, samples, catalog_ids, categories, products)

    print(f"{'policy':28s} {'score':>9s} {'HR':>7s} {'MRR':>9s} {'MTTC':>7s}")
    for release in range(2, 12):
        sessions = evaluate_policy(records, release)
        hit = sum(1 for h, _, _ in sessions if h) / len(sessions)
        print(f"{'walk, release turn ' + str(release):28s} {score(sessions):9.6f} {hit:7.4f} "
              f"{statistics.fmean(r for _, r, _ in sessions):9.6f} "
              f"{statistics.fmean(float(t) for _, _, t in sessions):7.3f}")
    sessions = oracle(records)
    hit = sum(1 for h, _, _ in sessions if h) / len(sessions)
    print(f"{'ORACLE (ceiling)':28s} {score(sessions):9.6f} {hit:7.4f} "
          f"{statistics.fmean(r for _, r, _ in sessions):9.6f} "
          f"{statistics.fmean(float(t) for _, _, t in sessions):7.3f}")

    reachable = [turn for record in records
                 for turn, position in enumerate(record["ranks"], start=1) if position is not None]
    print(f"\ntarget reaches the top ten in {sum(1 for r in records if any(p is not None for p in r['ranks']))}"
          f" of {len(records)} sessions")
    needle_catalog.extract_query_signatures = BASE_EXTRACT


if __name__ == "__main__":
    main()
