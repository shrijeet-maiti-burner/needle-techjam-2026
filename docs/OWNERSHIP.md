# Ownership boundaries

One owner per area, enforced through review rather than convention: a change
inside someone else's area was raised on their pull request instead of being
committed directly, and several were declined that way.

This replaces the H0 kickoff plan that stood here. That document listed first
branches and an hour-six gate, which was the right thing to write on day one and
the wrong thing to still be reading at submission: the branches it named are
gone and it described intentions rather than what held. What follows is the
record.

| Owner | Area | Must not change |
|---|---|---|
| Athul Krishna Boban (`athul1810`) | belief state, override policy, question policy, submission packaging | retrieval ranking, response serialization |
| Shrijeet Maiti (`shrijeet-maiti-burner`) | retrieval, ranking, emission, integration, release | another owner's area without review |
| Aryaman Anand (`AryamanAnand19`) | robustness catalogue, lexical normalization, conversational interface | state mutation, mandatory model dependency |
| Yazhiniyan (`Yazhiniyan99`) | evaluation baseline and independent reruns | evaluator, public labels, production ranking |

## How the boundary was actually held

Three examples, because the claim is only worth as much as its evidence.

**Measured in one area, landed by another.** EXP-019 measured the emission gate
and full-span signatures at +0.069513 on the public set. Both changes sit in
retrieval and response serialization, so the record and its harness were handed
over rather than merged by the owner who measured them; the patch landed in #19
under the retrieval owner.

**Declined rather than absorbed.** A `resolve_coarse_category` helper written
for the multilingual path duplicated `CatalogIndex.resolve_category`, which is
retrieval's and already stronger. It was dropped instead of shipped alongside.

**Flagged rather than assumed.** The signature asset stores the belief state's
parse of the catalog, so binding it to that parser touches `needle/catalog.py`.
The fingerprint lives in `needle/state.py`, which owns its own parsing identity,
and catalog.py only stores and compares it; the crossing was called out on the
pull request rather than settled quietly.

## Evidence discipline

Every record in `docs/evidence/` names an independent rerun owner, and the
headline arms were reproduced by a second person before being cited. Negative
and withdrawn results stay in the record with the reason, including a
popularity arm that gained on the released set and lost on the held-out one, a
propensity model that did not transfer, and a conjunction rule that was built,
measured, and reverted on the measurement.
