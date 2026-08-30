# Submission run notes

Status: selected development primary; source-only and asset-bundled clean rehearsals passed.

## Environment

- Python: 3.10 or later
- mandatory runtime dependencies: Python standard library only (see `requirements.txt`)
- network required for scoring: no
- credentials required: no
- official entry point: `starter.agent.Agent`
- equivalent release adapter: `submission.agent.Agent`

### Environment variables

`NEEDLE_SIGNATURE_INDEX` (optional). Read by `starter/agent.py` to override the
signature index location. Without an override, the starter automatically uses
`submission/assets/catalog-signatures.sqlite3` when present, otherwise the
development path `.artifacts/indexes/catalog-signatures.sqlite3`. If neither is
present, the agent rebuilds the equivalent index in process.

## Running in the official harness

The official evaluator imports `starter.agent.Agent`, so the submitted agent is
exposed through `starter/agent.py`, which re-exports the same configuration as
`submission/agent.py`. From the participant kit root, with this repository's
modules importable:

```
python -m evaluator.local_evaluator \
  --catalog data/catalog.jsonl \
  --dataset data/public_set.jsonl \
  --output results.json
```

There is no `scripts/evaluate.py` in the participant kit. An earlier revision of
this file documented one, which would have made the bundle unreproducible under
the submission rules.

For the instrumented internal run that also records provenance and the contract
report, from this repository root:

```
python scripts/run_experiment.py \
  --experiment-id RUN-001 \
  --agent starter.agent:Agent \
  --network-state disabled
```

Note the capitalisation: the exported symbol is `Agent`, not `agent`.

## Bundled asset

- optional asset: `submission/assets/catalog-signatures.sqlite3`

The schema-v2 signature index is a startup optimisation, not a requirement. It
is bound to a specific catalog by SHA-256. If it is absent, unreadable, or was
built against any other catalog, the agent records the reason in
`CatalogIndex.signature_index_fallback` and rebuilds the equivalent index in
process. The 49,860,608-byte asset contains 869,240 product-signature rows and
has SHA-256 `646fcd647a2a78cf00daf7998edd6d7c57c8a4d87000f1b888685b2e4864de9c`.
Measured construction is 5.125s with the asset and 40.614s without it; both
paths reproduce TechnicalScore 0.887527. A stale index is never trusted.

Rebuild it for a given catalog with:

```
python scripts/build_signature_index.py
```

## Packaging

The final bundle includes only required source, helper modules, dependency
instructions, and the catalog-bound signature asset. The participant kit,
datasets, evaluator, raw outputs, secrets, and development-only files must not
be packaged. A clean source-only `git archive` at commit `5a61c1a` rebuilt the
missing index and reproduced TechnicalScore 0.887527. The verified release
layout adds the generated asset at
`submission/assets/catalog-signatures.sqlite3`: 50,221,823 bytes across 76
files, zero stderr, and the same 0.887527 score. Rebuild the asset from the exact
scoring catalog and repeat this clean extracted-bundle command before upload.
