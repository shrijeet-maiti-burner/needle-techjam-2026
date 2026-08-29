# Architecture

## Decision boundary

The code currently implements only the minimum fields and behavior needed for a valid end-to-end run. Detailed confidence, provenance, ambiguity, cluster, and trace contracts are target architecture. They do not need to exist by H6 unless a running experiment consumes them.

```text
official evaluator
      |
starter.agent.Agent
      |
versioned state -> bounded signature promotion -> fielded sparse fallback
       -> bounded popularity rerank -> no-op semantic boundary -> strict response
```

## Stable H6 interfaces

- `StateStore.reset/observe` owns session lifecycle and raw active-intent history.
- `CatalogIndex.search` returns ordered catalog-valid `Candidate` values.
- `NoOpSemanticReranker.rerank` proves the optional stage can be bypassed without failure.
- `Agent.respond` owns the public contract, ten-item cap, deterministic message, and assembly.

The repeated-`other` action is still a control, not the final question policy or innovation claim. The official FTS weights are retained because both measured alternatives failed their gates.

## Current measured candidate

The development and submission adapters use the immutable primary preset:

- versioned state with sentence-bounded subject preservation on a scoped preference override;
- exact catalog-signature promotion only for non-empty buckets of at most 100;
- sparse `OR` fallback with weights `6/4/2.5/2.5/1.5/1`;
- bounded popularity strength 0.20, slate ten, and no seen-item exclusion;
- lexical normalization, expansion, fuzzy matching, and model reranking disabled.

The pure sparse preset is the rollback. The signature asset is a catalog-bound
32,034,816-byte SQLite file and is never built silently by an adapter. The
development adapter requires the ignored local asset; the submission adapter
requires the release-bundled asset.

This is a public-development selection, not a freeze. Deterministic surface and
paraphrase runs still regress materially, and the final asset has not completed
a clean-bundle rehearsal.

## Next experiment-driven extensions

1. EXP-013 and EXP-014 decide whether one constraint-ambiguity representation should control questions and later-rank coverage. Failure removes that controller without breaking the core path.
2. EXP-010 adds a session driver and independent surface/semantic slices rather than more hand-written marker patches.
3. Any optional model must beat the no-op and lexical controls on public score, perturbation slices, license, offline startup, latency, memory, disk, and clean packaging.
4. The deliberately failing hard-popularity filter remains to complete EXP-016's diagnostic matrix; it can never become the production policy.
5. Yazhiniyan independently reproduces the selected runs and owns final clean-package, faithful-trace, and submission checks.

## Invariants

- exact `parent_asin` identity is the only hit condition;
- recommendations are ordered, unique, catalog-valid objects and never exceed ten;
- `reset` isolates sessions and `respond` requires a prior reset;
- final scoring never requires network access, credentials, a hosted service, or an optional model;
- experiment diagnostics cannot mutate official labels, evaluator logic, or production responses;
- a faithful trace may describe executed behavior but never change ranking.
