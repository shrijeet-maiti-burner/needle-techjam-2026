# H0 ownership and handoff

All branches start from current `main`. No one should wait for another owner's speculative implementation.

| Owner | First branch | H6 deliverable | Must not change |
|---|---|---|---|
| Athul (`athul1810`) | `state/minimal-belief-lifecycle` | explicit constraint state plus correction, negation, and override fixtures behind `StateStore` | retrieval ranking or public facade |
| Aryaman (`AryamanAnand19`) | `semantic/noop-and-lexical-robustness` | preserve the no-op path; add bounded lexical normalization and robustness fixtures only | state mutation or mandatory model dependency |
| Yazhiniyan (`Yazhiniyan99`) | `evaluation/reproducible-baseline` | official baseline record, scenario slices, environment capture, result summarizer, and rerun instructions | evaluator, public labels, or production ranking |
| Shrijeet (`shrijeet-maiti-burner`) | `retrieval/catalog-and-sparse` | catalog validation, sparse controls, integration, and EXP-002/007/016 preparation | another owner's boundary without review |

## First integration gate

By H6, one offline command must finish all 200 public sessions with strict responses and no invalid identifiers. A score improvement is not required at this gate. Every owner supplies focused tests and a rollback boundary before integration.

## Pull-request order

1. evaluation command and baseline record;
2. state fixtures and lifecycle;
3. retrieval experiments and minimum ambiguity summary;
4. semantic/robustness variants;
5. integrated experiment branches after their controls are reproducible.

Parallel work is expected, but interface changes require tagging Shrijeet and every affected owner before code is written.
