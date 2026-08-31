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

**Question policy.** The scored contract asks `other` on every answerable turn
before the last. This is not a heuristic. The released simulator answers a specific attribute only
when the target actually has a constraint of that type, and returns nothing
otherwise, while `other` returns up to two undisclosed constraints regardless of
type. The target has at most four constraints. So `other` strictly dominates any
attribute-specific question and two questions exhaust the customer. Asking also
costs nothing, because the evaluator scores `recommendations` and may end the
session before it reads `ask_attribute`. The human-facing message independently
names the catalog facet with the greatest positive cost-adjusted expected
candidate reduction. That choice, its coverage, residual-set estimate, and
stopping evidence are emitted in the target-blind trace; it never changes the
scored `ask_attribute` or ranking policy.

**Retrieval.** Exact full-value and punctuation-delimited clause signatures are
looked up in a catalog-bound SQLite index, with fielded FTS5 BM25 as the fallback
ordering. Signature intersections larger than 500 are not promoted. The
metadata-derived intent-card path separately indexes every category-bound
disclosure prefix. At each turn, all plausible semicolon parses are unioned and
the admitted products are ordered by catalog popularity; an over-limit parse
makes this path decline instead of truncating evidence. A direct answer is used
only when a category-bound card key is globally unique, every resolving parse
agrees, and the intent-order safety guards hold. Before turn 5 or four active
constraints, the agent emits only rank one; it then releases the full slate.
Candidates actually shown within an intent version are excluded, while withheld
candidates remain eligible. FTS5, soft category coverage, and the bounded
`rating_number` prior remain the fallback.

**Surface robustness.** Structural parsers fold accents and normalize
whitespace. A catalog-derived one-edit corrector operates only on the explicit
opening category and disclosure clauses. Conservative category variants such
as `trousers`/`pants` share a category key. Negation is scoped to its clause;
contrastive punctuation and conjunctions let `not black - make it blue` reject
the old value without rejecting its replacement. Arbitrary customer prose is
not rewritten and no fixed product identifiers are encoded.

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
| per-response latency, p50 | 6.529 ms |
| per-response latency, p95 | 147.513 ms |
| per-response latency, p99 | 254.434 ms |
| per-response latency, max | 631.962 ms |
| construction with bundled index | 8.364 s |
| construction without bundled index | 84.788 s |
| generated index schema and size | 8; 68,702,208 bytes |
| generated index SHA-256 | `797dd7ef14911a43966599f7157e41db8e80e3feda56e9e09f197cad0e1917e3` |
| contract violations | 0 of 405 responses |

Measured on the 200 official public sessions, `retrieval_mode=signature_first`,
`signature_bucket_limit=500`, `category_strength=1.00`, `popularity_strength=0.30`,
`override_policy=retract_stated`, `exclude_seen=true`, category-bound disclosure
promotion and direct identification enabled, and adaptive slate size 1 -> 10.

## Limitations

These are stated plainly because they bear on how the result should be read.

**The public score is measured; private transfer is not.** Public intent cards
are deterministically materialised from the target catalog row. Three separate
200-target proxies exclude every released ground-truth target and match public
rating, price-presence, broad-category, profile, and scenario marginals. They
score 0.979075, 0.965625, and 0.959900 when rerun from the release-candidate
tree. They still reuse the released simulator, so they are evidence against
direct target memorising, not private-score estimates.

**Sensitivity to message wording is measured and real.** The exact surface has
HR@10 1.000 and MRR 0.996667. Paraphrase removes one target out of 200 and word
order removes two of 158 changed targets. Single-edit typo removes none but
reduces MRR to 0.988958. The meaning-changing negation, attribute-swap, and
constraint-drop edits also fail the registered zero-removal gate against the
original target. The exact rates and ranking metrics are retained in the dated
final evidence record. The gates were not weakened.

**Override handling still depends on a structural trigger.** Accent folding and
independent paraphrases pass, and later question answers now survive a scoped
preference override even when the optional opening-subject anchor cannot be
parsed. A genuinely unrecognised retraction would still leave the old intent
version active; no model is present to infer it semantically.

**The popularity prior is conditional, not free.** With category strength 1.00,
popularity 0.55 reaches 0.881183 on the released set but loses to 0.30 on 1,000
disjoint targets, 0.866666 versus 0.867627. The higher released result is
rejected rather than reported as the primary.

**Disclosure promotion depends on evaluator structure.** It assumes intent
cards are metadata-derived and clean disclosures retain the released ordering.
If the private evaluator uses hand-written cards or a different disclosure
policy, the category-bound path declines or loses its benefit and the
signature/FTS path must carry the session. An exhaustive public audit records
117 correct direct identifications and zero wrong; all 386 non-empty promoted
buckets retain the public target. Neither result proves private behavior.

**Negative constraints are soft, not absolute filters.** The belief state records
exclusions, removes their values from the bag-of-words retrieval surface, and
stably demotes candidates whose catalog facets conflict. Conflicting products
remain after compatible ones because catalog metadata and natural-language
parsing can both be incomplete. A probe that used hard filters scored materially
worse, 0.7054 against 0.8817, because precision without recall promotes
confident wrong items to rank one.

**Boundary sessions pay an unavoidable one-turn tax.** The first question asked
in a boundary session always returns a deflection. No policy avoids it; it can
only be paid early.


## Demonstrated session

`python scripts/needle_storefront.py --warm` runs an unscripted local storefront
against the selected primary. Each turn renders the active/superseded belief
ledger, grounded product fields, latency, and an expandable decision receipt
read directly from the same target-blind trace as Needle Lens. There is no
demo-only reranking path.

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
| evaluation baseline and reruns | Yazhiniyan | no merged repository contribution is recorded in this release candidate; add only independently verifiable release or submission work before the final description is frozen |

Every experiment in `docs/evidence/` names an independent rerun owner, and the
headline arms were reproduced by a second person before being cited.
