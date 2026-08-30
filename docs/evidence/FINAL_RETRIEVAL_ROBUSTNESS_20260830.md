# Clause-signature and robustness selection, 30 August 2026

Status: selected development primary; private performance remains unknown.

## Reproducibility boundary

- official source commit: `34078351e1c3615e5505a2e829600b56a542e462`
- evaluator SHA-256: `79a5ea06f9a1b8c5036f30efa85dc1f36b8f6b06eb8feb8f545dfa767bc45564`
- catalog SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- public-set SHA-256: `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- implementation lineage: `403451d`, `5a61c1a`
- runtime: Python 3.10 standard library, network disabled, no model
- contract tests: 201 passed

## Selected change

Catalog feature and detail values retain their full canonical signature and add
multi-token comma/semicolon clause signatures. Customer clauses become lookup
proposals, but only signatures present in the catalog index can affect ranking.
The selected collision gate promotes non-empty intersections of at most 500
products. FTS5 remains the fallback and catalog identity remains the only hit
condition.

Unicode combining marks are folded before sparse tokenisation and structural
parsing without removing sentence punctuation. On scoped preference overrides,
later question answers survive even if surface noise made the optional opening
subject anchor unparseable. Signature cardinalities are fetched in batches;
this is ranking-equivalent and reduces SQLite round trips.

## Official public result

Command:

```text
python scripts/run_experiment.py --experiment-id EXP-BATCHED-SIGNATURE-COUNTS --agent starter.agent:Agent --network-state disabled
```

| Metric | Previous primary | Selected |
|---|---:|---:|
| TechnicalScore | 0.878039 | 0.887527 |
| HR@10 | 0.995000 | 0.995000 |
| MRR | 0.684131 | 0.710089 |
| MTTC | 2.235000 | 2.150000 |
| responses | 446 | 429 |
| contract violations | 0 | 0 |

Selected scenario HR@10 is 1.0 for boundary, browsing, and intent override and
0.9875 for buying. This is released-development evidence, not a private result.

## Matched catalog-disjoint panels

`catalog-matched-v1` excludes every released target and matches the released
panel on rating quantile, price presence, broad category where feasible,
profile, and scenario marginals. Each seed selects 200 targets. Identifiers are
not written to tracked evidence.

| Seed | Previous primary | Clause, bucket 100 | Clause, bucket 500 |
|---|---:|---:|---:|
| 20260830 | 0.874507 | 0.885786 | 0.884987 |
| 20260831 | 0.865398 | 0.878756 | 0.886981 |
| 20260901 | 0.875573 | 0.888900 | 0.892706 |

Clause signatures improve all three panels. Bucket 500 is mixed against bucket
100 (`-0.000799`, `+0.008225`, `+0.003806`) but wins on mean transfer and raises
the released result from 0.884371 to 0.887527, so 500 is selected and 100 is the
narrower rollback gate.

## Robustness

All rows use seed `20260830` and the selected public configuration. Deltas are
against exact surface.

| Slice | HR@10 | MRR | MTTC | HR delta | target-removal rate |
|---|---:|---:|---:|---:|---:|
| exact surface | 0.995 | 0.710089 | 2.150 | - | - |
| accents | 0.995 | 0.710089 | 2.150 | 0.000 | 0.000 |
| filler | 0.995 | 0.705554 | 2.160 | 0.000 | 0.000 |
| word order | 0.995 | 0.660565 | 2.215 | 0.000 | 0.000 |
| compound paraphrase | 0.985 | 0.666165 | 2.425 | -0.010 | 0.010 |
| typo | 0.905 | 0.618657 | 3.010 | -0.090 | 0.005 |

Accent folding removes the previous 0.145 HR loss exactly. Retaining later
answers without requiring a subject anchor removes the previous filler HR loss.
Compound paraphrase is inside the registered 0.020 HR-drop gate but still has
two target removals. Typo remains an open failure.

## Rejected and retained controls

- Popularity `0.30` remains selected. On matched seeds 20260831 and 20260901 it
  scores 0.865398 and 0.875573; `0.40`, `0.50`, and `0.55` are lower on both.
- Public bucket sweep scores: 25 = 0.879522, 50 = 0.884998, 100 = 0.884371,
  200 = 0.886558, 500 = 0.887527. Only 500 was advanced to matched panels.
- Fractional clause coverage, complete-clause coverage, reciprocal-rank fusion,
  and full category promotion failed their public controls and were removed.
- A unique one-edit catalog typo index leaves typo HR and MRR unchanged while
  adding memory and code. It was removed.
- Indexing every material in a blended value improves paraphrase MRR but loses
  0.001571 publicly and regresses two of three matched panels. It was removed.
- Filtering pure no-preference turns clears the focused paraphrase gate but
  loses 0.002277 publicly and regresses two of three matched panels. It was
  removed.
- Popularity-only retuning, hard negative filtering, profile priors, lexical
  expansion, and model reranking remain rejected or disabled as recorded in the
  earlier evidence files.

## Resources and clean packaging

The schema-v2 index contains 869,240 rows, is 49,860,608 bytes, and has SHA-256
`646fcd647a2a78cf00daf7998edd6d7c57c8a4d87000f1b888685b2e4864de9c`.

| Check | Result |
|---|---:|
| isolated response latency p50 / p95 / p99 / max | 96.5 / 203.8 / 238.3 / 281.1 ms |
| construction with bundled index | 5.125 s |
| construction without index | 40.614 s |
| construction peak working set, bundled / source-only | 196,231,168 / 263,766,016 bytes |
| complete evaluator peak working set, bundled | 423,079,936 bytes |
| verified release layout | 76 files, 50,221,823 bytes |

A clean `git archive` without the ignored asset rebuilds in process and
reproduces 0.887527. A second clean archive with the generated index placed at
`submission/assets/catalog-signatures.sqlite3` is auto-detected by
`starter.agent.Agent`, emits no stderr, and reproduces the same score. The asset
is a startup optimisation; catalog hash mismatch still falls back safely.

## Decision

Select schema-v2 clause signatures, bucket 500, Unicode-stable parsing,
subject-anchor-independent retention of later answers, batched cardinality
lookups, and automatic bundled-asset discovery. Retain pure sparse as the
architecture rollback and bucket 100 as the narrower signature gate. Do not
claim typo robustness, private performance, or a winning result.
