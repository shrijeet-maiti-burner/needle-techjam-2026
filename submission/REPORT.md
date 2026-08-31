# Method, model choice, and limitations

Required by the participant kit's `docs/submission_rules.md` ("a short report describing method, model
choice, and limitations" and "a disclosure of latency, token usage, and
estimated model cost").

## Architecture and method

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

## Model choice and models used

None. No LLM API and no local model is used at any point in the scored path.
This was a deliberate choice: the task is recovering one catalog row from a
constrained vocabulary, roughly half of the public targets are uniquely
identified by a single verbatim constraint string, and exact matching does that
better and far faster than a semantic model. It also removes credential,
network, and cost risk from official scoring entirely.

## Cost, token usage, latency and resource disclosure

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
| construction with bundled index | 2.728 s |
| construction without bundled index, in-process rebuild | 24.400 s |
| peak resident memory, bundled index | 220.0 MB |
| peak resident memory, in-process rebuild | 302.1 MB |
| generated index schema and size | 9; 68,702,208 bytes |
| generated index catalog binding | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| generated index parser binding | `e8a0572f0938ed83b000869f2396de2183dbe03ed3c1c94c4491250784da23d2` |
| contract violations | 0 of 405 responses |

Construction happens once per evaluation run, not per session or per turn, so
the figures above are one-off. Both paths are reported because the specification
reserves the right to run the submission under CPU, memory, timeout and network
restrictions, and to treat a timeout as a miss. The worst case is the second
row: if the bundled index is refused for any reason the agent rebuilds an
equivalent one in process rather than failing, which costs 24.4 s once and
121 MB more, and then scores identically.

The index is identified by what it is bound to rather than by its own file
hash. Two builds of identical content can differ byte for byte, so a published
file hash is not something a rebuild can be checked against; the catalog and
parser bindings above are, and they are what the loader compares.

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

Required deliverable, printed in full below so it is readable from the archive
alone rather than only by running something. It is a real transcript, not a
staged one: the customer messages come from the official `local_evaluator`'s own
`initial_message`, `customer_reply` and override injection, and the hit test is
the evaluator's, so what is printed is what the scorer saw.

Reproduce it from this bundle with:

```
python3 scripts/demo_session.py --scenario intent_override
```

The script drives the organizer's own simulator, which ships with the
participant kit rather than with this submission, so from an extracted archive
it has to be told where the kit is:

```
TECHJAM_KIT_ROOT=/path/to/techjam-conversational-search \
    python3 scripts/demo_session.py --scenario intent_override
```

`--scenario` selects buying, browsing, intent_override or boundary; `--sample`
runs a specific `sample_id`.

```text
------------------------------------------------------------------------------
  session   public_0002   scenario intent_override
  target    B071X54486  Hide & Drink, Rustic Handmade Full Grain Leather [...]
  hidden    hard=['leather', '100% Leather']
            soft=['Imported', 'Buckle closure']
------------------------------------------------------------------------------

turn 1
  customer I'm looking for Accessories Belts. Buckle closure
  agent    I am starting with accessories belts. Which material? leather, nylon,
           rhinestone, polyester. You can also tell me anything else you
           prefer.
  asks     other
     1. B08FLYBP2J  Lavemi Men's Real Leather Ratchet Dress [...]
  (not scorable yet: the override has not been sent)

turn 2
  customer For that, what matters is: leather; 100% Leather.
  agent    I have 23 candidates among accessories belts and am narrowing with
           leather. Showing the most reviewed. Which style? casual (8),
           classic (3), elegant (2), vintage (2). You can also tell me
           anything else you prefer.
  asks     other
     1. B08L13LJ5M  BULLIANT Men's Belt, Slide Ratchet Belt [...]
  (not scorable yet: the override has not been sent)

turn 3
  customer Actually, ignore my earlier preference. What I need is: leather.
  agent    I am narrowing accessories belts using leather. Which style? casual (51),
           classic (25), elegant (21), vintage (11). You can also tell me
           anything else you prefer.
  asks     other
     1. B06XYH8FH8  Hanks 1.5" Freedom Men’s Heavy Duty [...]

turn 4
  customer For that, what matters is: Imported; Buckle closure.
  agent    I have 4 candidates among accessories belts and am narrowing with leather.
           Showing the most reviewed. Which style? classic (1), formal
           (1), vintage (1). You can also tell me anything else you
           prefer.
  asks     other
     1. B071X54486  Hide & Drink, Rustic Handmade Full Grain [...]  <-- target

  HIT on turn 4 at rank 1. Session ends here:
  the evaluator breaks on the first appearance and never re-reads the rank.

------------------------------------------------------------------------------
  turns to conversion 4   session score contribution 0.9400
  tokens 0, no network, no model.
------------------------------------------------------------------------------
```

The override transcript is the one worth reading. It shows the two turns the
evaluator refuses to score before the new intent arrives, which is why that
slice carries the highest turns-to-conversion by construction rather than
through any ranking weakness. It also shows the emission policy: one product per
turn while the belief state is still thin, because the scorer freezes a
session's rank at the first turn the target appears, so a premature slate locks
in a worse rank than waiting one turn would have earned.

A local storefront (`scripts/needle_storefront.py --warm`) and the target-blind
decision trace are in the source repository rather than this archive; the
specification puts interface work out of scope, and the transcript above is the
required artefact.

## Team contributions

Ownership boundaries are recorded in [docs/OWNERSHIP.md](../docs/OWNERSHIP.md)
and were enforced through review: each area has one owner, and cross-owner
changes were raised on the other owner's pull request rather than committed
directly.

| area | owner | delivered |
|---|---|---|
| belief state, override policy, question policy | Athul Krishna Boban | versioned constraint state with correction, negation and supersession (#1); `retract_stated` override policy (#6); contradiction invalidation (#9); retraction-rule override trigger (#10); submission packaging and run-safety (#8); EXP-006/013 closures and the popularity transfer review (#12) |
| retrieval, ranking, integration | Shrijeet Maiti | reproducible experiment harness (#2); catalog validation and sparse controls, measured primary and rollback paths (#5); transfer-gated primary selection (#11) |
| robustness, lexical normalization, conversational interface | Aryaman Anand | offline lexical normalizer and robustness fixtures (#3); EXP-010 perturbation library (#4); session-level robustness driver, slice runner and comparison report (#7); query/corpus tokenizer symmetry, SQLite handle release and the never-failing turn guard (#13); override-trigger tolerance to surface corruption (#15); vocabulary-derived typo recovery, measured and retained default-off as a negative result (#16); the conversational storefront interface (#27); concurrent traced storefront smoke gate (#35) |
| evaluation baseline and reruns | Yazhiniyan | no merged repository contribution is recorded in this release candidate; add only independently verifiable release or submission work before the final description is frozen |

Every experiment in the source repository's `docs/evidence/` names an
independent rerun owner, and the
headline arms were reproduced by a second person before being cited.
