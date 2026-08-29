# Research decisions for the H0-H24 build

Last audited: 29 August 2026. These are design constraints, not claims that a
published result transfers to the TechJam evaluator.

| Primary source | Result relevant here | Decision for Needle | Non-transfer warning |
|---|---|---|---|
| [ProductAgent (Ye et al., EMNLP 2025)](https://aclanthology.org/2025.emnlp-industry.25/) | Couples structured dialogue memory, candidate feature summaries, clarification, and hybrid retrieval in a closed loop. | Keep one explicit state -> retrieve -> ambiguity -> ask/slate loop. | Its LLM/tool stack and simulator are not evidence that the same components improve this catalog or score. |
| [Learning to Ask Good Questions (Rao and Daumé III, ACL 2018)](https://aclanthology.org/P18-1255/) | Frames clarification ranking as expected value of information rather than uncertainty alone. | EXP-013 must measure downstream target retention and slate-fit utility, not only partition entropy. | The source task is StackExchange clarification, not product retrieval. |
| [Asking More Informative Questions for Grounded Retrieval (Keh et al., NAACL 2024)](https://aclanthology.org/2024.findings-naacl.276/) | Shows that information-gain policies fail when a question's presupposition is false; adds an explicit no-answer path. | Estimate answerability before information gain and preserve an `UNKNOWN`/not-applicable outcome. Boundary deflection is evidence, not a negative constraint. | The source task identifies images and uses a VQA responder. Only the failure mechanism transfers. |
| [When and What to Ask (Zhao et al., ACL 2026)](https://aclanthology.org/2026.findings-acl.845/) | Separates deciding whether to clarify from choosing the clarification and evaluates interaction efficiency. | Include no-question and stop-asking controls; do not force a question after useful disclosure is exhausted. | Its QA/RLVR method is out of scope unless a later controlled experiment justifies it. |
| [CLARITY (Sarwar et al., ACL Industry 2026)](https://aclanthology.org/2026.acl-industry.86/) | Finds that systems may detect ambiguity yet fail to localize and resolve multiple ambiguity sources. | Keep attribute-scoped, versioned constraints and test correction/conflict localization rather than a single scalar confidence. | NL2SQL ambiguity is not catalog ambiguity; no reported metric transfers. |
| [MSPA-CQR (Cao et al., ACL 2026)](https://aclanthology.org/2026.findings-acl.638/) | Aligns conversational rewrites with retrieval and response feedback rather than judging rewrites in isolation. | Any query rewrite is accepted only on end retrieval metrics and robustness, never on linguistic plausibility alone. | Preference optimization is too data- and model-heavy for the current critical path. |
| [MMR (Goldstein and Carbonell, 1998)](https://aclanthology.org/X98-1025/) | Trades relevance against novelty during selection. | Use it only as a bounded EXP-014 control; rank one remains relevance-first. | Document novelty is not automatically useful product-facet coverage. |
| [Reciprocal rank fusion (Cormack et al., SIGIR 2009)](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/) | Combines rank lists without requiring calibrated raw scores. | Prefer fixed rank fusion when exact, sparse, and optional semantic scores are not comparable. | Fusion still needs a candidate-recall and slice gate here. |
| [LambdaMART overview (Burges, Microsoft Research 2010)](https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/) | Learning-to-rank methods are effective when trained and validated on suitable ranking data. | Defer LTR. Two hundred evaluator-coupled sessions with disjoint private targets do not justify adding a trainable ranker before fixed features and robustness splits are exhausted. | The cited large-scale ranking evidence does not establish sample efficiency on this task. |

## Consequences for the next experiments

1. Exact signatures, sparse weights, popularity, slate size, and seen-item
   suppression are independent constructor controls. Each arm changes one
   factor.
2. Exact matching may promote only a non-empty bounded bucket. It never hard
   filters the sparse fallback.
3. The popularity signal is bounded and monotone. A hard threshold appears
   only as a deliberately failing diagnostic control, never as a candidate
   architecture.
4. Question value is `answerability x downstream utility`, with entropy as one
   input. No-answer, repeated-question, override, and stop-asking outcomes are
   measured explicitly.
5. Learned or semantic methods remain optional until they beat the lexical
   rollback on public, perturbation, resource, licensing, and packaging gates.
