# Needle Storefront

The storefront is a local conversational interface driven by the selected primary agent. A person types whatever they like and the agent answers, so behaviour the 200 released sessions never produce can be found before a judge finds it.

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

## What it shows

- the reply and the recommended slate, joined back to catalog display fields;
- per card: title, store, price where the catalog carries one, rating, category path, and the disclosed values that appear in that product's text, labelled with the field they appear in;
- a belief panel with active constraints, ruled-out values, and values dropped at a change of mind, plus the intent version;
- per turn: number, latency, `ask_attribute`, and whether the turn is still inside the scored ten-turn budget;
- whether the run deviates from `PRIMARY_AGENT_KWARGS`, and whether the bundled signature index was accepted or rejected.

## Boundaries

**One policy.** The agent is constructed from `PRIMARY_AGENT_KWARGS`. There is no demo-only ranking path, no re-ranking for presentation, and no product the agent did not return. An operator override is displayed as a deviation, because a demo quietly running a different configuration from the scored one is worse than no demo.

**Nothing here reaches the bundle.** `storefront/` is not in `build_submission_bundle.SHIPPING_PATHS`, the same as `robustness/`. It imports from `needle`; `needle` does not import from it.

**Degradation is reported.** `Agent.respond` cannot raise by design, so a failure appears only as a slightly worse answer. `respond_failures` is read after every turn and a degraded turn is labelled in the transcript.

**Matched terms are not a rank explanation.** A chip states that a value the customer disclosed appears in that product's text, compared after the same fold and tokenization retrieval uses. It is deliberately not a claim about why the product ranked where it did — BM25 field weights, the popularity prior and disclosure promotion decide that together, and the lens is where that is certified.

## Two behaviours worth knowing before you demo

**A stale chip is not a bug.** Under `override_policy="retract_stated"` an override supersedes every active constraint but deliberately keeps the answers the customer gave to our questions (`needle/state.py`). So the belief panel can report a value as dropped while the text retrieval reads still contains it. Those chips are marked stale rather than hidden. On the released override sessions the retained answers stay compatible with the new intent and the policy measures 100% — see `docs/evidence/EXP_006_SHAPES.md`. In free text they need not be compatible: "ignore my earlier preference, I need a leather belt" keeps an earlier "soft cotton" and can return a cotton product. This is a known consequence of a measured decision, not a defect to patch around in the interface.

**A single-product slate is expected early.** `adaptive_slate` with `early_slate_size=1` holds the wider slate back until turn `full_slate_turn` or `full_slate_constraints` disclosures. The interface renders a one-product slate as a spotlight and says why, rather than looking broken.

## Interface notes

Single HTML file, no build step, no package, no network, no font or asset fetch. Everything user- or catalog-supplied is written through `textContent`; no path builds markup from either. The server binds the loopback interface only and is not written to be exposed to a network.
