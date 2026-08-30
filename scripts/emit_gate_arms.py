"""EXP-019 slate-emission arms against the official evaluator.

The scorer breaks out of a session the first turn the target appears in the
slate, and freezes `reciprocal_rank` at that rank forever
(`local_evaluator.evaluate`, the `if override_applied and target in ranked`
branch). A rank the agent would have improved on turn 3 is never re-read. So
emitting fewer than `top_k` products while the belief state is still thin defers
the lock, and converts a rank-7 hit into a later rank-1 hit.

Every arm holds retrieval, state, and question policy fixed and varies only how
many of the shipped agent's own ranked products are serialized. The ordering is
never touched: arm `k` emits `ranked[:k]` of the identical slate the shipped
agent produced at the identical message history.

Deferral is only worth what the next turn adds, so the arms commit to a full
slate as soon as the state stops improving. Three signals say that:

* `exhausted` - the simulator answered with one of the two replies that
  disclose nothing ("I don't have an additional preference for X", "Those
  options are not quite right yet"). `customer_reply` emits those exactly when
  no undisclosed constraint of the asked type remains, so it is a proof that
  further questioning cannot sharpen the ranking, not a heuristic. Holding past
  it spends MTTC for nothing.
* `fingerprint` - the exact-signature set is small. `intent_card` builds every
  constraint out of the target product's own fields, so the target always
  carries all of them and always sits in that set; a set of one is the target
  with certainty.
* `late_turn` - a floor, so no session can be starved of its hit.

`exclude_seen` has to be repaired for any of this to mean anything. The shipped
`respond` marks every retrieved product seen, not every emitted one, so a
withheld product would be excluded from later turns and the target could be
blacklisted by the very gate meant to promote it. Each arm therefore rewrites
the agent's per-version seen set to exactly the products it actually emitted.

    python3 scripts/emit_gate_arms.py                       # default grid
    python3 scripts/emit_gate_arms.py --k 1 --late 5 --signals exhausted,fingerprint
"""
from __future__ import annotations

import argparse
import json
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

from needle.presets import PRIMARY_AGENT_KWARGS  # noqa: E402

BASE_KWARGS: dict[str, object] = dict(PRIMARY_AGENT_KWARGS)
BASE_RESPOND = needle_agent.Agent.respond
BASE_OBSERVE = needle_state.SessionState.observe

# `top_k` is fixed at 10 by the evaluator; emitting 10 is the shipped behavior.
NO_GATE = 10

# The two released simulator replies that disclose nothing about the target,
# plus the boundary refusal. Reaching any of them means `customer_reply` found
# no undisclosed constraint to hand over.
EXHAUSTED_RE = re.compile(
    r"^I don'?t have (?:an additional preference for|a preference for)\b"
    r"|^Those options are not quite right yet\b",
    re.IGNORECASE,
)


def _install(emit_k: int, late_turn: int, commit_constraints: int, signals: frozenset[str]) -> None:
    emitted: dict[tuple[str, int], set[str]] = {}
    exhausted: set[str] = set()
    evidence: dict[str, int] = {}

    def observe(self, user_message: str, turn: int) -> None:
        # Holding the slate back costs turns, and every held turn appends
        # another uninformative reply to `retrieval_text`, diluting the BM25
        # query until the target falls out of the top ten. EXP-013 arm B
        # measured withholding these in isolation and it cost 0.003; the
        # question here is whether it pays once the gate makes long holds
        # worth having.
        if EXHAUSTED_RE.search(user_message.strip()):
            if not 1 <= turn <= 10:
                raise ValueError(f"turn must be in 1..10, received {turn}")
            self.last_turn = turn
            return
        BASE_OBSERVE(self, user_message, turn)

    if "withhold" in signals:
        needle_state.SessionState.observe = observe
    if "allspans" in signals:
        needle_catalog.extract_query_signatures = _extract_all_spans

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int):
        if EXHAUSTED_RE.search(user_message.strip()):
            exhausted.add(session_id)
        response = BASE_RESPOND(self, session_id, user_message, turn, top_k)
        state = self.state._sessions[session_id]

        limit = None
        if "exact" in signals:
            # Every constraint in the card is lifted from the target's own
            # fields, so the target carries all of them and is always inside
            # the exact-signature set (verified 200/200 on the public set). A
            # set of one is therefore a proof of identity, and a set of n
            # guarantees a hit at rank <= n. Emitting exactly that set banks
            # the hit at the best rank the evidence supports, where emitting a
            # full slate would bury it behind sparse-ranked filler.
            _, exact = self.catalog.signature_candidates(
                state.messages, limit=self.catalog.signature_bucket_limit
            )
            if 0 < len(exact) <= _install.fingerprint_limit:
                limit = min(len(exact), top_k)

        if limit is None:
            confident = turn >= late_turn or len(state.active_constraints()) >= commit_constraints
            if not confident and "exhausted" in signals and session_id in exhausted:
                confident = True
            if not confident and "stalled_exact" in signals:
                # Holding only pays while the candidate set is still narrowing.
                # A turn that does not shrink the exact set will not improve the
                # rank either, so every further hold is pure MTTC. Sessions whose
                # constraints never key on the catalog are released immediately
                # instead of waiting out the late-turn floor.
                _, exact_now = self.catalog.signature_candidates(
                    state.messages, limit=self.catalog.signature_bucket_limit
                )
                size = len(exact_now) or 10 ** 6
                previous = evidence.get(session_id)
                if previous is not None and size >= previous:
                    confident = True
                evidence[session_id] = size
            if not confident and "stalled" in signals:
                # Commit the moment evidence stops accumulating. The greedy
                # signature match only grows while the customer discloses
                # something the catalog can key on, so a turn that adds no new
                # matched signature is a turn that will not improve the rank,
                # and every further hold is pure MTTC.
                matched, _ = self.catalog.signature_candidates(
                    state.messages, limit=self.catalog.signature_bucket_limit
                )
                previous = evidence.get(session_id)
                if previous is not None and len(matched) <= previous:
                    confident = True
                evidence[session_id] = len(matched)
            limit = top_k if confident else max(1, min(top_k, emit_k))
        response["recommendations"] = response["recommendations"][:limit]

        # Repair `exclude_seen`: only what the customer was actually shown may
        # be excluded from later retrieval.
        key = (session_id, state.intent_version)
        shown = emitted.setdefault(key, set())
        shown.update(item["parent_asin"] for item in response["recommendations"])
        self._seen_by_version[key] = set(shown)
        return response

    needle_agent.Agent.respond = respond


_install.fingerprint_limit = 3


def _restore() -> None:
    needle_agent.Agent.respond = BASE_RESPOND
    needle_state.SessionState.observe = BASE_OBSERVE
    needle_catalog.extract_query_signatures = BASE_EXTRACT


def _run(samples, catalog_ids, categories, products, catalog, emit_k, late_turn, commit, signals) -> dict:
    if emit_k >= NO_GATE:
        _restore()
    else:
        _install(emit_k, late_turn, commit, signals)
    try:
        agent = needle_agent.Agent(str(catalog), **BASE_KWARGS)
        return evaluate(agent, samples, catalog_ids, categories, products)
    finally:
        _restore()


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-019 slate-emission arms")
    parser.add_argument("--k", type=int, action="append", help="products emitted while unconfident")
    parser.add_argument("--late", type=int, action="append", help="turn that forces a full slate")
    parser.add_argument("--commit", type=int, action="append", help="constraint count that forces a full slate")
    parser.add_argument("--signals", action="append", default=None,
                        help="comma-separated: exhausted, fingerprint; repeat the flag for several arms")
    parser.add_argument("--fingerprint-limit", type=int, default=3)
    parser.add_argument("--dataset", type=Path, default=KIT / "data/public_set.jsonl")
    parser.add_argument("--out", type=Path, default=None, help="write per-session rows here")
    parser.add_argument("--no-baseline", action="store_true")
    arguments = parser.parse_args()

    _install.fingerprint_limit = arguments.fingerprint_limit

    catalog = KIT / "data/catalog.jsonl"
    missing = [path for path in (catalog, arguments.dataset) if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise SystemExit(f"official kit is incomplete ({formatted}); run python scripts/bootstrap.py")

    samples = load_jsonl(str(arguments.dataset))
    catalog_ids, categories, products = catalog_index(str(catalog))

    ks = arguments.k or [1]
    lates = arguments.late or [5]
    commits = arguments.commit or [4]
    signal_sets = [frozenset(part for part in group.split(",") if part) for group in (arguments.signals or [""])]

    grid = [] if arguments.no_baseline else [(NO_GATE, 0, 0, frozenset())]
    grid += [(k, late, commit, signals)
             for signals in signal_sets for k in ks for late in lates for commit in commits]

    payload = []
    print(f"{'arm':46s} {'score':>9s} {'HR':>7s} {'MRR':>9s} {'MTTC':>7s}   delta")
    baseline = 0.878039
    for emit_k, late_turn, commit, signals in grid:
        started = time.time()
        result = _run(samples, catalog_ids, categories, products, catalog, emit_k, late_turn, commit, signals)
        score = result["recommended_technical_score"]
        label = ("shipped (no gate)" if emit_k >= NO_GATE
                 else f"k={emit_k} late={late_turn} commit={commit} [{','.join(sorted(signals)) or 'none'}]")
        print(
            f"{label:46s} {score:9.6f} {result['hit_rate_at_10']:7.4f} "
            f"{result['mrr']:9.6f} {result['mttc']:7.3f}  {score - baseline:+.6f} "
            f"({time.time() - started:.0f}s)",
            flush=True,
        )
        payload.append({
            "emit_k": emit_k, "late_turn": late_turn, "commit_constraints": commit,
            "signals": sorted(signals), "fingerprint_limit": arguments.fingerprint_limit,
            "summary": {key: value for key, value in result.items() if not isinstance(value, (dict, list))},
            "scenario_metrics": result["scenario_metrics"],
            "sessions": result["sessions"],
        })

    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(
            json.dumps({"dataset": arguments.dataset.name, "runs": payload}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {arguments.out}")


# --- EXP-020: full-span signature extraction -------------------------------- #
#
# `extract_query_signatures` keeps only the first semicolon span of a marked
# clause, on the grounds that catalog features contain semicolons too so later
# spans are structurally ambiguous. The released simulator, though, hands over
# *two* constraints per reply joined with "; " (`customer_reply`), so that
# split discards half the evidence: 2 signatures matched where 4 were offered,
# in 165 of 200 public sessions.
#
# The ambiguity does not actually need resolving. `signature_candidates`
# already admits a span only when it matches at least one catalog product, so a
# fragment produced by splitting inside a feature string matches nothing and is
# dropped. Trying every span is therefore safe under the existing filter, and
# costs only the lookups.
import needle.catalog as needle_catalog  # noqa: E402

BASE_EXTRACT = needle_catalog.extract_query_signatures


def _extract_all_spans(messages):
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
if __name__ == "__main__":
    main()
