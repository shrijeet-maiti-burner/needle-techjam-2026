# Red team: human conversational state

Scope: corrections, "not x but y", exclusions, contradictory preferences,
mixed-language requests, intent changes. Adversarial input written by hand
against the belief state, not a leaderboard run.

Base: `origin/main` at `4e36df6`. Every input below is exact and reproducible
through `needle.state.StateStore` or `needle.state.extract_constraints`.

Two findings were structural and are fixed on this branch with tests. The rest
are recorded and deliberately not fixed, for the reasons given.

## Fixed

### F1 A negator governed past the end of its clause

`_is_negated` read a fixed-width lookbehind and nothing else. A correction and
a coordinated exclusion put the same number of characters between the negator
and the value, so the two were indistinguishable and every correction below
recorded the wanted value as excluded.

| exact input | before | after |
|---|---|---|
| `I want not black but red.` | black NEG, **red NEG** | black NEG, red POS |
| `Not leather, cotton.` | leather NEG, **cotton NEG** | leather NEG, cotton POS |
| `I don't want polyester. Cotton is fine.` | polyester NEG, **cotton NEG** | polyester NEG, cotton POS |
| `Avoid wool; silk works.` | wool NEG, **silk NEG** | wool NEG, silk POS |
| `No black, red instead.` | black NEG, **red NEG** | black NEG, red POS |
| `not black, not navy, but green` | black NEG, navy NEG, **green NEG** | black NEG, navy NEG, green POS |

Consequence beyond the label: `active_constraints` feeds the turn record, and a
NEGATIVE constraint becomes a "ruled out" line, so the agent told the customer
it had ruled out the value they had just asked for.

Target-blind measurement. `customer_reply` joins two disclosures with `"; "`,
so whenever the first carries a negation token the second sits inside the
lookbehind width. Across the 200 public cards under the `negate_value`
perturbation, of 400 two-span disclosures **50 excluded a value that appeared
only in the second span**; after the fix, **0**. Examples:

```
public_0017  "For that, what matters is: no leather; color: red."
             wrongly excluded color:red
public_0020  "For that, what matters is: no cotton; color: grey."
             wrongly excluded color:grey
public_0008  "For that, what matters is: no nylon; 96% Nylon, 4% Spandex."
             wrongly excluded material:spandex
```

Coordination is deliberately not a terminator, so these are unchanged:

```
"A dress. No black and no navy."   black NEG, navy NEG
"I don't want black or navy"       black NEG, navy NEG
"no leather and no suede"          leather NEG, suede NEG
```

### F2 A retraction verb under a negated auxiliary fired an override

`EXPLICIT_OVERRIDE_RE` matched the verb without looking at what governed it.

| exact input | before | after |
|---|---|---|
| `Don't forget that I need cotton.` | **override**, session discarded | no override |
| `I can't forget the last pair I bought, they were great.` | **override** | no override |
| `Please do not forget my earlier preference.` | **override** | no override |
| `I won't forget what I said.` | **override** | no override |

The first is the sharpest inversion available: `observe` bumps
`intent_version`, supersedes every active constraint and clears the message
history, so the customer's most explicit statement that a requirement stands is
what deletes it.

`_override_match` scans past a suppressed trigger rather than returning at the
first hit, so a message carrying both still overrides:

```
"Don't forget the wool, but ignore my earlier preference on colour."  -> override
```

Seven genuine retractions are asserted to still fire, including
`I'm not sure, forget what I said.` and `That's not right. Ignore my earlier
preference.`, where a negator is present but in a different clause.

### What the two fixes cost

Nothing measurable, in either direction.

| | origin/main 4e36df6 | this branch |
|---|---|---|
| public score | 0.978500 | 0.978500 |
| HR@10 / MRR / MTTC | 1.0000 / 0.996667 / 2.025 | 1.0000 / 0.996667 / 2.025 |
| intent_override (30) | HR 1.0000, MRR 1.000000, MTTC 3.866667 | identical |
| robustness `summary` | | byte-identical |
| robustness `comparison` | | byte-identical |
| robustness `gate_failures` | 6 pre-existing | identical, none added |
| tests | 379 | 390 |

That the robustness report is byte-identical is expected and worth stating
plainly: **nothing in retrieval reads `excluded_values` today**. Constraint
polarity reaches the customer-facing turn record and nothing else. So these are
correctness fixes whose live effect is on what a person is told and on typed
storefront input, not on the leaderboard number. They are cheap and they cannot
move the score in either direction, which is the argument for taking them
during a freeze rather than the argument that they win anything.

## Recorded, not fixed

### F3 Verb-sense ambiguity still fires a false override

```
"Drop it in my basket if it's under $50."      -> override
"Cancel that shipping upgrade, not my preference." -> override
```

`drop` and `cancel` are retraction verbs here only by coincidence of sense.
Distinguishing them needs a list of exempt objects, which is a phrase list, so
it is out of scope for this pass. Lower severity than F2: neither reads as the
customer reinforcing a requirement.

### F4 Negation surfaces that carry no negator the extractor knows

```
"I don't like black."     -> color:black POSITIVE
"I don't need leather."   -> material:leather POSITIVE
"I never wear black."     -> color:black POSITIVE
"anything except black"   -> color:black POSITIVE
"black is out"            -> color:black POSITIVE
"I hate black."           -> color:black POSITIVE
```

`NEGATION_RE` carries `don'?t want`, which hardcodes one verb where the
negation is actually on the auxiliary. Generalising to `(?:do|does|did)n't
<verb>` is a grammar rule and would be in scope, but it inverts idioms that
mean the opposite: `I don't mind black` and `I wouldn't say no to black` would
both become exclusions. Correcting that needs an exemption list. Left alone
rather than half-done under a freeze.

### F5 Mixed-language requests reach the belief state empty

```
"Busco unas botas de cuero."                    -> no constraints
"Je cherche des bottes en cuir."                -> no constraints
"Oubliez ce que j'ai dit, je veux du coton."    -> no override, no constraints
"No, mejor de lona, not leather."               -> material:leather NEG only
```

`ATTRIBUTE_VOCABULARY` and `EXPLICIT_OVERRIDE_RE` are English. Both a value
vocabulary and a retraction trigger in another language are phrase lists by
construction, so neither is in scope today. Note separately that the
multi-language module built for #24 is **not on `origin/main`**: `needle/
language.py`, its two test files and the `set_language` wiring did not survive
the squash into #28, and nothing on main references them. That is a merge
decision for the release owner, not a red-team fix.

### F6 Coordinated values on one attribute collapse to the last one

```
"I want a black and white striped shirt."  -> color:white only
```

Positives supersede by attribute, so the second colour replaces the first.
This is the designed rule and it is right for a correction; it is wrong for a
genuine conjunction, and the two are not separable from the surface. Changing
it would need multi-valued positive constraints, which is a data-model change
and not a freeze-week edit.

### F7 Only the first budget in a message is read, and budget ignores negation

```
"Under $50. Actually, up to $200."      -> budget 50
"Not under $50, more like $200."        -> budget 50
"I want it under $50 but no more than $30." -> budget 50
```

`BUDGET_RE.search` takes the first match and the result is unconditionally
POSITIVE, so an in-message budget correction is lost. A later turn does
supersede correctly, so this is confined to one message. No public session
phrases a budget this way.

## Reproduction

```bash
python3 -m pytest tests/test_negation_scope.py tests/test_negated_override_trigger.py
python3 scripts/evaluate.py --output results.json
python3 scripts/run_robustness.py --agent starter.agent:Agent
```

Pins: base `4e36df6`, official `local_evaluator.py` at source commit
`34078351e1c3615e5505a2e829600b56a542e462`, Python 3.12, macOS, stdlib only,
zero tokens.
