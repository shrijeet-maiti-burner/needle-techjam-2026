# Team contributions and ownership

The team divided responsibility by subsystem so implementation, evaluation,
and review remained independently attributable. Cross-subsystem changes were
reviewed by the contributor responsible for the affected area.

| Contributor | Primary area | Delivered |
|---|---|---|
| Athul Krishna Boban (`athul1810`) | conversation state, override behavior, question policy, packaging | versioned constraints; clause-scoped negation, contradiction and retraction handling; intent-override policy; question-policy experiments; correction-safe query retirement; release packaging and clean-bundle checks |
| Shrijeet Maiti (`shrijeet-maiti-burner`) | retrieval, ranking, integration, release | reproducible experiment harness; catalog validation; signature and SQLite FTS5 retrieval; bounded category and popularity priors; adaptive slate and seen-item policy; typed price/rating/review behavior; primary/rollback integration and release verification |
| Aryaman Anand (`AryamanAnand19`) | robustness, lexical normalization, conversational interface | perturbation library and session-level robustness reporting; tokenizer symmetry and typo-recovery experiments; never-failing turn guard; target-blind interface; concurrent HTTP checks and interface isolation tests |
| Yazhiniyan (`Yazhiniyan99`) | baseline evaluation, adversarial language QA, independent reproduction | official baseline verification; negation and correction counterexamples; clean-tree and extracted-archive reproductions on CPython 3.10 and 3.12; resource and release checks |

## Review and evidence

- headline evaluator results were reproduced by a second contributor before
  being cited;
- the evaluation owner did not modify evaluator code, public labels, or
  production ranking;
- every retained experiment record identifies its code, controls, metrics,
  limitations, decision, and rollback;
- the source repository retains negative and withdrawn results under
  `docs/evidence/`, including public-only improvements that failed
  catalog-disjoint transfer checks.
