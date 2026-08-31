# Needle

Needle is an ambiguity-aware conversational shopping agent for TikTok TechJam 2026 Track 4. It is built to find one hidden product from a frozen 50,000-item catalog through at most ten turns, where only an exact `parent_asin` match counts.

The working thesis is **ask better, remember correctly, rank deliberately**:

- represent the active intent separately from superseded preferences;
- ask the question that is most likely to reduce decision-relevant ambiguity;
- keep rank one relevance-first while testing whether later positions should cover distinct candidate clusters;
- preserve a deterministic, offline exact-and-sparse path even if optional semantic methods are added.

This is a hypothesis, not a result. Architecture decisions are accepted only after controlled official-evaluator and robustness experiments.

## Current status

The scored path is complete and frozen. The selected primary and the pure-sparse rollback are encoded in `needle/presets.py`, and the submission archive is reproduced from a clean extraction rather than from this tree. The primary measures TechnicalScore 0.978500 on the 200 released sessions, with HR@10 1.000, MRR 0.996667, MTTC 2.025, and zero contract violations. Three 200-target, distribution-matched catalog-disjoint panels rerun from this exact tree score 0.979075, 0.965625, and 0.959900. A full registered robustness run is reported with its unresolved target-removal gates rather than being converted into a blanket robustness claim. Every response of the official run validates against the participant kit's own `agent_api_contract.json`: 405 responses, zero violations. Refusing the bundled index rebuilds an equivalent one in memory and scores identically. These are development measurements, not a private-score estimate or winning claim.

## Quick start

Python 3.10 or later is required. The baseline path uses only the standard library.

```bash
python scripts/bootstrap.py
python scripts/build_signature_index.py
python -m unittest discover -s tests -v
python scripts/evaluate.py --output results/primary.json
python scripts/run_experiment.py --experiment-id PRIMARY-CHECK --agent starter.agent:Agent --network-state disabled
```

`bootstrap.py` downloads the official participant kit, verifies its pinned SHA-256 digest, and extracts it under the ignored `.artifacts/` directory. `build_signature_index.py` creates the ignored catalog-bound development asset. `evaluate.py` runs the measured `starter.agent.Agent` preset against the unmodified official evaluator and public data.

`run_experiment.py` is the decision-grade path: it refuses dirty trees by default and writes an ignored, immutable directory containing the raw result, artifact/config fingerprints, strict-contract report, scenario metrics, latency, environment, and checksums.

## See the decision, not just the answer

Needle Lens replays released public sessions and exposes the same agent call's target-blind belief ledger, interpretation lattice, candidate funnel, ambiguity certificate, ranking evidence, and question decision:

```bash
python scripts/needle_lens.py
```

The console is dependency-free and offline. Its human-shopping question board is explicitly a diagnostic shadow; it cannot affect the measured official-simulator policy or the recommendation slate. See [`docs/NEEDLE_LENS.md`](docs/NEEDLE_LENS.md) for the faithfulness boundary.

## Repository map

```text
needle/                 production components and integration facade
starter/agent.py        strict official entry-point adapter
submission/             final-bundle entry point and run notes
scripts/                artifact bootstrap and official evaluator launcher
storefront/             conversational interface service (ships, unscored)
demo/                   local interfaces, no build step
tests/                  dependency-free contract and behavior checks
docs/                   architecture, ownership, evidence, and disclosures
```

## Conversational interface

```bash
python scripts/needle_storefront.py --warm
```

Serves a local shopping interface on `http://127.0.0.1:8770`. The frozen primary agent generates candidates; an explicitly labelled product layer adds multi-item plans, alternative constraints, user-confirmed anchors, catalog-grounded compatibility evidence, typed price/rating/review preferences and value-of-information questions. It also exposes the ranked question alternatives, correction history, evidence-bounded product comparison, seven reply languages, and accessible light/dark themes. Text fields remain searchable, while explicit numeric filters and orderings are evaluated over the complete catalog-derived category pool. Use `--benchmark-mode` to disable that layer and reproduce the one-target scored session shape. The journey layer is product evidence, not part of the reported `.978500` measurement. See [docs/STOREFRONT.md](docs/STOREFRONT.md).

## Non-negotiable rules

- do not modify the official evaluator or labels when reporting public metrics;
- do not commit datasets, downloaded kits, models, generated indexes, raw results, credentials, or secrets;
- emit no more than ten unique schema-conforming recommendation objects;
- keep `main` runnable and use short-lived, owner-scoped pull requests;
- report negative and inconclusive experiments, not only favorable runs;
- never describe an unmeasured hypothesis as a score or winning result.

## Pinned official source

- repository: [`TechJam2026/techjam-conversational-search`](https://github.com/TechJam2026/techjam-conversational-search)
- source commit: `34078351e1c3615e5505a2e829600b56a542e462`
- participant-kit zip SHA-256: `b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae`
- catalog source: [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/)

Needle is the submitted project name. Repository naming is not part of the technical claim.
