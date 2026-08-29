# EXP-002/003/007/016 preregistration

Registered: 29 August 2026, before running the new retrieval arms.

## Fixed controls

- Official evaluator, catalog, and public-set pins remain those in
  [`H0_CONTROL.md`](H0_CONTROL.md).
- H0 integrated control is the sparse `OR` query, field weights
  `6/4/2.5/2.5/1.5/1`, no popularity prior, slate size 10, and no seen-item
  exclusion.
- Every arm retains repeated `other`, the same state implementation, the no-op
  semantic boundary, and the strict response validator.
- Raw outputs stay ignored. A reviewed summary records every arm, including
  negative results.

## Arms

1. EXP-002: sparse control versus bounded signature-first promotion at bucket
   limits 10, 50, and 100. The sparse fallback is never removed.
2. EXP-003: fixed slate sizes 1, 3, 5, and 10 under identical ranking, plus
   sequential unseen rank one.
3. EXP-007: the official field weights versus a title/category-heavy arm and a
   feature/details-heavy arm. `OR` remains the control; `AND` is a brittleness
   diagnostic.
4. EXP-016: no prior versus bounded log-popularity strengths 0.02, 0.05, 0.10,
   and 0.20 over the same candidate pool. No arm may remove a low-volume item.

## Decision thresholds

- A primary candidate needs at least `+0.005` TechnicalScore over its immediate
  fixed control on the 200 public sessions.
- Aggregate HR@10 may not regress. Buying or Browsing HR may not regress by
  more than `0.025`; Intent Override may not regress by more than one session
  (`0.033334`); Boundary may not regress by more than one session (`0.10`).
- Contract violations must remain zero. Startup, evaluation time, and traced
  Python memory are recorded for every arm; a feature exceeding 2x the H0
  control on any one measure is rejected unless a narrower follow-up removes
  the excess.
- Signature promotion must retain the target whenever all matched signatures
  come from that target, activate on at least 25% of public sessions, and have
  median activated bucket size at most 10. Case, punctuation, whitespace, and
  Unicode-normalization perturbations may not change its bucket.
- The popularity prior is rejected if the low-volume public-target slice loses
  any hit relative to the same retriever without the prior.
- A slate policy is not accepted merely for higher MRR. It must pass the full
  TechnicalScore and slice gate; first-hit lock-in cases are reported.
- Ties are broken by robustness, reproducibility, simplicity, and then public
  aggregate, in that order.

These thresholds select among public-development candidates. They do not
estimate private performance or guarantee a judging outcome.
