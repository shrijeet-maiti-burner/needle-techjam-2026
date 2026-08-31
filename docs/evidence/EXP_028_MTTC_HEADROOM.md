# EXP-028 where the remaining public score is, and why it is not reachable

Status: measured, negative. No code change. Written so nobody spends the rest
of the window re-deriving it.

## Registered question

"We are at 0.978500 against a protocol-conditioned oracle of 0.982500. Where is
the 0.004, and is any of it reachable?"

Answer: it is almost entirely turn-1 MTTC, and it is not reachable without
leaning harder on a public-set sampling artefact that five prior experiments
already measured as losing on held-out data.

## Where the turns are

`TechnicalScore = 0.50*HR@10 + 0.30*MRR + 0.20*Efficiency`, so one turn of MTTC
is worth `0.20/10 = 0.02` across the set, and HR is already saturated.

| scenario | n | our MTTC | oracle MTTC | gap |
|---|---:|---:|---:|---:|
| buying | 80 | 1.5000 | **1.0000** | 0.50 |
| browsing | 80 | 1.8000 | 1.6375 | 0.16 |
| boundary | 10 | 2.5000 | 2.4000 | 0.10 |
| intent_override | 30 | 3.8667 | 3.8333 | 0.03 |

`first_hit_turn` distribution:

| scenario | t1 | t2 | t3 | t4 | t5 |
|---|---:|---:|---:|---:|---:|
| buying | 46 | 30 | 3 | 0 | 1 |
| browsing | 29 | 41 | 8 | 1 | 1 |
| boundary | 3 | 0 | 6 | 1 | 0 |
| intent_override | 0 | 0 | 5 | 24 | 1 |

MRR contributes almost nothing: 199 of 200 sessions are rank 1, and the single
exception (`public_0020`, rank 3) is recorded elsewhere as unrecoverable in
every configuration tried. Closing it is worth 0.001.

## Three levers checked and closed

**The question policy is already optimal, and cannot be improved.** The agent
asks `other` on every turn. In `customer_reply`, `attribute == "other"` disables
the classification filter entirely, so it returns the first two undisclosed
constraints whatever they are. Any specific attribute is a subset of that, so
`other` weakly dominates every alternative. Replayed over the full set: 175
questions asked, 162 answered with a disclosure, and only **6 turns across 4
sessions** produced a reply that disclosed nothing, all of them where the card's
constraints were already exhausted. There is no waste to recover. This
independently reconfirms EXP-013 at the current primary.

**Emitting more at turn 1 loses.** Holding pays whenever it converts a mid-slate
hit into a rank-1 hit, and the arithmetic is fixed: a turn is worth 0.02, moving
rank 2 to rank 1 is worth `0.30 * 0.5 = 0.15`. Emitting the full slate at turn 1
only breaks even if the target is already rank 1, which is what `emit_k=1`
already does. The oracle's buying MTTC of 1.0000 says the target is inside our
turn-1 top ten in all 80 buying sessions; it is at rank 1 in 46. Taking the
other 34 by widening the slate would cost roughly 0.034 of MRR to buy 0.004 of
efficiency.

**Turn-1 emission is already saturated, in every scenario.** This is the
decisive measurement, and it is built from `local_evaluator.intent_card`
directly rather than from needle's re-implementation of it, because the whole
conclusion rests on it. A catalog product is a plausible target at turn 1
exactly when the card the evaluator would build for it opens with the value the
customer disclosed, in the same coarse category. Validation: the target is
inside that pool in **80 of 80** buying sessions, as it must be.

| scenario | pool | target is most-rated in pool | **we hit at turn 1** | uniform-sampling expectation |
|---|---|---:|---:|---:|
| buying | same first card value, median 24 | **46 / 80** | **46** | 12.2 |
| browsing | whole coarse category, median 173 | **29 / 80** | **29** | 1.7 |
| boundary | whole coarse category, median 330 | **3 / 10** | **3** | 0.1 |

We reach the ceiling exactly, in all three. Not approximately: the shipped agent
picks the target at turn 1 in precisely the sessions where the target is the
most-rated member of a set of products the customer has given us no way to tell
apart, and in no others.

The last column is what that ceiling is made of. If targets were drawn uniformly
from eligible products, turn 1 would land about 14 times across the 170
non-override sessions. It lands 78. The public set's targets are drawn from the
popular tail by roughly five and a half times, and the entire turn-1 hit rate
above 14 is that draw, not retrieval skill.

**Nothing else separates them.** Nine catalog-side orderings, scored inside the
buying pools:

| ordering | turn-1 top-1 | MRR within pool |
|---|---:|---:|
| `rating_number` (shipped) | **46** | **0.6989** |
| `rating_number` x `average_rating` | 46 | 0.6979 |
| log `rating_number` x `average_rating` | 44 | 0.6867 |
| price, low first | 25 | 0.4858 |
| features count | 23 | 0.4167 |
| price, high first | 22 | 0.4436 |
| card values, most first | 17 | 0.3411 |
| title length, short first | 13 | 0.2492 |
| `average_rating` | 10 | 0.2598 |

Nothing beats what is shipped, and the two that tie on top-1 are worse on MRR.
The remaining 34 buying sessions are ones where the target is not the most-rated
member of an otherwise identical set, and no ordering over catalog fields finds
them.

**The pool is exchangeable, so the rest is not rankable.** For buying,
the opening message discloses exactly one constraint, `hard_constraints[0]`.
Counting catalog products that share the target's `(coarse category, first
signature value)` key, which is every piece of evidence the customer has given
by turn 1:

```
buying sessions                            80
products sharing the target's turn-1 key   median 24, mean 65.9, max 1004
key is unique to the target                 7
two or more indistinguishable              73
```

Only **7 of 80** turn-1 answers are determined by the evidence. We get 46 right.
The extra 39 come from popularity ordering, and the public targets are drawn
from the popular tail (median `rating_number` 6846 against a catalog median of
12, and 3 on the shape holdout). So we are already extracting substantially more
from turn 1 than the disclosed evidence supports, and the remaining 34 are
available only by leaning harder on that artefact.

## Why that is the end of the road

Every route into the exchangeable set has been measured and rejected:

| attempt | result | record |
|---|---|---|
| stronger `popularity_strength` | +0.017 public, -0.024 shape holdout | EXP_006_SHAPES |
| gated user-profile prior | +0.011 public, -0.011 holdout | EXP_006_SHAPES |
| public-set popularity re-read | public set cannot judge it at all | EXP_022 |
| catalog-only target propensity model | +0.0004, regresses 2 of 3 disjoint panels | EXP_024 |
| promotion-release arms | regressed clean MRR | EXP_025 |
| `early_slate_size` 2 and 3 | -0.020 and -0.032 clean | EXP_010 final |

Five independent attacks on the same set, every one a public-set gain that
inverts on held-out data. That is the signature of an artefact, not of an
unexploited signal.

## What a higher published score would have to be made of

Worth stating in full, because "someone will post 0.99" is a reasonable worry
and it is answerable with arithmetic rather than with reassurance.

The evaluator floors MTTC by itself. `override_applied` gates the hit check, and
it only flips one turn before the override message arrives, so an
`intent_override` session cannot hit before turn 3 or 4 no matter what the agent
does. Measured on the released set: **12 sessions floor at turn 3, 18 at turn
4.** With every other session hitting at turn 1, the minimum possible total is
`170 + 12*3 + 18*4 = 278` turns, MTTC 1.3900.

| | MTTC | score | what it requires |
|---|---:|---:|---|
| absolute ceiling | 1.3900 | **0.992200** | already knowing the target |
| protocol oracle | 1.7500 | **0.982500** | perfect play on disclosed evidence only |
| us, shipped | 2.0250 | **0.978500** | |

Nobody can exceed 0.992200. That is a property of the released evaluator, not an
estimate.

The interesting number is the second one. 0.982500 is the best score reachable
by an agent that uses only what the customer has actually said, because by turn
1 the target is one of a median 24 products that are identical on the disclosed
evidence. **The band between 0.982500 and 0.992200 is not a skill gap. It is the
leakage region**, and the only way into it is to already know which of those 24
is the answer, which on the released set means having fitted the 200 published
targets.

So a published score in the high 0.98s or above is not evidence of a better
method. It is evidence of fitting a set whose targets are drawn from the popular
tail by a factor of about five and a half, and that fit is what the private run
removes.

## What predicts the private run instead

| set | target `rating_number`, median | our score |
|---|---:|---:|
| public, released | 6846 | 0.978500 |
| target-disjoint control, seed 13 | catalog-like | 0.954701 |
| target-disjoint control, seed 29 | catalog-like | 0.944155 |
| omitted-shape holdout, adversarial | **3** | 0.919400 |

Catalog median is 12. The released targets are roughly 570 times more rated than
a typical catalog product, which is the artefact stated as a number.

We expect to score meaningfully below 0.978500 on a set we have not seen, and
these three are the estimate. An agent whose public score comes from fitting the
released targets has no equivalent number and a much larger fall, because the
whole of its margin above 0.982500 is the part that does not transfer.

This is reasoning about the benchmark's arithmetic, not intelligence about any
other team. What it supports is a decision, not a prediction: do not trade
holdout transfer for released-set score, at any exchange rate, this late.

## Conclusion

0.978500 is at 99.6% of the protocol-conditioned oracle, and the remaining
0.004 is turn-1 rank among products the customer has given us no way to tell
apart. It is reachable only by fitting the public set's sampling, which costs
more on every disjoint panel we hold. Recommend spending the remaining window
on the private-run risks instead: packaging, reproduction, and contract safety.

## Reproduction

The replay harness mirrors `local_evaluator.run` exactly, including
`initial_message`, `normalize_recommendations` and the override injection, and
labels each customer reply.

Pins: base `64e2158`, official `local_evaluator.py` at source commit
`34078351e1c3615e5505a2e829600b56a542e462`, Python 3.12, macOS, stdlib only.
