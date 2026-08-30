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

Measured first at the pre-#11 primary, which is what the narrative below was
written against, and rerun at the current one. The current primary adds the
soft category prior at 1.00 and popularity at 0.30.

| Set | n | pre-#11 | current primary | HR@10, current |
|---|---:|---:|---:|---:|
| public | 200 | 0.868395 | 0.878039 | 0.995 |
| control, 4-constraint, disjoint targets | 200 | 0.862610 | see below | |
| holdout, omitted shapes | 200 | 0.798766 | 0.818531 | 0.905 |

The 200-session control is superseded by six 600-session draws of the same
construction, which average 0.861734 at HR@10 0.9678 under the current primary.
So target disjointness costs about 0.016 and card shape a further 0.043. The
agent is not memorising public targets, and the shape gap narrowed under #11
without closing.

No contract violations and no exceptions on any of the sessions in either
measurement, so the shapes are a scoring risk, not a safety risk.

## The cost is degeneracy, not constraint count

Current primary, with the pre-#11 HR in the last column for comparison:

| Holdout shape | n | HR@10 | MRR | MTTC | HR, pre-#11 |
|---|---:|---:|---:|---:|---:|
| 3 constraints, well-formed | 66 | 1.000 | 0.7856 | 2.030 | 1.000 |
| 3 constraints, degenerate | 66 | 0.909 | 0.7122 | 2.758 | 0.894 |
| 2 constraints, degenerate | 68 | 0.809 | 0.5406 | 3.794 | 0.735 |

Three well-formed constraints beat the four-constraint control on every metric.
Fewer constraints is not the problem. Degeneracy is, and it scales with how
degenerate the card is. The ordering is unchanged by #11, which lifted the two
degenerate shapes without touching the well-formed one.

The mechanism is an information floor rather than a defect. A two-constraint
degenerate card has `cleaned` of length one, so `hard_constraints` and
`soft_preferences` are the same single string and the whole session carries one
distinguishing term. `customer_reply` filters on `value not in disclosed`, so
once that term is disclosed every later `other` returns "I don't have an
additional preference." Retrieval has one term to work with for ten turns. This
is also why holdout MTTC is worst on that shape, 3.794 against 2.030 for the
well-formed one.

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

The split is identical under the current primary and the pre-#11 one, so #11
changed which items rank where without changing which override sessions are
winnable.

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

## `popularity_strength` under the #11 primary

This is the transfer evidence for EXP-016, whose register entry names Shrijeet
as owner and Athul as reviewer. It is a review, not a retrieval decision.

#11 selected popularity 0.30 with the new category prior, on a 1,000-target
disjoint proxy where 0.30 beat 0.20 by 0.000797. That proxy takes catalog
targets disjoint from released ground truth with no shape filter, so it is about
96% four-constraint by construction: it controls target identity, not card
shape. The slice in this document is the only one that varies shape, and the two
disagree.

Swept at the current primary, so the category prior is active in every arm. Six
600-session controls from `build_shape_holdout.py --control` at seeds 29, 13, 5,
17, 41, 97, plus public and the omitted-shape holdout.

| strength | public | shapes | s29 | s13 | s5 | s17 | s41 | s97 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.00 | 0.861027 | **0.842421** | **0.857272** | 0.858367 | **0.860939** | **0.865463** | 0.866541 | **0.870130** |
| 0.10 | 0.869263 | 0.834755 | 0.856077 | 0.859466 | 0.859309 | 0.863990 | 0.866664 | 0.867964 |
| 0.20 | 0.875803 | 0.826462 | 0.856894 | **0.860651** | 0.858990 | 0.863254 | 0.868493 | 0.864545 |
| 0.30 (shipped) | **0.878039** | 0.818531 | 0.855953 | 0.858137 | 0.858134 | 0.865286 | **0.869943** | 0.862949 |

Public at 0.30 reproduces #11's selected result exactly, 0.878039 at HR@10
0.995, which is what licenses comparing the rest.

Paired, 0.30 minus 0.00:

| set | n | mean | 95% bootstrap | worse / better | sign test |
|---|---:|---:|---|---|---:|
| shapes holdout | 200 | **-0.023890** | **[-0.043017, -0.008474]** | 46 / 15 | p 0.00009 |
| pooled controls | 3600 | -0.001385 | [-0.004096, +0.001193] | 624 / 473 | p 0.00001 |
| public | 200 | +0.017012 | [-0.000159, +0.034148] | 38 / 71 | p 0.00203 |

**On the omitted-shape holdout, 0.30 costs 0.023890 against 0.00, with an
interval that excludes zero.** That is the one comparison here whose size, and
not merely direction, is established. The holdout falls monotonically as the
prior rises while public rises monotonically, which is the same opposed-gradient
signature that rejected the profile-tag arm above, at twice the magnitude.

On the six controls the direction is the same at every step, 0.10 over 0.00 at
p 0.00268, 0.20 over 0.10 at p 0.00047, 0.30 over 0.20 at p 0.02098, and 0.30
over 0.00 at p 0.00001, but no interval on the mean excludes zero. Set totals
disagree about which value ranks first, which is exactly why #11's +0.000797
from a single draw should not be read as a preference for 0.30: that margin is
about half of one standard error at that sample size.

The cost concentrates where information is scarcest. Dropping the prior to 0.00
lifts the two-constraint degenerate slice from HR 0.809 to 0.868 and its
override sessions from 6 of 9 to 7 of 9, while the well-formed shape stays at
1.000 either way. A card with one distinguishing term leaves retrieval little to
rank on, so a popularity prior decides the slate on that shape.

The category prior itself passes this slice comfortably, and that is worth
recording separately: at matched popularity 0.20 it moves the holdout from
0.798766 to 0.826462, and at 0.00 from 0.802804 to 0.842421. It gains more the
lower the popularity prior is set.

**Recommendation to EXP-016's owner: lower `popularity_strength`.** 0.00 is
first or tied on the holdout and on four of six controls, and it costs 0.017012
on public, which is the set with the known filter. The decision, and any value
between 0.00 and 0.10, belongs to Shrijeet.

## Pins

- code: the shape and EXP-006 sections were measured pre-#11 at
  `popularity_strength=0.20` with no category prior, and rerun at the current
  primary: `retrieval_mode=signature_first`, `signature_bucket_limit=100`,
  `category_strength=1.00`, `popularity_strength=0.30`,
  `override_policy=retract_stated`, `exclude_seen=True`, `slate_size=10`,
  `lexical_mode=none`. Both are stated wherever they differ.
- popularity sweep: 32 runs at the current primary with only
  `popularity_strength` varying, per-session rows retained. The sweep calls the
  official `evaluate()` directly and so records no contract-violation count; the
  contract evidence is the zero-violation runs recorded above, not these.
- evaluator: official `local_evaluator.py`, source commit
  `34078351e1c3615e5505a2e829600b56a542e462`
- public set: sha256 `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- catalog: sha256 `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- holdout: regenerate with `python3 scripts/build_shape_holdout.py` (seed 13).
- controls: the same script with `--control --count 600` at seeds 29, 13, 5, 17,
  41, 97. Datasets and sweep payloads are development artifacts under
  `.artifacts/`, not committed and not shipped.
- Python 3.12.3, macOS, stdlib only, no network, no model assets

Reproduce the sweep with:

```bash
python3 scripts/popularity_sweep.py --seeds 29 13 5 17 41 97 --count 600 \
    --strengths 0.00 0.10 0.20 0.30 \
    --extra-dataset .artifacts/participant-kit/techjam-conversational-search/data/public_set.jsonl \
    --extra-dataset .artifacts/holdout/shapes.jsonl \
    --output .artifacts/sweeps/popularity-category.json
python3 scripts/analyze_sweep.py .artifacts/sweeps/popularity-category.json
```

About 35 minutes for the 32 runs, stdlib only, no network.

## Caveat

The holdout is built from the released `intent_card` and `behavior_for`. If the
private set ships pre-materialized `intent_card` and `behavior` fields, which
`materialize_hidden_fields` explicitly supports by early return, then its card
shapes are whatever the organizers chose and this slice constrains them only by
analogy. The slice is evidence that the agent degrades gracefully and without
contract violations on shapes it was never tuned on. It is not a private-score
prediction.

Independent rerun owner: Shrijeet or Aryaman.
