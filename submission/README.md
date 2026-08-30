# Submission run notes

Status: selected development primary; source-only clean-bundle rehearsal passed.

## Environment

- Python: 3.10 or later
- mandatory runtime dependencies: Python standard library only (see `requirements.txt`)
- network required for scoring: no
- credentials required: no
- entry point: `submission.agent.Agent`

### Environment variables

`NEEDLE_SIGNATURE_INDEX` (optional). Read by `starter/agent.py` to override the
signature index location. If unset it defaults to
`.artifacts/indexes/catalog-signatures.sqlite3`, which is a development path
excluded from the bundle, so in a packaged bundle the default will not resolve
and the agent rebuilds the index in process. Set it to
`submission/assets/catalog-signatures.sqlite3` to use the bundled asset and skip
the rebuild. Nothing fails either way; the only difference is startup time.

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

The signature index is a startup optimisation, not a requirement. It is bound to
a specific catalog by SHA-256. If it is absent, unreadable, or was built against
any other catalog, the agent logs the reason to
`CatalogIndex.signature_index_fallback` and rebuilds the equivalent index in
process. Measured: identical TechnicalScore on the 200 public sessions either
way, with construction at roughly 1.5s using the bundled asset and 8.2s
rebuilding. The stale index is never trusted, only ever discarded and rebuilt.

Rebuild it for a given catalog with:

```
python scripts/build_signature_index.py
```

## Packaging

The final bundle includes only required source, helper modules, dependency
instructions, and optionally the catalog-bound signature asset. The participant
kit, datasets, evaluator, raw outputs, secrets, and development-only files must
not be packaged. A clean source-only `git archive` at commit `531ad33b` rebuilt
the missing index and reproduced TechnicalScore 0.878039. Before release,
rebuild any optional asset from the exact scoring catalog, verify its catalog
binding and SHA-256, and repeat the evaluator command from a clean extracted
bundle.
