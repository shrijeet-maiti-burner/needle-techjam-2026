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
- typed catalog-property intent: lower, upper and bounded filters for price, star rating and review count; and explicit lowest-price, highest-price, least/most-reviewed or confidence-adjusted lowest/best-rated ordering;
- per related product, the compatibility signals that catalog text supports, their confidence and the missing evidence limiting the claim;
- a separate journey receipt with candidate-source, merge, filter, relation-anchor, numeric-ranking method and clarification-board evidence;
- the catalog-derived alternatives the selected question outranked, plus a correction timeline when a preference was superseded;
- an evidence-bounded comparison tray for up to three products, using `not stated` rather than inventing a mismatch when metadata is absent;
- direct selection of any of the seven supported reply languages, and system/light/dark themes whose measured text contrast clears 4.5:1.

## Boundaries

**Frozen candidate generator, labelled product policy.** Both modes construct the agent from `PRIMARY_AGENT_KWARGS`. Product mode then unions candidates for each explicit alternative, enforces hard category/audience/constraint boundaries, and reranks with inspectable journey evidence. An explicit numeric filter or ordering additionally opens the complete catalog-derived category pool so `cheapest` and `best rated` do not merely reshuffle the first ten candidates. This is visible in the interface and trace; it is not the official `.978500` policy. Benchmark mode performs none of that overlay work. An operator override is displayed as a deviation in either mode.

**The storefront ships but cannot reach scoring.** `storefront/`, its launcher and the single-file interface are allowlisted into the submission archive as an optional judge-facing demonstration. The official entry point does not import them; an import-graph test fails if that boundary reverses. `robustness/` remains development-only.

**Degradation is reported.** `Agent.respond` cannot raise by design, so a failure appears only as a slightly worse answer. `respond_failures` is read after every turn and a degraded turn is labelled in the transcript.

**The decision receipt is not reconstructed in JavaScript.** The service reads `Agent.trace_for(session_id)` after the turn succeeds and sends that exact trace beside the response. The interface selects a bounded set of fields to render; it does not recompute candidate counts, question utility or compatibility evidence. For an explicit numeric ranking, the product layer additionally reports the catalog field, direction, eligible-value count and method it actually used.

**Compatibility is evidence-bounded.** There is no table saying that a named product pair goes together. The service compares catalog-derived style, wearer, occasion and color evidence using a general color-space calculation. A missing field lowers confidence and appears as a limitation. An unconfirmed top proposal may seed exploration, but the interface calls it a proposal; clicking **Use in plan** makes it a confirmed relation anchor.

**Ambiguity is preserved.** `blue or white` becomes an `either` group and each branch receives a retrieval query. A new category creates a new line item rather than resetting the old one. Wearer values come from the catalog taxonomy; when the slate spans audiences and the shopper did not specify one, the next question asks instead of guessing.

**Catalog properties have typed semantics.** `title`, `features`, `description`, `details`, `categories` and `store` are searchable text. Category and audience come from the catalog taxonomy. `price`, `average_rating` and `rating_number` are not injected as prose: they become numeric filters or explicit orderings. Each numeric field supports lower bounds, upper bounds and bounded ranges. Natural rating requests such as `highly rated`, `well reviewed` and `great reviews` use the same evidence-bounded ordering as `best rated`; explicit forms such as `rated 4.5 or higher` and `5 star` become hard rating floors. `best rated` uses an empirical-Bayes average with the category pool's review-weighted mean and median review count as its disclosed prior, preventing a single five-star review from automatically winning. A missing numeric value fails a hard filter and sorts after stated values for an ordering. Internal identifiers remain identity keys rather than recommendation features.

Supported numeric forms are deliberately bounded: comparator or range language tied to price, stars or review counts, plus the explicit ranking language named above. Vague rating language changes ordering rather than imposing an arbitrary fixed star threshold. `Good quality` is not silently equated with ratings because the catalog has no independent product-quality field. The parser rejects measurement and quantity-shaped values such as `up to 30mm` or `up to 3 pairs`; it does not claim general quantitative reasoning over arbitrary dimensions buried in free-form details.

**Multilingual scope stays bounded.** Product mode persists one of the seven supported reply languages for the session and uses the same fixed phrase tables as the agent. Its partial shopping-noun lexicon maps a recognized noun back through the active catalog taxonomy; an unknown noun declines rather than guesses. Free-form preferences and catalog values are not machine-translated, so this is multilingual routing and questioning, not a claim of open-domain translation.

**Matched terms are not a rank explanation.** A chip states that a value the customer disclosed appears in that product's text, compared after the same fold and tokenization retrieval uses. It is deliberately not a claim about why the product ranked where it did — BM25 field weights, the popularity prior and disclosure promotion decide that together, and the lens is where that is certified.

## Behaviours worth knowing before you demo

**Override semantics are isolated by mode.** Benchmark mode preserves the measured `override_policy="retract_stated"`: an override supersedes stated constraints but retains clarification answers, and stale chips remain visible for audit. Product mode cannot assume those retained answers are compatible with an arbitrary human correction. A preference retraction therefore rotates only the active line item's agent session and clears its live query, selection and question caches while retaining the superseded audit trail, product identity and other journey items.

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

It covers multi-item preservation, catalog-derived audience clarification, alternative constraints, explicit selection, relation evidence, correction scope, comparison-state immutability, vague exploration, complete-category numeric filtering and ranking, natural rating language, explicit rating floors, category integrity, degradation and the ten-card contract. It does not emit or imply an official score.

The gate fails on a degraded turn, empty slate, malformed response, missing
target-blind trace, bad error status, accepted eleventh turn, or p95 latency
above the supplied ceiling. The final benchmark-mode run completed 36 traced
turns in 2.99s at p50 65.9ms, p95 185.6ms, and max 372.9ms; error paths and
turn budget passed.

## Interface notes

Single HTML file, no frontend build step, package, network, font or asset fetch. Everything user- or catalog-supplied is written through `textContent`; no path builds markup from either. The server binds the loopback interface only and is not written to be exposed to a network.

The interface was rendered and exercised in Chrome on desktop and a narrow mobile viewport. The final interface branch passed 21 browser checks, including session reset, language switching and compare-state isolation. Both theme palettes were measured at 4.5:1 or better for interface text down to 10.5px, and the user completed the final visual confirmation after the numeric receipt and plan controls landed. Static tests additionally prohibit unsafe HTML sinks and literal surface colors. This is evidence for the tested Chromium build, not a blanket cross-browser claim; a fresh browser connection was unavailable during the final repository audit, so that audit did not claim a second independent render.
