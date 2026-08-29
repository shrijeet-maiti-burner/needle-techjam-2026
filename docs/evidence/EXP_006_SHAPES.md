# EXP-006 close, and a held-out card-shape slice

Status: EXP-006 closed as not actionable. A new held-out slice is added and
immediately rejected an arm that looked like a public gain.

## Why the public set is not a sample of the catalog

`public_set.jsonl` ships only `sample_id`, `scenario_type`, `ground_truth`,
`user_profile`, `category_bucket`, and `difficulty_bucket`. It carries no
`intent_card` and no `behavior`. Both are generated at run time from the target
product by `materialize_hidden_fields`, so every constraint the customer can
disclose is a deterministic function of the catalog row.

Running `intent_card` over all 50,000 catalog products gives four shapes:

| Constraints | Override | Products | Share |
|---|---|---:|---:|
| 4 | well-formed | 48122 | 96.24% |
| 3 | well-formed | 1150 | 2.30% |
| 3 | degenerate | 463 | 0.93% |
| 2 | degenerate | 265 | 0.53% |

Degenerate means `soft_preferences[-1] == hard_constraints[0]`, so
`behavior_for` draws `old_value` and `new_value` from the same string and the
customer retracts a preference by restating it. It follows from
`soft_preferences = cleaned[2:4] or cleaned[:1]` and therefore cannot occur on a
four-constraint card.

**All 200 public targets are the four-constraint well-formed shape.** Drawing
200 targets uniformly and seeing zero of the other three has probability about
0.0004, so the public targets were filtered to well-formed cards. Private has
800 disjoint targets and no published guarantee of that filter. Every number the
team has quoted so far describes one of the four shapes the catalog contains.

## The held-out slice

`scripts/build_shape_holdout.py` builds 200 sessions whose targets are drawn in
equal thirds from the three omitted shapes, disjoint from every public target,
at the official scenario mix and reusing public `user_profile` values so shape
is the only variable. A matched control of 200 four-constraint targets, also
disjoint from public, separates "different target" from "different shape".

| Set | n | TechnicalScore | HR@10 | MRR | MTTC | Override HR | Boundary HR | Violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| public | 200 | 0.868395 | 0.995 | 0.667984 | 2.475 | 1.000 | 1.000 | 0 |
| control, 4-constraint, disjoint targets | 200 | 0.862610 | 0.965 | 0.721367 | 2.815 | 1.000 | 1.000 | 0 |
| holdout, omitted shapes | 200 | 0.798766 | 0.875 | 0.678885 | 3.120 | 0.867 | 0.600 | 0 |

Target disjointness alone costs 0.005785. The agent is not memorizing public
targets. Card shape costs a further 0.063844.

No contract violations and no exceptions on any of the 600 sessions, so the
shapes are a scoring risk, not a safety risk.

## The cost is degeneracy, not constraint count

| Holdout shape | n | HR@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| 3 constraints, well-formed | 66 | 1.000 | 0.8500 | 2.106 |
| 3 constraints, degenerate | 66 | 0.894 | 0.6701 | 2.818 |
| 2 constraints, degenerate | 68 | 0.735 | 0.5213 | 4.397 |

Three well-formed constraints beat the four-constraint control on every metric.
Fewer constraints is not the problem. Degeneracy is, and it scales with how
degenerate the card is.

The mechanism is an information floor rather than a defect. A two-constraint
degenerate card has `cleaned` of length one, so `hard_constraints` and
`soft_preferences` are the same single string and the whole session carries one
distinguishing term. `customer_reply` filters on `value not in disclosed`, so
once that term is disclosed every later `other` returns "I don't have an
additional preference." Retrieval has one term to work with for ten turns. This
is also why holdout MTTC rises to 4.397 on that shape.

## EXP-006 is closed: targeted invalidation has nothing to fix

EXP-006 registered "does targeted versioned invalidation beat no reset and full
reset, at identical retrieval and override fixtures?". The comment in
`needle/state.py` at `_supersede_all` has stood open pending this evidence.

Split the holdout override sessions by shape:

| Holdout intent_override shape | n | Hits | HR@10 |
|---|---:|---:|---:|
| 3 constraints, well-formed | 15 | 15 | 1.000 |
| 3 constraints, degenerate | 6 | 5 | 0.833 |
| 2 constraints, degenerate | 9 | 6 | 0.667 |

Every override miss is on a degenerate card. Across all 45 well-formed override
sessions measured to date, 30 public and 15 held out, `retract_stated` hits
100%. There is no well-formed override session anywhere that targeted
invalidation could rescue.

On the degenerate sessions there is nothing to invalidate selectively: the
retracted preference and its replacement are the same string, so any policy that
distinguishes them either keeps the value or loses it, and keeping it is what
`retract_stated` already does. Traced directly:

```
messages after the override: ["I'm looking for casual shirt.",
                              "Actually, ignore my earlier preference.
                               What I need is: soft cotton blend."]
active constraints:          [("material", "cotton", positive)]
intent_version:              2
```

The stated preference clause is retracted, the subject anchor survives, and the
value is carried by the override message itself. `tests/test_degenerate_override.py`
pins that behavior.

Separately, constraint-level invalidation still has no path to the score:
nothing outside `state.py` reads `active_constraints` or `excluded_values`, and
appending active constraint values to `retrieval_text` was previously measured
byte-identical across all 200 public sessions. Targeted invalidation would need
that wiring first, and it now has no session shape to justify it.

**Decision: close EXP-006. No code change. `_supersede_all` keeps full
supersession at the override.** Reopen only if a session shape appears where a
well-formed override misses.

## Rejected arm: user profile tags in the retrieval query

`user_profile` is stored by `StateStore.reset` and read by nothing. It is the
only unused signal available, and an information-poor card is exactly the case
where extra signal might help, so it was tested rather than assumed useless.

| Arm | public | control4 | holdout |
|---|---:|---:|---:|
| off (shipped) | 0.868395 / 0.995 | 0.862610 / 0.965 | **0.798766 / 0.875** |
| always append `preference_tags` | 0.863886 / 0.975 | 0.845611 / 0.940 | 0.761811 / 0.835 |
| append only when the query is term-poor | **0.879404 / 0.995** | 0.862252 / 0.965 | 0.787435 / 0.860 |

Appending always loses on all three sets; reject.

The gated arm is the one that matters. It gains 0.011009 on public, is a wash on
the matched control, and loses 0.011331 on the holdout. That is the shape of
overfitting: it gains on the set that was used to build it and loses on the set
constructed to differ. Public alone would have scored it a free +0.011 and it
would have shipped.

**Decision: reject both. `user_profile` stays unread.** Recorded because the
gated arm is exactly the kind of change someone will propose again, and because
the holdout slice justified itself on its first use.

## Pins

- code: branch `state/exp013-question-policy` at the parent of this commit,
  clean tree, primary config `retrieval_mode=signature_first`,
  `signature_bucket_limit=100`, `popularity_strength=0.20`,
  `override_policy=retract_stated`, `exclude_seen=True`, `slate_size=10`,
  `lexical_mode=none`
- evaluator: official `local_evaluator.py`, source commit
  `34078351e1c3615e5505a2e829600b56a542e462`
- public set: sha256 `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- catalog: sha256 `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- holdout and control: regenerate with `python3 scripts/build_shape_holdout.py`
  (seed 13). Both are development artifacts under `.artifacts/`, not committed
  and not shipped.
- Python 3.12.3, macOS, stdlib only, no network, no model assets

## Caveat

The holdout is built from the released `intent_card` and `behavior_for`. If the
private set ships pre-materialized `intent_card` and `behavior` fields, which
`materialize_hidden_fields` explicitly supports by early return, then its card
shapes are whatever the organizers chose and this slice constrains them only by
analogy. The slice is evidence that the agent degrades gracefully and without
contract violations on shapes it was never tuned on. It is not a private-score
prediction.

Independent rerun owner: Shrijeet or Aryaman.
