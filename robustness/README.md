# Robustness harness (EXP-010)

Offline tooling that measures how gracefully the agent degrades when the
customer's phrasing changes. Not part of the submission bundle.

## Pieces

| Module | What it does |
|---|---|
| `perturb.py` | perturbation library: 11 surface perturbations + `negate_value` / `swap_value`, `apply` / `compose` |
| `session.py` | `run_perturbed_session` — mirror of the official `evaluate()` loop with one perturbation hook; `run_slice`; `Simulator` shim + `official_simulator()` |
| `slices.py` | the default slice catalogue (`DEFAULT_SLICES`) |
| `report.py` | `summarize`, `compare` (deltas + target-removal rate), `gate_failures` |
| `scripts/run_robustness.py` | CLI over the real public set (needs the bootstrapped kit) |

## Perturbation families

- **surface** (`Meaning.PRESERVING`): `casing`, `whitespace`, `punctuation`,
  `accents`, `synonym`, `word_order`, `filler`, `politeness`, `contraction`,
  `number_format`, `typo`. These rewrite phrasing only; the target's true
  constraint set is unchanged, so a robust agent must still find it.
- **card edits** (`Meaning.CHANGING`): `negate`, `swap`, `drop_soft`. These
  change one constraint in the reconstructed intent card; the harness checks the
  agent reflects the change instead of treating the message as equivalent.

Every perturbation takes an explicit `random.Random`, so a `(text, seed)` pair is
reproducible; `run_slice` derives its per-session RNG from `(seed, slice,
sample_id)`. A non-empty input never becomes empty. Surface perturbations are
tested to never introduce an override / negation / no-preference trigger the
original message did not contain.

## Slices

`exact_surface` (baseline) `| casing | whitespace | punctuation | accents |
synonym | word_order | filler | politeness | contraction | number_format | typo
| paraphrase | override_paraphrase | negation | attribute_swap |
constraint_drop`

Per slice: HR@10, MRR, MTTC, `target_recall` (target surfaced in *any* turn's
scored top-K), and the delta vs the `exact_surface` baseline. `target_removal_rate`
is computed only over samples the perturbation actually changed. Meaning-preserving
and meaning-changing slices are gated differently (`gate_failures`): a preserving
slice may not raise target removal or drop HR@10 past the bound; a changing slice
must not be silently equated with the baseline.

## Run

```bash
python scripts/bootstrap.py
python scripts/run_robustness.py --agent starter.agent:Agent            # full catalogue
python scripts/run_robustness.py --agent starter.agent:Agent --slices casing,negation
```

Writes an ignored `results/robustness/<ts>-<sha>/report.json`. Exits non-zero if a
preregistered gate fails.

## Known harness scope

`conflict_add` and a mid-session `correction` slice (both need bucket-aware or
multi-message perturbation); `@50` / `@200` recall (needs the retriever to expose
a wider pool than the scored ten). These are declared development-harness
limits, not unfinished runtime features or pre-submission gates.
