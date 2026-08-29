# Robustness harness (EXP-010)

Offline tooling that measures how gracefully the agent degrades when the
customer's phrasing changes. Not part of the submission bundle.

## Status

| Piece | State |
|---|---|
| `perturb.py` — perturbation library | **this PR** |
| session driver — mirror of the official loop with a per-message perturbation hook | next PR |
| slice runner + report — baseline vs perturbed deltas per slice | next PR |
| `scripts/run_robustness.py` — CLI over the real public set + catalog | next PR |

## Perturbation families

- **surface** (`Meaning.PRESERVING`): `casing`, `whitespace`, `punctuation`,
  `accents`, `synonym`, `word_order`, `filler`, `politeness`, `contraction`,
  `number_format`, `typo`. These rewrite phrasing only; the target's true
  constraint set is unchanged, so a robust agent must still find it.
- **semantic** (`Meaning.CHANGING`): `negate_value`, `swap_value`. These change
  one constraint; the harness checks the agent reflects the change instead of
  treating the message as equivalent.

Every function takes an explicit `random.Random`, so a `(text, seed)` pair is
fully reproducible. A non-empty input never becomes empty. Surface perturbations
are verified in tests to never introduce an override / negation / no-preference
trigger the original message did not contain.

## Planned slices (next PR)

`exact surface | casing | whitespace | punctuation | accents | synonym |
word_order | filler | politeness | contraction | number_format | typo |
negation | attribute_swap | constraint_drop | conflict_add | correction |
override_paraphrase`

Per slice, against the reconstructed intent for each public target:
target recall @10 / @50 / @200, target-removal rate (dominant safety metric),
HR@10, MRR, MTTC, and the semantic-enabled minus semantic-bypassed delta.
Meaning-preserving and meaning-changing slices are reported separately with
different gates: preserving slices must not lose recall; changing slices must
not regress and must not be silently equated.
