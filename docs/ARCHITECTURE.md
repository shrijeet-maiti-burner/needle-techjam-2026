# Architecture

This document records the detailed source architecture. The condensed technical
report is [`submission/REPORT.md`](../submission/REPORT.md), which also ships in
the submission archive.

## Decision boundary

The line that held all the way through: nothing outside the scored path may
change a scored response. Confidence, provenance, clarification ranking,
explanations, translation and the multi-item planner all exist now, and every
one of them is downstream of, or beside, the ranking rather than inside it. The
guard is mechanical rather than cultural: a test walks the import graph from the
entry point and fails if a scored module reaches the interface layer.

```text
official evaluator
      |
starter.agent.Agent
      |
versioned state -> safe category-bound disclosure ranking/identification
       -> bounded signature retrieval -> fielded sparse fallback
       -> soft category/popularity rerank -> adaptive slate + seen exclusion
       -> no-op semantic boundary -> strict response
```

Beside that path, and reaching none of it: `needle/questions.py` ranks the
catalog facet worth asking a person about, `needle/explain.py` writes the
customer-facing sentence from the state that produced the turn,
`needle/language.py` answers in the language the customer wrote in, and
`storefront/` is the multi-item journey interface. It adds typed catalog-property
filters and explicit numeric ordering over a catalog-derived category pool;
those operations are confined to the labelled product surface. The scored
`ask_attribute` and the scored ranking are untouched by all four.

## Stable interfaces

- `StateStore.reset/observe` owns session lifecycle and raw active-intent history.
- `CatalogIndex.search` returns ordered catalog-valid `Candidate` values.
- `NoOpSemanticReranker.rerank` proves the optional stage can be bypassed without failure.
- `Agent.respond` owns the public contract, ten-item cap, deterministic message, and assembly.

The repeated-`other` action is selected for the released simulator because it
returns up to two undisclosed constraints regardless of type. It remains an
evaluator-specific control rather than a claim that real customers should only
receive generic questions. The original FTS weights are retained because both
measured alternatives failed their gates.

## Selected architecture

The development and submission adapters use the immutable primary preset:

- versioned state that retracts the stated opening preference while preserving later answers on a scoped preference override;
- exact full-value and clause-level catalog-signature promotion only for non-empty buckets of at most 500;
- popularity-ordered category-plus-disclosure buckets, including the opening category bucket, with every plausible semicolon parse unioned before emission;
- direct identification only for category-bound card keys that are unique in the full catalog, with agreement across plausible semicolon parses;
- ordered-prefix identification only before intent revision, and unordered identification only after all four disclosure positions are present;
- sparse `OR` fallback with weights `6/4/2.5/2.5/1.5/1`;
- soft opening-category coverage strength 1.00 and popularity strength 0.30;
- one high-confidence item before turn 5 or four active constraints, then the full ten-item slate, with seen-item exclusion scoped to items actually emitted in the current intent version;
- Unicode diacritic folding at token and structural-parser boundaries;
- catalog-derived one-edit recovery only inside explicit category and disclosure regions;
- free-text lexical expansion and model reranking disabled.

The pure sparse preset is the rollback and retains the selected safe state and
soft priors. The optional signature asset is catalog-bound by SHA-256. If it is
missing, corrupt, or bound to another catalog, construction records the reason
and rebuilds the equivalent in-memory index rather than aborting the run.

The selected primary measures TechnicalScore 0.978500 on the released set,
with HR@10 1.000, MRR 0.996667, and MTTC 2.025. Three distribution-matched
200-target panels disjoint from released targets score 0.979075, 0.965625, and
0.959900 when rerun from this exact tree. An exhaustive ground-truth audit records 117 correct direct
identifications and zero wrong ones; across 386 non-empty disclosure-bucket
promotions, all 386 retain the target. The registered robustness matrix still
has target-removal failures under several surface and meaning-changing edits.
This remains development evidence rather than a private-performance claim.

A second proxy varies card shape rather than target identity, drawing targets
from the three `intent_card` shapes the released set never contains. It exposes
a different failure surface and disagrees with released-set tuning of
`popularity_strength` (docs/evidence/EXP_006_SHAPES.md). These proxies are
development diagnostics, not private-score estimates.

## Closed decisions and possible extensions

1. EXP-013 is closed: question specificity was measured across ten arms and every alternative to repeated `other` lost (docs/evidence/EXP_013.md). Later-rank cluster coverage remains post-submission research, only behind the selected deterministic path.
2. Robustness work targets general normalization and retrieval invariants; more released-template phrase patches are not acceptable evidence.
3. Any optional model must beat the no-op and lexical controls on released score, disjoint targets, perturbation slices, license, offline startup, latency, memory, disk, and clean packaging.
4. Closed. The release asset is rebuilt from the frozen scoring catalog and
   both paths are rerun from a clean extraction on every release candidate: the
   bundled index and the refused-index rebuild score identically at 0.978500,
   and the asset now carries the fingerprint of the parser that produced its
   facets so a stale one is refused rather than served.

## Invariants

- exact `parent_asin` identity is the only hit condition;
- recommendations are ordered, unique, catalog-valid objects and never exceed ten;
- `reset` isolates sessions and `respond` requires a prior reset;
- final scoring never requires network access, credentials, a hosted service, or an optional model;
- experiment diagnostics cannot mutate official labels, evaluator logic, or production responses;
- a faithful trace may describe executed behavior but never change ranking.
