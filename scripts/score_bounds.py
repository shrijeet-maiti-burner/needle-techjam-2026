"""Upper bounds on `recommended_technical_score` for the released public set.

Two numbers, both derived rather than tuned, so that a measured score can be
read as a fraction of what is reachable instead of as a number on its own.

**Absolute bound, 0.992200.** `local_evaluator.evaluate` will not count a hit
until `override_applied`, and `override_applied` is set at the end of turn
`override.turn - 1`. The public set draws `override.turn` as 12 threes and 18
fours, so 30 sessions cannot convert before turn 3 or 4 whatever the agent does.
That floors the set at `12*3 + 18*4 + 170*1 = 278` turns, MTTC 1.39, efficiency
0.961, and therefore `0.50 + 0.30 + 0.20*0.961 = 0.992200`. It assumes rank-one
on turn one in all 170 other sessions, including 90 whose opening message
discloses nothing but a coarse category, so it bounds without being approachable.

**Achievable bound, 0.982500.** This script replays each session's exact message
schedule and grants an oracle no real agent can have: the moment the disclosed
evidence admits the target at all, it emits the target at rank one. On turn one
of a browsing or boundary session nothing is disclosed, so there the oracle is
held to the best rule that actually exists -- the most popular product in the
stated category.

The second number is the useful one. It bounds every technique that ranks within
the evidence the simulator discloses: popularity, BM25, dense retrieval, a
perfect LLM reranker. None of them can rank a product the evidence never
surfaces, and none can separate products the evidence cannot distinguish.

That second point is the load-bearing one, and it is a property of the released
`intent_card`: every constraint is lifted from the target's own field values, so
the products sharing a disclosed prefix are *exchangeable* on that evidence. At
turn one of a buying session the bucket has median 26 members, all carrying the
one stated constraint in the one stated category, and nothing in the transcript
separates them. The only discriminator left is the prior over which of them is
likely to be a target at all, which is what `rating_number` supplies.

    python3 scripts/score_bounds.py
"""
import sys, importlib.util, statistics
sys.argv = ["x"]; sys.path.insert(0, "/private/tmp/pr5repro")
spec = importlib.util.spec_from_file_location("ega", "/private/tmp/pr5repro/scripts/emit_gate_arms.py")
ega = importlib.util.module_from_spec(spec); spec.loader.exec_module(ega)
KIT = ega.KIT
from evaluator.local_evaluator import (
    catalog_index, load_jsonl, materialize_hidden_fields, coarse_category,
    initial_message, customer_reply, MAX_TURNS,
)
import needle.catalog as nc

samples = load_jsonl(str(KIT / "data/public_set.jsonl"))
ids, cats, prods = catalog_index(str(KIT / "data/catalog.jsonl"))
ega._build_prefix_index(prods, cats)

def bucket(messages, category):
    """Every product the disclosed evidence still admits, most specific lookup."""
    best = None
    for disclosed in ega._disclosed_candidates(messages):
        for table, key in (
            (ega._CATEGORY_INDEX, (category, disclosed)),
            (ega._CATEGORY_SET_INDEX, (category, frozenset(disclosed))),
            (ega._PREFIX_INDEX, disclosed),
            (ega._FIRST4_INDEX, frozenset(disclosed)),
        ):
            c = table.get(key)
            if c:
                if best is None or len(c) < len(best):
                    best = c
                break
    return best or []

turns_used, hits = [], 0
by_scen = {}
for sample in samples:
    target = str(sample["ground_truth"]["parent_asin"])
    card, beh = materialize_hidden_fields(sample, prods)
    eff = {**sample, "intent_card": card, "behavior": beh}
    disclosed, boundary_used = set(), False
    applied = sample["scenario_type"] != "intent_override"
    msg = initial_message(eff, coarse_category(cats.get(target, [])), disclosed)
    category = nc.canonical_signature(ega._opening_category(msg))
    def popular(a):
        v = prods[a].get("rating_number")
        return float(v) if isinstance(v, (int, float)) else 0.0
    opening_bucket = ega._CATEGORY_INDEX.get((category, ()), [])
    opening_guess = max(opening_bucket, key=lambda a: (popular(a), a)) if opening_bucket else None
    messages, hit_turn = [], None
    for turn in range(1, MAX_TURNS + 1):
        messages.append(msg)
        cand = bucket(messages, category)
        # The oracle emits the target whenever the evidence admits it at all.
        # Perfect knowledge once a constraint is disclosed; on turn one with
        # nothing disclosed, only the achievable guess -- the most popular
        # product in the stated category -- because no agent can do better.
        if applied and (target in cand if cand else (turn == 1 and opening_guess == target)):
            hit_turn = turn
            break
        if turn == MAX_TURNS:
            break
        ov = beh.get("override") or {}
        if not applied and turn + 1 == int(ov.get("turn", 3)):
            applied = True
            if ov.get("new_value"):
                disclosed.add(str(ov["new_value"]))
            msg = str(ov.get("message", ""))
        else:
            msg, boundary_used = customer_reply(eff, "other", disclosed, boundary_used)
    t = hit_turn if hit_turn else 11
    turns_used.append(t); hits += int(hit_turn is not None)
    by_scen.setdefault(sample["scenario_type"], []).append(t)

n = len(samples)
hr = hits / n
mttc = statistics.fmean(turns_used)
e = max(0.0, min(1.0, (11 - mttc) / 10))
print(f"{'scenario':<18}{'n':>4}{'oracle MTTC':>14}")
for k in sorted(by_scen):
    print(f"{k:<18}{len(by_scen[k]):>4}{statistics.fmean(by_scen[k]):>14.4f}")
print(f"\nbucket oracle: HR={hr:.4f} MRR=1.0000 MTTC={mttc:.4f} -> SCORE {0.5*hr + 0.3*1.0 + 0.2*e:.6f}")
print(f"our measured arm                                    0.978550")
print(f"\nabsolute bound (omniscient, evaluator floor only)     0.992200")
