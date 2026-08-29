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

**Retrieval.** Exact catalog-signature promotion over an FTS5 index, with sparse
BM25 as the fallback ordering and a bounded popularity prior over
`rating_number`. Candidates already shown within an intent version are excluded,
which turns ten turns of ten slots into up to a hundred distinct products rather
than the same twenty repeated.

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

| item | value |
|---|---|
| model | none |
| prompt tokens | 0 |
| completion tokens | 0 |
| estimated model cost | $0.00 |
| network access required | no |
| credentials required | no |
| per-response latency, p50 | 38.5 ms |
| per-response latency, p95 | 77.7 ms |
| per-response latency, p99 | 103.6 ms |
| per-response latency, max | 126.9 ms |
| one-time construction | ~1.5 s with the bundled index, ~8.2 s rebuilding |
| peak Python heap | ~9 MB above the interpreter baseline |
| contract violations | 0 of 494 responses |

Measured on the 200 official public sessions, `retrieval_mode=signature_first`,
`override_policy=retract_stated`, `exclude_seen=true`.

## Limitations

These are stated plainly because they bear on how the result should be read.

**The public score is measured, its transfer is not.** Public intent cards are
deterministically materialised from the target catalog row, and the private set
uses disjoint users and disjoint targets. A high public score is consistent with
having fitted the message generator rather than solved the task. Nothing in this
submission demonstrates transfer.

**Sensitivity to message wording is measured and real.** Under a perturbation
harness that rewords the customer's messages while preserving meaning, the
TechnicalScore falls from 0.8977 at baseline to 0.8216 under light synonym
substitution and 0.7188 under heavy paraphrase. At the heavier levels the tuned
system scores below plain BM25 with no additions, which sits at 0.8294. The
constraint matching, category parsing, and override detection all key off the
released message templates, so they degrade together rather than independently.

**Override detection is the single largest fragility.** If the override trigger
phrase is not recognised, the intent version never bumps and no override policy
runs. In that condition the override slice falls to 0.133 hit rate and the
overall score to 0.7242, identically for every policy.

**The popularity prior is conditional, not free.** Added to bare BM25 it is
negative, 0.8294 to 0.7727. It pays only once exact matching has narrowed the
candidate set. It is therefore a second bet on the messages being literal.

**Negative constraints are tracked but not enforced.** The belief state records
exclusions and exposes them, but retrieval does not currently filter on them. A
probe that applied them as hard filters scored materially worse, 0.7054 against
0.8817, because precision without recall promotes confident wrong items to rank
one. Wiring them in remains an open measured question rather than an oversight.

**Boundary sessions pay an unavoidable one-turn tax.** The first question asked
in a boundary session always returns a deflection. No policy avoids it; it can
only be paid early.
