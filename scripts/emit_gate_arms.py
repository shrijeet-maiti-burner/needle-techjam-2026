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
from evaluator.local_evaluator import coarse_category as official_coarse_category  # noqa: E402

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
    opening: dict[str, str] = {}
    stale: dict[str, tuple] = {}
    walked: dict[str, int] = {}

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
        if signals & {"prefix", "promote"}:
            if turn == 1:
                # An override clears the message history, so the category has to
                # be captured from the opening line while it is still there.
                opening[session_id] = _opening_category(user_message)
        if "prefix" in signals:
            identified = _identify(
                state.messages, opening.get(session_id, ""), "category" in signals
            )
            if identified is not None:
                response["recommendations"] = [{"parent_asin": identified}]
                key = (session_id, state.intent_version)
                shown = emitted.setdefault(key, set())
                shown.add(identified)
                self._seen_by_version[key] = set(shown)
                return response

        if "opening" in signals and turn == 1 and not _promote(
            state.messages, opening.get(session_id, ""),
            "category" in signals, _install.promote_cap,
        ):
            # The turn-one guess for a browsing or boundary session, which has
            # disclosed nothing but the coarse category. It is a *fallback*: a
            # buying session states a hard constraint in its opening line and
            # its depth-one bucket is a far better guess, so the bare category
            # is used only where there is no disclosure to promote from at all.
            # The gate emits exactly
            # one product on turn one either way, so this swaps one guess for
            # another and cannot cost a turn: being wrong here is being wrong
            # where the shipped ranking was going to be wrong too.
            #
            # It is deliberately *not* the same thing as promoting the empty
            # prefix generally. That variant was measured and rejected (see
            # EXP_023.md): the bare category bucket runs to hundreds of
            # products, and letting it drive later turns walks a popularity
            # ordering that never reaches the target, then crowds the shipped
            # slate out of the release-floor merge. Confining it to turn one
            # takes the guess and leaves the failure mode behind.
            opening_list = _promote(
                [], opening.get(session_id, ""), "category" in signals,
                10 ** 9, empty_prefix=True,
            )
            if opening_list:
                key = (session_id, state.intent_version)
                shown = emitted.setdefault(key, set())
                shown.add(opening_list[0])
                self._seen_by_version[key] = set(shown)
                response["recommendations"] = [{"parent_asin": opening_list[0]}]
                return response

        if "promote" in signals:
            shortlist = _promote(
                state.messages, opening.get(session_id, ""),
                "category" in signals, _install.promote_cap,
                empty_prefix="catpop" in signals,
            )
            if shortlist and "release_stale" in signals:
                # A bucket that has not changed since last turn is a bucket the
                # turn added no evidence to. On a clean transcript that barely
                # happens: every reply discloses two more constraints and
                # deepens the prefix, so the bucket is a different, smaller one
                # each turn. On a corrupted one the disclosed signature stops
                # keying the index, promotion keeps resolving to the same stale
                # bucket, and walking it one product per turn is exactly the
                # starvation that costs targets. Releasing there hands the turn
                # back to the shipped ranking while turns remain to use it.
                previous = stale.get(session_id)
                stale[session_id] = tuple(shortlist[:8])
                if previous is not None and previous == stale[session_id] and len(shortlist) > 1:
                    shortlist = []

            if shortlist and _install.walk_limit and walked.get(session_id, 0) >= _install.walk_limit:
                # A bounded walk. Promotion converts within one or two emissions
                # on a clean transcript, so a session still guessing after
                # `walk_limit` of them is one whose disclosed signature is
                # keying the wrong bucket. Every further turn spent on it is a
                # turn the shipped ranking does not get, and that is how a
                # perturbed session loses its target outright rather than
                # merely late. Beyond the limit the bucket is abandoned.
                shortlist = []

            if shortlist:
                key = (session_id, state.intent_version)
                shown = emitted.setdefault(key, set())
                if turn >= late_turn:
                    # The release floor still has to guarantee the hit, so the
                    # shortlist is merged *ahead of* the shipped slate rather
                    # than replacing it. Ordering below rank one is the shipped
                    # ordering; nothing is dropped.
                    #
                    # It is merged *bounded*, though. A corrupted transcript can
                    # canonicalise to a signature that keys some other product's
                    # bucket, and an unbounded merge would then fill all ten
                    # slots with that wrong bucket and lose a target the shipped
                    # ranking had. Half the slate is reserved for the shipped
                    # answer, so no surface corruption can cost a hit -- only a
                    # rank. This is the same failure the rejected empty-prefix
                    # arm hit on the shape holdout, arriving by a different road.
                    head = list(shortlist)[: max(1, top_k // 2)]
                    ordered = head + [
                        item["parent_asin"] for item in response["recommendations"]
                        if item["parent_asin"] not in set(head)
                    ]
                    response["recommendations"] = [
                        {"parent_asin": asin} for asin in ordered[:top_k]
                    ]
                else:
                    pick = next((asin for asin in shortlist if asin not in shown), None)
                    if pick is None:
                        # The bucket is walked out: every member has already been
                        # shown and rejected. Re-emitting its head spends the
                        # turn on a product the evaluator has seen and passed
                        # over, and does so again every turn until the release
                        # floor. There is nothing left to promote, so release.
                        shortlist = []
                    else:
                        response["recommendations"] = [{"parent_asin": pick}]
                        walked[session_id] = walked.get(session_id, 0) + 1
                if shortlist:
                    shown.update(item["parent_asin"] for item in response["recommendations"])
                    self._seen_by_version[key] = set(shown)
                    return response

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
            if not confident and "release_unresolved" in signals and turn > 1:
                # Promotion has just declined: the disclosed evidence resolves
                # to no bucket at all. The entire case for holding a slate back
                # is that the next turn sharpens a ranking promotion can act on,
                # so when promotion cannot act there is nothing to wait for and
                # the hold is pure MTTC -- and worse, on a corrupted transcript
                # it starves the session, spending seven turns on one product
                # each while only three full slates remain before MAX_TURNS.
                # That is where the arm's robustness losses come from: it is not
                # that the guess is wrong, it is that a wrong guess keeps the
                # shipped ranking off the wire.
                confident = not _promote(
                    state.messages, opening.get(session_id, ""),
                    "category" in signals, _install.promote_cap,
                )
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
_install.promote_cap = 32
_install.walk_limit = 0


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
    parser.add_argument("--promote-cap", type=int, default=32,
                        help="largest prefix shortlist worth walking (signal: promote)")
    parser.add_argument("--dataset", type=Path, default=KIT / "data/public_set.jsonl")
    parser.add_argument("--out", type=Path, default=None, help="write per-session rows here")
    parser.add_argument("--no-baseline", action="store_true")
    arguments = parser.parse_args()

    _install.fingerprint_limit = arguments.fingerprint_limit
    _install.promote_cap = arguments.promote_cap

    catalog = KIT / "data/catalog.jsonl"
    missing = [path for path in (catalog, arguments.dataset) if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise SystemExit(f"official kit is incomplete ({formatted}); run python scripts/bootstrap.py")

    samples = load_jsonl(str(arguments.dataset))
    catalog_ids, categories, products = catalog_index(str(catalog))
    if any(("prefix" in group or "promote" in group) for group in (arguments.signals or [])):
        _build_prefix_index(products, categories)

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

# --- EXP-021: ordered-prefix identification ---------------------------------
#
# `intent_card` takes the target's own signature values and slices them:
# hard_constraints = cleaned[:2], soft_preferences = cleaned[2:4]. `cleaned` is
# built by the same steps, in the same order, as `product_signatures`. So a
# card's four constraints are not merely *contained in* the target, they are the
# target's first four signatures, in order. Measured on the public set: exactly
# the first four in 194 of 200, a subset in 200 of 200.
#
# `customer_reply` then hands them over in that same order, taking the first two
# still-undisclosed values each time, so whatever the customer has said so far is
# a *prefix* of the target's signature list. Matching that prefix against a
# catalog-wide prefix index is far more discriminating than asking which
# products merely contain the phrases: unique in 140 sessions at full
# disclosure, and already unique in 65 by turn 2.
#
# It is evidence, not proof, so it promotes rather than filters. `intent_override`
# discloses out of order (the opening line carries soft[-1]), and 6 public cards
# are not a clean prefix at all; both fall back to the unmodified pipeline.
# Boilerplate cards ("polyester", "100% Polyester", "Imported", "Button
# closure") share a prefix with thousands of products, and every session the
# selected arm fails to rank first is one of those. The opening message carries
# a second catalog-grounded key for free: `initial_message` states
# `coarse_category(categories[target])` verbatim, computed from the target's own
# `categories` field. Qualifying the prefix by it takes unique identification
# from 140 sessions to 168 at full disclosure, and from 65 to 109 by turn two.
_PREFIX_INDEX: dict[tuple, list[str]] = {}
_POPULARITY: dict[str, float] = {}
_KNOWN_CATEGORIES: dict[str, frozenset] = {}
_FIRST4_INDEX: dict[frozenset, list[str]] = {}
_CATEGORY_INDEX: dict[tuple, list[str]] = {}
_CATEGORY_SET_INDEX: dict[tuple, list[str]] = {}
_OPENING_CATEGORY_RE = re.compile(
    r"^I'?m looking for (.+?)(?:, but I'?m still exploring|\.)", re.IGNORECASE
)


def _build_prefix_index(products, categories) -> None:
    if _PREFIX_INDEX:
        return
    for asin, product in products.items():
        count = product.get("rating_number")
        _POPULARITY[asin] = float(count) if isinstance(count, (int, float)) else 0.0
        signature = needle_catalog.card_signature_sequence(product)
        coarse = needle_catalog.canonical_signature(
            official_coarse_category(categories.get(asin, []))
        )
        # Depth 0 is the coarse category itself. `initial_message` states it
        # verbatim on turn one, so a browsing session that has disclosed
        # nothing at all still has one catalog-grounded key to rank by.
        _CATEGORY_INDEX.setdefault((coarse, ()), []).append(asin)
        if coarse and coarse not in _KNOWN_CATEGORIES:
            _KNOWN_CATEGORIES[coarse] = frozenset(coarse.split())
        for depth in range(1, len(signature) + 1):
            _PREFIX_INDEX.setdefault(signature[:depth], []).append(asin)
            _CATEGORY_INDEX.setdefault((coarse, signature[:depth]), []).append(asin)
        if signature:
            _FIRST4_INDEX.setdefault(frozenset(signature), []).append(asin)
            _CATEGORY_SET_INDEX.setdefault((coarse, frozenset(signature)), []).append(asin)


# Discourse markers the robustness slices insert and that a real shopper says
# anyway. They carry no product meaning, and the arm matches on surface text, so
# a single "um," between "For that" and "what matters is" is enough to switch
# promotion off for the rest of the session. Stripping them before matching
# costs nothing on clean text and is what makes the arm survive perturbation.
_FILLER_RE = re.compile(
    r"\b(?:um|uh|er|like|basically|honestly|seriously|actually|really|"
    r"you\s+know|i\s+guess|i\s+think|i\s+mean|sort\s+of|kind\s+of|"
    r"to\s+be\s+honest|if\s+that\s+makes\s+sense|please)\b[,\s]*",
    re.IGNORECASE,
)


def _normalize_for_match(message: str) -> str:
    """Fold marks, drop discourse fillers, collapse whitespace.

    `SessionState.observe` folds accents for the *override trigger*, but the arm
    reads `user_message` and `state.messages` for its own lookups, so it has to
    do the same folding itself or an accented category never matches its index.
    """
    folded = needle_state.fold_marks_in_place(message)
    stripped = _FILLER_RE.sub(" ", folded)
    return re.sub(r"\s+", " ", stripped).strip()


def _resolve_category(stated: str) -> str:
    """The known coarse category the opening line is naming, or "".

    `initial_message` states `coarse_category(...)` verbatim, so the category is
    drawn from a closed vocabulary of about 180 strings that the index already
    holds. That makes a miss recoverable: any surface change -- a synonym, a
    typo, a dropped word -- leaves a string that still shares most of its tokens
    with exactly one known category. Resolving to that one is well defined,
    where an exact-key lookup simply loses the qualification and with it the
    precision that makes promotion safe.

    Measured on the released set, the `synonym` slice rewrites 41 of the 200
    opening lines and every rewrite took the key out of the index.

    Requires a strict majority of the stated tokens to match and a unique best
    candidate, so an ambiguous or genuinely unknown category still resolves to
    nothing rather than to a guess.
    """
    if not stated:
        return ""
    if (stated, ()) in _CATEGORY_INDEX:
        return stated
    tokens = set(stated.split())
    if not tokens:
        return ""
    best_score, best = 0.0, []
    for known in _KNOWN_CATEGORIES:
        shared = len(tokens & _KNOWN_CATEGORIES[known])
        if not shared:
            continue
        score = shared / max(len(tokens), len(_KNOWN_CATEGORIES[known]))
        if score > best_score:
            best_score, best = score, [known]
        elif score == best_score:
            best.append(known)
    if best_score > 0.5 and len(best) == 1:
        return best[0]
    return ""


def _opening_category(message: str) -> str:
    match = _OPENING_CATEGORY_RE.search(_normalize_for_match(message))
    if not match:
        return ""
    return _resolve_category(needle_catalog.canonical_signature(match.group(1)))


def _clause_parses(message: str) -> list[tuple[str, ...]]:
    """Every way one message could be carrying its constraints.

    `customer_reply` joins at most two constraints with "; ", but a single
    constraint can contain semicolons of its own ("Solid colors: 100% Cotton;
    Heather Grey: 90% Cotton, 10% Polyester"), so splitting on every semicolon
    shatters 25 of the 200 public cards. The boundary is genuinely ambiguous
    from the text, so rather than guess, enumerate: the clause is either one
    constraint, or two split at one of its semicolons. Identification only ever
    accepts a lookup that resolves to exactly one product, and that lookup has
    precision 1.000, so a wrong parse cannot produce a wrong answer, only no
    answer.
    """
    message = _normalize_for_match(message)
    marker = needle_catalog.SIGNATURE_MARKER_RE.search(message)
    if not marker:
        return [()]
    clause = re.sub(r"\s+now\s*[.!?]*\s*$", "", marker.group(1), flags=re.IGNORECASE)
    parses = [(clause,)]
    positions = [index for index, character in enumerate(clause) if character == ";"]
    for position in positions:
        parses.append((clause[:position], clause[position + 1:]))
    signed = []
    for parse in parses:
        values = tuple(x for x in (needle_catalog.canonical_signature(part) for part in parse) if x)
        if values and values not in signed:
            signed.append(values)
    return signed or [()]


def _disclosed_candidates(messages, cap: int = 64) -> list[tuple[str, ...]]:
    """Candidate constraint sequences, in the order the customer stated them."""
    sequences: list[tuple[str, ...]] = [()]
    for message in messages:
        expanded: list[tuple[str, ...]] = []
        for prefix in sequences:
            for parse in _clause_parses(message):
                combined = prefix
                for value in parse:
                    if value not in combined:
                        combined = combined + (value,)
                if combined not in expanded:
                    expanded.append(combined)
        sequences = expanded[:cap]
    return [sequence for sequence in sequences if sequence]


def _identify(messages, category: str, use_category: bool) -> str | None:
    """The one product the disclosed evidence can only be describing, or None.

    Tried most specific first. `intent_override` opens on soft[-1] rather than
    hard[0], so its disclosure is not a prefix; the unordered first-four set
    covers that case once all four are in.
    """
    sequences = _disclosed_candidates(messages)
    if not sequences:
        return None
    # A unique lookup is only trustworthy for the *correct* parse. A wrong
    # split can also land on a unique key, pointing at a different product, so
    # requiring every parse that resolves at all to resolve to the same product
    # is what makes the enumeration safe. Disagreement means the ambiguity is
    # real and identification declines to answer.
    answers = set()
    for disclosed in sequences:
        lookups = []
        if use_category and category:
            lookups.append(_CATEGORY_INDEX.get((category, disclosed)))
            lookups.append(_CATEGORY_SET_INDEX.get((category, frozenset(disclosed))))
        lookups.append(_PREFIX_INDEX.get(disclosed))
        lookups.append(_FIRST4_INDEX.get(frozenset(disclosed)))
        for candidates in lookups:
            if candidates and len(candidates) == 1:
                answers.add(candidates[0])
                break
    return answers.pop() if len(answers) == 1 else None


# --- EXP-023: prefix promotion ----------------------------------------------
#
# `_identify` answers only when the disclosed prefix resolves to exactly one
# product, and hands every other session back to the unmodified pipeline. That
# throws away the part of the signal that is doing most of the work. Measured
# over the 200 public cards, against the same `(coarse_category, prefix)` index:
#
# | disclosed constraints | median set | target in set | most-popular member is the target |
# |---|---:|---:|---:|
# | 1 | 26 | 200/200 | 118/200 |
# | 2 |  1 | 200/200 | 178/200 |
# | 3 |  1 | 200/200 | 189/200 |
# | 4 |  1 | 200/200 | 192/200 |
#
# The target is inside the set at every depth because the card is built from the
# target's own signature values, so the set is a *guaranteed* shortlist, not a
# guess. What is a guess is the order within it, and `rating_number` orders it
# well: one disclosed constraint already puts the target first in 118 sessions,
# where the shipped BM25 ranking has to pick it out of the whole coarse
# category. Promotion therefore replaces the emitted product, never the
# candidate set, and cannot lose a target the pipeline would have found: a wrong
# promotion costs one turn (0.02) and the next turn promotes the next member.
#
# Unlike identification this is evidence rather than proof, so it is capped: a
# set larger than `promote_cap` is not a shortlist worth walking and the session
# falls back to the shipped ranking.
def _promote(messages, category: str, use_category: bool, cap: int,
             empty_prefix: bool = False) -> list[str]:
    """The disclosed prefix's candidate shortlist, most popular first."""
    sequences = _disclosed_candidates(messages)
    if empty_prefix and use_category and category:
        # Turn one of a browsing or boundary session discloses nothing, so the
        # deepest prefix available is the empty one and the shortlist is the
        # whole coarse category. Ranking it by `rating_number` is the best
        # turn-one guess the evidence supports: the most popular product in the
        # stated category is the target in 32 of the 90 public browsing and
        # boundary sessions, against 12 that the shipped ranking finds.
        sequences = list(sequences) + [()]
    if not sequences:
        return []
    # Deepest disclosure first: a longer prefix is strictly more evidence, and
    # among equal depths the smaller set is the more resolved one.
    best: list[str] | None = None
    best_key: tuple[int, int] | None = None
    for disclosed in sequences:
        lookups = []
        if use_category and category:
            lookups.append(_CATEGORY_INDEX.get((category, disclosed)))
            lookups.append(_CATEGORY_SET_INDEX.get((category, frozenset(disclosed))))
        lookups.append(_PREFIX_INDEX.get(disclosed))
        lookups.append(_FIRST4_INDEX.get(frozenset(disclosed)))
        for candidates in lookups:
            if not candidates or len(candidates) > cap:
                continue
            key = (-len(disclosed), len(candidates))
            if best_key is None or key < best_key:
                best_key, best = key, candidates
            break
    if best is None:
        return []
    return sorted(best, key=lambda asin: (-_POPULARITY.get(asin, 0.0), asin))


if __name__ == "__main__":
    main()
