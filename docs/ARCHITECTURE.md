# Architecture

## Decision boundary

The code currently implements only the minimum fields and behavior needed for a valid end-to-end run. Detailed confidence, provenance, ambiguity, cluster, and trace contracts are target architecture. They do not need to exist by H6 unless a running experiment consumes them.

```text
official evaluator
      |
starter.agent.Agent
      |
session state -> fielded sparse index -> no-op semantic boundary -> strict response
```

## Stable H6 interfaces

- `StateStore.reset/observe` owns session lifecycle and raw active-intent history.
- `CatalogIndex.search` returns ordered catalog-valid `Candidate` values.
- `NoOpSemanticReranker.rerank` proves the optional stage can be bypassed without failure.
- `Agent.respond` owns the public contract, ten-item cap, deterministic message, and assembly.

The initial repeated-`other` action is a control, not the final question policy or innovation claim. The initial FTS weights are the official weak baseline weights, not an accepted retrieval decision.

## Next experiment-driven extensions

1. Athul replaces raw history with versioned explicit constraints and correction/override fixtures.
2. Shrijeet measures exact signatures, fielded sparse variants, slate sizes, and the bounded target-eligibility prior.
3. Aryaman supplies a no-network lexical robustness layer first; any model remains optional until public, robustness, license, latency, memory, and packaging gates pass.
4. Yazhiniyan freezes the evaluator command, run record, scenario slices, resource measurements, and clean-package checks.
5. EXP-013 and EXP-014 decide whether one constraint-ambiguity representation should control questions and later-rank coverage. Failure removes that controller without breaking the core path.

## Invariants

- exact `parent_asin` identity is the only hit condition;
- recommendations are ordered, unique, catalog-valid objects and never exceed ten;
- `reset` isolates sessions and `respond` requires a prior reset;
- final scoring never requires network access, credentials, a hosted service, or an optional model;
- experiment diagnostics cannot mutate official labels, evaluator logic, or production responses;
- a faithful trace may describe executed behavior but never change ranking.
