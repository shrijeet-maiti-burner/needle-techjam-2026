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

## Completed records

- [EXP-001 and H0-CONTROL-001, 29 August](evidence/H0_CONTROL.md): official weak baseline reproduced exactly; minimal integrated control completed all 200 sessions. The control is retained without attributing its combined gain or treating public behavior as private validation.
- [EXP-002/003/007/016 retrieval evidence, 29 August](evidence/EXP_002_003_007_016.md): bounded signatures, slate size, sparse fields, and popularity were measured; negative arms and the missing hard-filter diagnostic are recorded.
- [EXP-006/008/018 state, lexical, and robustness evidence, 29 August](evidence/EXP_006_008_018.md): subject-preserving override passed, lexical rewrites failed, invalid surface runs were excluded, and the then-current primary plus rollback were selected without freezing.
- [Final primary selection, 30 August](evidence/FINAL_SELECTION_20260830.md): seen exclusion and safe intent retraction were promoted; category and popularity were selected on released, 1,000-target disjoint, and robustness evidence; the profile prior and higher public-only popularity arm were rejected; source-only packaging passed.
