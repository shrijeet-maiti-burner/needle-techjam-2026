# Safe adaptive identification selection, 30 August 2026

Status: selected final development primary. Private performance remains unknown.

## Reproducibility boundary

- official source commit: `34078351e1c3615e5505a2e829600b56a542e462`
- evaluator SHA-256: `79a5ea06f9a1b8c5036f30efa85dc1f36b8f6b06eb8feb8f545dfa767bc45564`
- catalog SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- public-set SHA-256: `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- runtime: Python 3.10, standard library only, network disabled, no model
- contract tests: 292 passed

## Selected mechanism

The official simulator derives a card from the target product's metadata and
discloses up to four cleaned values in order. The production path uses that
structure only when the evidence is safe:

1. the opening request must yield an explicit normalized category;
2. a category plus ordered disclosure prefix, or category plus complete
   unordered disclosure, must map to exactly one product across the catalog;
3. every plausible semicolon parse that resolves must agree on that product;
4. ordered-prefix lookup is disabled after intent revision;
5. unordered lookup requires four disclosure positions, preventing a partial
   target prefix from matching another product's complete short card.

The index stores only globally unique category-bound keys. Keys are SHA-256
digests of canonical category and disclosure tuples; no public labels or target
identifiers are inputs to construction. When the checks decline, the existing
bounded signature and FTS5 ranker remains in control.

Before turn 5 and before four active constraints, the agent emits only its
rank-one item. It releases the full slate afterward. Only emitted items enter
seen-item exclusion. Catalog-derived one-edit recovery is restricted to the
explicit opening category and disclosure clauses; arbitrary free text is not
rewritten.

## Official public result

```text
python scripts/run_experiment.py --experiment-id FINAL-SAFE-V5-PUBLIC --agent starter.agent:Agent --network-state disabled
```

| metric | result |
|---|---:|
| TechnicalScore | 0.955233 |
| HR@10 | 0.995000 |
| MRR | 0.967778 |
| MTTC | 2.630000 |
| responses | 525 |
| contract violations | 0 |

The one public miss is in the buying slice. Boundary, browsing, and intent
override HR@10 are 1.0. This is released-development evidence, not a private
result.

## Catalog-disjoint transfer

`catalog-matched-v1` excludes all 200 released targets and preserves the
released scenario marginals while matching target-popularity and catalog
eligibility properties. Each seed selects 200 different targets.

| seed | TechnicalScore | HR@10 | MRR | MTTC | violations |
|---|---:|---:|---:|---:|---:|
| 20260830 | 0.961692 | 1.000 | 0.980972 | 2.630 | 0 |
| 20260831 | 0.952900 | 0.985 | 0.978333 | 2.655 | 0 |
| 20260901 | 0.947439 | 0.990 | 0.957798 | 2.745 | 0 |

These panels argue against direct released-target memorisation. They still use
our sampler and the released simulator, so they are not private-score
estimates.

## Wrong-identification audit

`scripts/audit_identification.py` instruments every non-null direct lookup and
compares it with evaluator ground truth. On all released sessions and the exact
schema-v5 asset it records 179 calls, 179 correct, and zero wrong. This audit
found and removed an earlier unsafe partial-set implementation; the historical
EXP-021 wrapper result must not be used as the runtime safety claim.

## Robustness

The full registered seed-0 matrix was run without weakening its zero-removal
threshold. Ten of thirteen meaning-preserving slices have zero target removal.
The remaining failures are explicit:

| slice | HR@10 | MRR | MTTC | target-removal rate |
|---|---:|---:|---:|---:|
| exact | 0.995 | 0.967778 | 2.630 | - |
| paraphrase | 0.990 | 0.888790 | 3.145 | 0.005000 |
| typo | 0.990 | 0.951562 | 2.905 | 0.005000 |
| word order | 0.990 | 0.933298 | 2.945 | 0.005348 |
| attribute swap | 0.935 | 0.797415 | 3.800 | 0.055000 |
| constraint drop | 0.955 | 0.899810 | 3.090 | 0.040000 |

Attribute swap and constraint drop are meaning-changing card edits; their
failures remain relevant because the registered gate also requires target
retention after those edits. Casing, whitespace, punctuation, accents,
synonym, filler, politeness, contraction, number format, override paraphrase,
and negation have zero target removal. No claim of complete robustness is made.

## Asset and rollback

The schema-v5 asset contains 869,240 exact-signature pairs and 162,190 globally
unique card keys. It is 57,683,968 bytes with SHA-256
`c3142af7d33e2ef1b6eaca66d112d6a372b5cf47546883aa6bfc4916d058b5c2`.
It is bound to the catalog hash above. A missing, corrupt, or mismatched asset
falls back to an equivalent in-process build rather than aborting agent
construction.

An isolated bundled run records 7.561s construction, 21.336s evaluation,
509,960,192 bytes peak process working set, and response latency p50/p95/p99/max
of 31.2/106.7/131.6/478.7 ms. The allowlisted release builder excludes the
participant kit, datasets, evaluator, caches, results, and secrets; the verified
21,357,204-byte zip has SHA-256
`b2b998b1a61aa63fb52f8f23f4dca66b0a8bc76cd6dd3db52b188716dcc7d196`
and reproduces 0.955233 through the unmodified official evaluator with zero
stderr.

The source-only fallback also reproduces 0.955233, but construction takes
83.755s and the full run peaks at 608,514,048 bytes. The bundled index is
therefore the release path; source-only is survivability, not the preferred
deployment.

The rollback remains the pure-sparse preset. Direct identification, adaptive
emission, and structured correction are separate constructor controls and can
be disabled without changing the public response contract.

## Decision

Select the category-bound unique-key path, parse agreement, post-override
ordering guard, full-disclosure unordered guard, adaptive slate, and
structured correction. Reject the earlier unconstrained partial-set lookup.
Carry the five registered robustness failures into the final limitations; do
not convert public or proxy measurements into a private-score or winning claim.
