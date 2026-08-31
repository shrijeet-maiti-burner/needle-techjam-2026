# Needle Storefront

The storefront is a local conversational interface with two explicit modes. The default product mode uses the selected primary agent as a candidate generator and adds catalog-grounded state for multi-item journeys. `--benchmark-mode` uses the exact one-target session shape measured by the official evaluator. A person can therefore test behaviour the 200 released sessions never produce without presenting that product overlay as a benchmark result.

It is the interactive counterpart to [Needle Lens](NEEDLE_LENS.md). The lens replays a released public sample through the official simulator and certifies what the agent decided. The storefront has no simulator, no ground truth and no script: the input is a person.

## Run it

Bootstrap the participant kit and build the catalog asset first, then start the server:

```bash
python scripts/bootstrap.py
python scripts/build_signature_index.py
python scripts/needle_storefront.py --warm
```

Open `http://127.0.0.1:8770`. `--warm` builds the agent before serving instead of on the first message; without it the first turn pays the construction cost.

To explore a different configuration:

```bash
python scripts/needle_storefront.py --set adaptive_slate=false --set slate_size=10
```

The value is read as JSON, so `false` is a bool and `10` an int. A keyword the installed `Agent` does not accept is refused at startup rather than ignored.

To inspect only the scored session shape:

```bash
python scripts/needle_storefront.py --warm --benchmark-mode
```

## What it shows

- the reply and the recommended slate, joined back to catalog display fields;
- per card: title, store, price where the catalog carries one, rating, category path, and the disclosed values that appear in that product's text, labelled with the field they appear in;
- a belief panel with active constraints, ruled-out values, and values dropped at a change of mind, plus the intent version;
- per turn: number, latency, and the attribute named in the human question; after turn ten the composer locks rather than exercising the agent's degraded-response fallback;
- an expandable decision receipt taken from the same target-blind trace as Needle Lens: the candidate funnel, ambiguity status, retrieval path, released slate size, and the catalog-derived expected value of the question;
- whether the run deviates from `PRIMARY_AGENT_KWARGS`, and whether the bundled signature index was accepted or rejected.
- in product mode, a typed plan with separate line items, shared occasion context, `all`/`either`/`avoid` groups, wearer state and a user-confirmed product anchor;
- per related product, the compatibility signals that catalog text supports, their confidence and the missing evidence limiting the claim;
- a separate journey receipt with candidate-source, merge, filter, relation-anchor and clarification-board evidence.

## Boundaries

**Frozen candidate generator, labelled product policy.** Both modes construct the agent from `PRIMARY_AGENT_KWARGS`. Product mode then unions candidates for each explicit alternative, enforces hard category/audience/constraint boundaries, and reranks with inspectable journey evidence. This is visible in the interface and trace; it is not the official `.978500` policy. Benchmark mode performs none of that overlay work. An operator override is displayed as a deviation in either mode.

**Nothing here reaches the bundle.** `storefront/` is not in `build_submission_bundle.SHIPPING_PATHS`, the same as `robustness/`. It imports from `needle`; `needle` does not import from it.

**Degradation is reported.** `Agent.respond` cannot raise by design, so a failure appears only as a slightly worse answer. `respond_failures` is read after every turn and a degraded turn is labelled in the transcript.

**The decision receipt is not reconstructed in JavaScript.** The service reads `Agent.trace_for(session_id)` after the turn succeeds and sends that exact trace beside the response. The interface selects a bounded set of fields to render; it does not recompute candidate counts, question utility, evidence, or a second confidence score.

**Compatibility is evidence-bounded.** There is no table saying that a named product pair goes together. The service compares catalog-derived style, wearer, occasion and color evidence using a general color-space calculation. A missing field lowers confidence and appears as a limitation. An unconfirmed top proposal may seed exploration, but the interface calls it a proposal; clicking **Use in plan** makes it a confirmed relation anchor.

**Ambiguity is preserved.** `blue or white` becomes an `either` group and each branch receives a retrieval query. A new category creates a new line item rather than resetting the old one. Wearer values come from the catalog taxonomy; when the slate spans audiences and the shopper did not specify one, the next question asks instead of guessing.

**Multilingual scope stays bounded.** Product mode persists one of the seven supported reply languages for the session and uses the same fixed phrase tables as the agent. Its partial shopping-noun lexicon maps a recognized noun back through the active catalog taxonomy; an unknown noun declines rather than guesses. Free-form preferences and catalog values are not machine-translated, so this is multilingual routing and questioning, not a claim of open-domain translation.

**Matched terms are not a rank explanation.** A chip states that a value the customer disclosed appears in that product's text, compared after the same fold and tokenization retrieval uses. It is deliberately not a claim about why the product ranked where it did — BM25 field weights, the popularity prior and disclosure promotion decide that together, and the lens is where that is certified.

## Behaviours worth knowing before you demo

**A stale chip is not a bug.** Under `override_policy="retract_stated"` an override supersedes every active constraint but deliberately keeps the answers the customer gave to our questions (`needle/state.py`). So the belief panel can report a value as dropped while the text retrieval reads still contains it. Those chips are marked stale rather than hidden. On the released override sessions the retained answers stay compatible with the new intent and the policy measures 100% — see `docs/evidence/EXP_006_SHAPES.md`. In free text they need not be compatible: "ignore my earlier preference, I need a leather belt" keeps an earlier "soft cotton" and can return a cotton product. This is a known consequence of a measured decision, not a defect to patch around in the interface.

**A single-product slate is expected early.** `adaptive_slate` with `early_slate_size=1` holds the wider slate back until turn `full_slate_turn` or `full_slate_constraints` disclosures. The interface renders a one-product slate as a spotlight and says why, rather than looking broken.

**Natural corrections are clause scoped.** A comma, spaced hyphen, en/em dash, semicolon, sentence boundary, or contrastive conjunction ends the preceding negation scope. Thus `no black - make it blue` records `black` as excluded and `blue` as active. This rule is shared by every catalog-derived attribute value; it is not a color-specific demo phrase.

## Concurrent smoke gate

With a warm `--benchmark-mode` storefront running, exercise the exact scored
HTTP boundary rather than only the service object:

```bash
python scripts/storefront_smoke.py --clients 12 --max-p95-ms 750
```

Run the product-level adversarial gate against the real catalog separately:

```bash
python scripts/journey_redteam.py
```

It covers multi-item preservation, catalog-derived audience clarification, alternative constraints, explicit selection, relation evidence, correction scope, comparison-state immutability, vague exploration, category integrity, degradation and the ten-card contract. It does not emit or imply an official score.

The gate fails on a degraded turn, empty slate, malformed response, missing
target-blind trace, bad error status, accepted eleventh turn, or p95 latency
above the supplied ceiling. The freeze run completed 36 traced turns in 6.62s
at p50 140.6ms, p95 430.0ms, and max 820.3ms; error paths and turn budget passed.

## Interface notes

Single HTML file, no build step, no package, no network, no font or asset fetch. Everything user- or catalog-supplied is written through `textContent`; no path builds markup from either. The server binds the loopback interface only and is not written to be exposed to a network.

The release-candidate interface was rendered in headless Chrome at 1440x1000 and a 390x844 mobile viewport. Both dimensions reported `scrollWidth == clientWidth`; the live two-turn correction flow displayed two decision receipts, active `blue`, excluded `black`, and no degraded turn. This is browser evidence for the tested Chromium build, not a blanket cross-browser claim.
