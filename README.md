# Needle

Needle is an ambiguity-aware conversational shopping agent for TikTok TechJam 2026 Track 4. It is built to find one hidden product from a frozen 50,000-item catalog through at most ten turns, where only an exact `parent_asin` match counts.

The working thesis is **ask better, remember correctly, rank deliberately**:

- represent the active intent separately from superseded preferences;
- ask the question that is most likely to reduce decision-relevant ambiguity;
- keep rank one relevance-first while testing whether later positions should cover distinct candidate clusters;
- preserve a deterministic, offline exact-and-sparse path even if optional semantic methods are added.

This is a hypothesis, not a result. Architecture decisions are accepted only after controlled official-evaluator and robustness experiments.

## Current status

H0 began on 29 August 2026 at 12:00 SGT. The contract-valid integration path is complete and a measured public-development candidate plus pure-sparse rollback are encoded in `needle/presets.py`. The candidate is not frozen: deterministic wording perturbations still regress, question-policy experiments remain open, and the generated signature asset has not completed final clean-bundle validation.

## Quick start

Python 3.10 or later is required. The baseline path uses only the standard library.

```bash
python scripts/bootstrap.py
python scripts/build_signature_index.py
python -m unittest discover -s tests -v
python scripts/evaluate.py --output results/primary.json
python scripts/run_experiment.py --experiment-id PRIMARY-CHECK --agent starter.agent:Agent --network-state enabled
```

`bootstrap.py` downloads the official participant kit, verifies its pinned SHA-256 digest, and extracts it under the ignored `.artifacts/` directory. `build_signature_index.py` creates the ignored catalog-bound development asset. `evaluate.py` runs the measured `starter.agent.Agent` preset against the unmodified official evaluator and public data.

`run_experiment.py` is the decision-grade path: it refuses dirty trees by default and writes an ignored, immutable directory containing the raw result, artifact/config fingerprints, strict-contract report, scenario metrics, latency, environment, and checksums.

## Repository map

```text
needle/                 production components and integration facade
starter/agent.py        strict official entry-point adapter
submission/             final-bundle entry point and run notes
scripts/                artifact bootstrap and official evaluator launcher
tests/                  dependency-free contract and behavior checks
docs/                   architecture, ownership, evidence, and disclosures
```

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

The product codename is provisional. Repository naming is not part of the technical claim.
