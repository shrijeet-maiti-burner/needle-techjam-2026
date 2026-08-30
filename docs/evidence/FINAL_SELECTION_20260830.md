# Final primary selection, 30 August 2026

Status: selected development primary; private performance remains unknown.

## Reproducibility boundary

- official source commit: `34078351e1c3615e5505a2e829600b56a542e462`
- evaluator SHA-256: `79a5ea06f9a1b8c5036f30efa85dc1f36b8f6b06eb8feb8f545dfa767bc45564`
- catalog SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- public set SHA-256: `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- selected code commit: `531ad33b`
- runtime dependencies: Python 3.10 standard library; network disabled; no model

## Selected configuration

The primary uses signature-first retrieval with bucket limit 100, fielded sparse
fallback weights `6/4/2.5/2.5/1.5/1`, soft opening-category coverage strength
`1.00`, popularity strength `0.30`, `retract_stated` override handling,
seen-item exclusion within each intent version, lexical rewrites off, and a
ten-item slate. Category coverage is a soft rerank signal; it never filters a
candidate.

## Official public result

Command:

```text
python scripts/run_experiment.py --experiment-id EXP-FINAL-PRIMARY-SELECTED --agent starter.agent:Agent --network-state disabled
```

| Metric | Result |
|---|---:|
| TechnicalScore | 0.878039 |
| HR@10 | 0.995000 |
| MRR | 0.684131 |
| MTTC | 2.235000 |
| responses | 446 |
| contract violations | 0 |

Scenario HR@10 was 1.0 for boundary, browsing, and intent override, and 0.9875
for buying. The result is an official public-development measurement, not a
private-score claim.

## Catalog-disjoint transfer proxy

`scripts/run_unseen_proxy.py` deterministically selects catalog targets that do
not occur in released ground truth, while retaining the released simulator and
marginal scenario/profile distributions. Selected target identifiers are not
written to tracked files. The proxy is a transfer diagnostic, not an estimate
of the private score.

All arms below use the same 1,000 targets and seed `20260829`.

| Arm | TechnicalScore | HR@10 | MRR | MTTC | Decision |
|---|---:|---:|---:|---:|---|
| no category, popularity 0.20 | 0.862899 | 0.964 | 0.717729 | 2.721 | control |
| category 1.00, popularity 0.20 | 0.866830 | 0.972 | 0.706367 | 2.554 | category passes |
| category 1.00, popularity 0.30 | 0.867627 | 0.972 | 0.709958 | 2.568 | select |
| category 1.00, popularity 0.55 | 0.866666 | 0.970 | 0.712488 | 2.604 | reject |

The higher popularity value reached 0.881183 on the released set but lost to
0.30 on disjoint targets, so it was rejected as public-set overfitting.

## Robustness comparison

Both arms use popularity 0.30, identical state/signature/seen controls, and the
same deterministic perturbation seed. The absolute robustness gate still
fails; the category prior is selected because it improves every compared slice
without hiding that remaining failure.

| Slice | No category | Category 1.00 | HR@10 change | Target-recall change |
|---|---:|---:|---:|---:|
| exact surface | 0.873821 | 0.878039 | 0.000 | 0.000 |
| accents | 0.735782 | 0.746239 | +0.010 | +0.010 |
| filler | 0.835421 | 0.852302 | +0.010 | +0.010 |
| paraphrase | 0.809810 | 0.831659 | +0.035 | +0.035 |
| typo | 0.782521 | 0.792330 | +0.010 | +0.010 |
| whitespace | 0.864659 | 0.866604 | 0.000 | +0.005 |
| word order | 0.863482 | 0.865589 | 0.000 | 0.000 |
| override paraphrase | 0.874013 | 0.878229 | 0.000 | 0.000 |

## Rejected profile prior

A cold-start profile-tag query improved the released score and a 1,000-target
proxy. Constraining it to preserve first-slate membership reduced the transfer
gain to `+0.000122` while increasing p50 latency by about 9 ms and p95 by about
51 ms. The runtime arm was removed completely; the selected code has no profile
ranking path.

## Packaging

A clean `git archive` of the selected source was extracted without the ignored
signature asset, combined only with the official evaluator/data, and invoked
through `python -m evaluator.local_evaluator`. The missing-asset fallback rebuilt
the index and reproduced TechnicalScore 0.878039, HR@10 0.995, MRR 0.684131,
and MTTC 2.235. No public target identifier, dataset, raw result, or generated
index is tracked.

## Decision

Select category strength 1.00 and popularity 0.30 with the existing
signature-first, seen-excluding, `retract_stated` path. Keep pure sparse with the
same safe state and priors as rollback. Do not select the profile prior,
popularity 0.55, hard negative filtering, lexical rewriting, or a model path.
