# Method, model choice, and limitations

Required by `docs/submission_rules.md` ("a short report describing method, model
choice, and limitations" and "a disclosure of latency, token usage, and
estimated model cost").

## Method

The agent is a deterministic, standard-library retrieval system. No neural
model, no embeddings, no network.

**Belief state.** Each session accumulates the customer's messages and a
versioned constraint list. Constraints carry a polarity, a turn, and an intent
version, and are superseded rather than deleted so the history stays auditable.
A stated value and its own exclusion cannot be active simultaneously.

**Question policy.** The agent asks `other` on every turn before the last. This
is not a heuristic. The released simulator answers a specific attribute only
when the target actually has a constraint of that type, and returns nothing
otherwise, while `other` returns up to two undisclosed constraints regardless of
type. The target has at most four constraints. So `other` strictly dominates any
attribute-specific question and two questions exhaust the customer. Asking also
costs nothing, because the evaluator scores `recommendations` and may end the
session before it reads `ask_attribute`.

**Retrieval.** Exact full-value and punctuation-delimited clause signatures are
looked up in a catalog-bound SQLite index, with fielded FTS5 BM25 as the fallback
ordering. Signature buckets larger than 500 are not promoted. A soft coverage
score for opening-category words and a bounded popularity prior over
`rating_number` rerank but never filter candidates. Candidates already shown
within an intent version are excluded, which turns ten turns of ten slots into
up to a hundred distinct products rather than repeating the same slate.

**Intent override.** An explicit override retracts the preference the customer
stated, not the answers they gave to our questions. The opening message is
reduced to its subject clause and later replies are kept. This matters because
`intent_override` sessions cannot score until the override fires, so the turns
before it are spent gathering constraints that a full reset would then discard.

## Model choice

None. No LLM API and no local model is used at any point in the scored path.
This was a deliberate choice: the task is recovering one catalog row from a
constrained vocabulary, roughly half of the public targets are uniquely
identified by a single verbatim constraint string, and exact matching does that
better and far faster than a semantic model. It also removes credential,
network, and cost risk from official scoring entirely.

## Disclosure

The separate [submission disclosure inventory](../docs/SUBMISSION_DISCLOSURES.md)
tracks the required development tools, APIs, libraries and frameworks, and
datasets and assets for the final Devpost description.

| item | value |
|---|---|
| model | none |
| prompt tokens | 0 |
| completion tokens | 0 |
| estimated model cost | $0.00 |
| network access required | no |
| credentials required | no |
| per-response latency, p50 | 96.5 ms |
| per-response latency, p95 | 203.8 ms |
| per-response latency, p99 | 238.3 ms |
| per-response latency, max | 281.1 ms |
| construction with bundled index | 5.125 s |
| construction without bundled index | 40.614 s |
| construction peak working set, bundled | 196,231,168 bytes |
| construction peak working set, source-only | 263,766,016 bytes |
| complete evaluator peak working set, bundled | 423,079,936 bytes |
| release bundle size | 50,221,823 bytes |
| contract violations | 0 of 429 responses |

Measured on the 200 official public sessions, `retrieval_mode=signature_first`,
`signature_bucket_limit=500`, `category_strength=1.00`, `popularity_strength=0.30`,
`override_policy=retract_stated`, `exclude_seen=true`.

## Limitations

These are stated plainly because they bear on how the result should be read.

**The public score is measured; private transfer is not.** Public intent cards
are deterministically materialised from the target catalog row. Three separate
200-target proxies exclude every released ground-truth target and match public
rating, price-presence, broad-category, profile, and scenario marginals. They
score 0.884987, 0.886981, and 0.892706. They still reuse the released simulator,
so they are evidence against direct target memorising, not private-score
estimates.

**Sensitivity to message wording is measured and real.** The exact surface has
HR@10 0.995 and MRR 0.710089. Accent perturbations are now byte-identical on all
reported metrics; filler preserves HR@10 and loses 0.004535 MRR; compound
paraphrase reaches HR@10 0.985 and MRR 0.666165. Single-edit typos remain the
largest failure at HR@10 0.905 and MRR 0.618657. The measured typo-recovery arm
did not improve these figures and was removed.

**Override handling still depends on a structural trigger.** Accent folding and
independent paraphrases pass, and later question answers now survive a scoped
preference override even when the optional opening-subject anchor cannot be
parsed. A genuinely unrecognised retraction would still leave the old intent
version active; no model is present to infer it semantically.

**The popularity prior is conditional, not free.** With category strength 1.00,
popularity 0.55 reaches 0.881183 on the released set but loses to 0.30 on 1,000
disjoint targets, 0.866666 versus 0.867627. The higher released result is
rejected rather than reported as the primary.

**Category parsing is soft and bounded.** Failure to recognize an opening
category removes only that prior; it does not remove candidates. A wrong partial
parse can still reorder results, so the category prior is not equivalent to a
verified taxonomy constraint.

**Negative constraints are tracked but not enforced.** The belief state records
exclusions and exposes them, but retrieval does not currently filter on them. A
probe that applied them as hard filters scored materially worse, 0.7054 against
0.8817, because precision without recall promotes confident wrong items to rank
one. Wiring them in remains an open measured question rather than an oversight.

**Boundary sessions pay an unavoidable one-turn tax.** The first question asked
in a boundary session always returns a deflection. No policy avoids it; it can
only be paid early.


## Demonstrated session

`python3 scripts/demo_session.py --scenario intent_override` prints one full
multi-turn session. It is a real transcript, not a staged one: the customer
messages come from the official `local_evaluator`'s own `initial_message`,
`customer_reply` and override injection, and the hit test is the evaluator's, so
what is printed is what the scorer saw. `--scenario` selects buying, browsing,
intent_override or boundary; `--sample` runs a specific `sample_id`.

The override transcript is the one worth reading. It shows the turns the
evaluator refuses to score before the new intent arrives, which is why that
slice carries the highest turns-to-conversion by construction rather than
through any ranking weakness.

## Team contributions

Ownership boundaries are recorded in [docs/OWNERSHIP.md](../docs/OWNERSHIP.md)
and were enforced through review: each area has one owner, and cross-owner
changes were raised on the other owner's pull request rather than committed
directly.

| area | owner | delivered |
|---|---|---|
| belief state, override policy, question policy | Athul Krishna Boban | versioned constraint state with correction, negation and supersession (#1); `retract_stated` override policy (#6); contradiction invalidation (#9); retraction-rule override trigger (#10); submission packaging and run-safety (#8); EXP-006/013 closures and the popularity transfer review (#12) |
| retrieval, ranking, integration | Shrijeet Maiti | reproducible experiment harness (#2); catalog validation and sparse controls, measured primary and rollback paths (#5); transfer-gated primary selection (#11) |
| robustness, lexical normalization | Aryaman Anand | offline lexical normalizer and robustness fixtures (#3); EXP-010 perturbation library (#4); session-level robustness driver, slice runner and comparison report (#7); query/corpus tokenizer symmetry and resource safety (#13) |
| evaluation baseline and reruns | Yazhiniyan | <!-- CONFIRM BEFORE SUBMISSION: no merged pull requests are attributable to this owner in the repository history. Replace this line with the actual contribution or remove the row. --> |

Every experiment in `docs/evidence/` names an independent rerun owner, and the
headline arms were reproduced by a second person before being cited.
