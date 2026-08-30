# EXP-010 robustness evidence, 30 August 2026

Status: **the gate does not pass.** Two of five failures are closed, the
remaining three are diagnosed and bounded, and one of them is recommended for
acceptance rather than repair. Nothing here is a private-set claim.

## Reproducibility boundary

- official source commit `34078351e1c3615e5505a2e829600b56a542e462`
- catalog SHA-256 `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- public set SHA-256 `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- primary preset, signature asset present, seed `0`, 200 sessions per slice
- Python 3.11.9, SQLite 3.45.1, network disabled

The harness drives the official simulator's own message generation and mirrors
`evaluate()`'s session loop. It never reports a leaderboard metric; every number
below is a degradation delta against the unperturbed arm.

## Result

| Slice | Start of day | Now | Meaning |
|---|---:|---:|---|
| exact surface | 0.995 | 0.995 | baseline |
| accents | 0.860 | **0.960** | preserving |
| typo | 0.925 | **0.990** | preserving |
| whitespace | 0.990 | 0.990 | preserving |
| word order | 0.995 | 0.995 | preserving |
| override paraphrase | 0.995 | 0.995 | preserving |
| filler | 0.960 | 0.960 | preserving |
| paraphrase | 0.970 | 0.970 | preserving |

Gate failures 8 -> 7. The `typo` HR gate now passes. Official public result is
unchanged at TechnicalScore 0.878039 throughout: every accepted change is either
inert on clean text or provably a no-op there.

## What was actually wrong

**Query and corpus tokenized differently.** `products` is built
`unicode61 remove_diacritics 2`, so the corpus stores `cafe` for `café`, while
`TOKEN_RE` matches ASCII only -- an unfolded query term broke *at* the accent:
`cótton` tokenized to `tton`. `canonical_signature` folded; `query_terms` did
not, so the two retrieval routes disagreed about which products a disclosed
constraint referred to. Fixed by folding both through one function. Accent
target-removal 0.035 -> 0.005.

**The override trigger is a phrase list.** Corrupting its own keywords silently
disabled override handling: missed 26/60 typo variants, 31/40 accent variants,
0/60 filler variants. A miss is not a ranking loss, it is a lost session --
`override_applied` gates the hit check, so the session cannot convert at all.
This was the dominant cause of both remaining failures, and it is why
`override_paraphrase` passed: politeness and synonym rewrites happen not to
touch those particular words, so that slice was passing for the wrong reason.

**`Agent.respond` could raise.** Seven argument shapes raised, including a
replayed turn and a non-integer `top_k`. `evaluate` catches and substitutes an
empty response, which also blanks `ask_attribute`, so the customer discloses
nothing for every remaining turn. On turn one that forfeits the session.

## Two negative results, recorded

**Vocabulary-derived typo correction: +0.005, rejected.** Mapping unmatched
query terms to the nearest catalog term at edit distance one worked exactly as
designed -- 1311 corrections, all correct on inspection, 2.6 ms per lookup over
102,544 terms, provably inert on clean queries. It moved `typo` by one session
in 200. Target recall was already 0.990 without it, so unmatched query terms
were never what the slice was losing. Shipped default-off; not proposed for the
preset.

Worth recording as process: had this shipped on the strength of "1311 correct
corrections" without an end-to-end arm, it would have added a permanent path to
the scoring bundle for +0.005 and the override-trigger defect -- thirteen times
larger -- would not have been found.

**Signature prefix backoff: +0.000, discarded.** Trailing text lands inside the
extracted signature span, so an appended aside turns `cloudsoft cotton` into
`cloudsoft cotton like`, which no product carries. Confirmed to happen in 7/30
filler variants. Backing off to the longest prefix the catalog does contain
recovered the precise signature -- and changed no slice at all, because the
sparse fallback already absorbs the loss. The code was not kept: a default-off
path with no measured benefit is weight in a bundle heading for freeze. The
finding is worth more than the fix, and it is evidence the two-route design
degrades the way it was meant to.

## What remains, and a recommendation not to fix one of them

`accents` -0.035, `filler` -0.035, `paraphrase` -0.025, plus four slices over
the target-removal gate.

The `filler` mechanism is understood. Conversational filler enters the BM25
query as terms, and those terms are corpus-*rare* -- `honestly` appears in 3 of
50,000 products, `uh` in 3, `um` in 11. Rare terms carry high IDF, so each one
pulls ranking hard toward the handful of products that happen to contain it.

**There is no corpus-statistical way to separate those from meaningful rare
terms**: `honestly` inside a product description is legitimate text. Only a
hardcoded linguistic stopword list distinguishes them. Weighed against that:
the effect is at most 0.035 on a perturbation family this team invented, its
private relevance is unknown while A-03 is unanswered, and the list would risk
discarding genuinely discriminative terms.

Recommendation: **accept `filler` and `paraphrase` as bounded and understood
rather than fix them.** Seeding a stopword list from the harness's own filler
vocabulary would be fitting the test set, and a general list is a real
precision risk for a synthetic gain.

## Gate calibration, flagged against my own work

`max_target_removal_rate` is preregistered at exactly zero. One lost session in
200 is 0.005 and fails it, so four slices fail that gate on a single session
each. The threshold is probably too strict to carry information at this sample
size. It is mine, and it is flagged here rather than relaxed, because loosening
a gate after seeing the result it produces is how a gate stops meaning anything.
A team decision either way is fine; a quiet edit is not.

## Not covered

- Two-character corruption. Widening edit distance raises false-override risk
  sharply and needs its own measurement.
- Value-internal corruption, as opposed to trailing noise.
- `@50` / `@200` recall, which needs the retriever to expose a pool wider than
  the scored ten.
- The catalog-disjoint transfer proxy. Every number above is public-set only.
