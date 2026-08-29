# Experiment register

No result is decision-grade unless another owner can reproduce it from the recorded code, configuration, official artifact pins, environment, and command.

## Record template

```text
experiment id:
hypothesis:
comparison and fixed controls:
falsification threshold registered before run:
code sha and clean-tree state:
official source, evaluator, catalog, and public-set pins:
command and configuration:
machine, python, dependencies, network, and model assets:
aggregate and scenario metrics:
robustness slices:
cold/warm latency, startup, memory, disk, and package impact:
negative or inconclusive findings:
decision and rollback:
independent rerun owner:
```

## First gates

| ID | Owner | Question | Required controls | Earliest decision |
|---|---|---|---|---|
| EXP-001 | Yazhiniyan | does the unmodified official baseline reproduce? | published baseline, identical artifacts | H2 |
| EXP-002/007 | Shrijeet | do exact signatures or fielded sparse variants improve controlled retrieval? | official weak FTS, collision and perturbation slices | H12 |
| EXP-006 | Athul | does targeted versioned invalidation beat no reset and full reset? | identical retrieval and override fixtures | H12 |
| EXP-016 | Shrijeet; Athul reviews | does a bounded soft target-eligibility prior help without tail or slice damage? | no prior and hard-filter controls | H12 |
| EXP-013 | Athul + Shrijeet | does answerability-aware questioning beat fixed, entropy-only, repeated-`other`, and no-question controls? | identical safe slates | H24 |
| EXP-014 | Shrijeet | does ambiguity-cluster later-rank coverage beat relevance-only and fixed slate controls? | rank-one relevance preserved where applicable | H24 |
| EXP-008/010/011 | Aryaman + Yazhiniyan | does an optional semantic path improve robustness within offline resource limits? | no-op and lexical-only controls | H40 |

Public TechnicalScore is one technical input, not the architecture selection rule. Robustness, contract safety, resources, reproducibility, and judge-facing evidence remain independent gates.
