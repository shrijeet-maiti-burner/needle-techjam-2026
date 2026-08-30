# Submission run notes

Status: selected development primary; source-only and asset-bundled official rehearsals passed.

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

The schema-v5 signature index is a startup optimisation, not a requirement. It
is bound to a specific catalog by SHA-256. If it is absent, unreadable, or was
built against any other catalog, the agent records the reason in
`CatalogIndex.signature_index_fallback` and rebuilds the equivalent index in
process. The 57,683,968-byte asset contains 869,240 product-signature rows and
162,190 globally unique category-bound card keys. It has SHA-256
`c3142af7d33e2ef1b6eaca66d112d6a372b5cf47546883aa6bfc4916d058b5c2`.
The isolated bundled construction takes 7.561s. The slower source-only fallback
takes 83.755s on the recorded machine; both paths reproduce TechnicalScore
0.955233. A stale index is never trusted.

Rebuild it for a given catalog with:

```
python scripts/build_signature_index.py
```

## Packaging

The final bundle includes only required source, helper modules, dependency
instructions, report, and the catalog-bound signature asset. The participant
kit, datasets, evaluator, raw outputs, bytecode caches, secrets, and
development-only files are excluded. `scripts/build_submission_bundle.py`
copies only the allowlisted tracked paths, adds the ignored generated asset,
runs the extracted entry point against the unmodified official evaluator, and
then writes the zip and manifest. The verified archive writes zero stderr and
reproduces TechnicalScore 0.955233. Its external SHA-256 and byte size are
recorded in the final evidence record because embedding an archive hash inside
the archive would be self-referential. Rebuild the asset from the exact scoring
catalog and rerun the bundle command immediately before upload.

```text
python scripts/build_submission_bundle.py \
  --asset .artifacts/indexes/catalog-signatures.sqlite3 \
  --output .artifacts/releases/needle-submission.zip
```
