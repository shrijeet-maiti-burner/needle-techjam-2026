# Architecture

## Decision boundary

The code currently implements only the minimum fields and behavior needed for a valid end-to-end run. Detailed confidence, provenance, ambiguity, cluster, and trace contracts are target architecture. They do not need to exist by H6 unless a running experiment consumes them.

```text
official evaluator
      |
starter.agent.Agent
      |
versioned state -> bounded signature promotion -> fielded sparse fallback
       -> soft category/popularity rerank -> seen exclusion
       -> no-op semantic boundary -> strict response
```

## Stable H6 interfaces

- `StateStore.reset/observe` owns session lifecycle and raw active-intent history.
- `CatalogIndex.search` returns ordered catalog-valid `Candidate` values.
- `NoOpSemanticReranker.rerank` proves the optional stage can be bypassed without failure.
- `Agent.respond` owns the public contract, ten-item cap, deterministic message, and assembly.

The repeated-`other` action is selected for the released simulator because it
returns up to two undisclosed constraints regardless of type. It remains an
evaluator-specific control rather than a claim that real customers should only
receive generic questions. The original FTS weights are retained because both
measured alternatives failed their gates.

## Current measured candidate

The development and submission adapters use the immutable primary preset:

- versioned state that retracts the stated opening preference while preserving later answers on a scoped preference override;
- exact full-value and clause-level catalog-signature promotion only for non-empty buckets of at most 500;
- sparse `OR` fallback with weights `6/4/2.5/2.5/1.5/1`;
- soft opening-category coverage strength 1.00 and popularity strength 0.30;
- seen-item exclusion within each intent version and a ten-item slate;
- Unicode diacritic folding at token and structural-parser boundaries;
- lexical expansion, fuzzy typo matching, and model reranking disabled.

The pure sparse preset is the rollback and retains the selected safe state and
soft priors. The optional signature asset is catalog-bound by SHA-256. If it is
missing, corrupt, or bound to another catalog, construction records the reason
and rebuilds the equivalent in-memory index rather than aborting the run.

The selected primary measures TechnicalScore 0.887527 on the released set.
Three distribution-matched 200-target panels disjoint from released targets
score 0.884987, 0.886981, and 0.892706. Source-only and asset-bundled clean
archives reproduce 0.887527. Accent and filler slices preserve HR@10 exactly;
compound paraphrase loses 0.010 HR and typo loses 0.090 HR. This remains
development evidence rather than a private-performance claim.

A second proxy varies card shape rather than target identity, drawing targets
from the three `intent_card` shapes the released set never contains. It exposes
a different failure surface and disagrees with released-set tuning of
`popularity_strength` (docs/evidence/EXP_006_SHAPES.md). These proxies are
development diagnostics, not private-score estimates.

## Next experiment-driven extensions

1. EXP-013 is closed: question specificity was measured across ten arms and every alternative to repeated `other` lost (docs/evidence/EXP_013.md). EXP-014 may still test later-rank cluster coverage, but only behind the selected deterministic path.
2. Robustness work targets general normalization and retrieval invariants; more released-template phrase patches are not acceptable evidence.
3. Any optional model must beat the no-op and lexical controls on released score, disjoint targets, perturbation slices, license, offline startup, latency, memory, disk, and clean packaging.
4. Final release work rebuilds the optional asset from the exact scoring catalog and repeats the clean extracted-bundle command.

## Invariants

- exact `parent_asin` identity is the only hit condition;
- recommendations are ordered, unique, catalog-valid objects and never exceed ten;
- `reset` isolates sessions and `respond` requires a prior reset;
- final scoring never requires network access, credentials, a hosted service, or an optional model;
- experiment diagnostics cannot mutate official labels, evaluator logic, or production responses;
- a faithful trace may describe executed behavior but never change ranking.
