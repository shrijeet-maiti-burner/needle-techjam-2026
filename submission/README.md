# Submission run notes

Status: selected development primary; source-only and asset-bundled official rehearsals passed.

## Environment

- Python: 3.10 or later; verified on CPython 3.10.5, the interpreter the release was built and reproduced under
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

The versioned signature index is a startup optimisation, not a requirement. It
is bound to a specific catalog by SHA-256. If it is absent, unreadable, or was
built against any other catalog, the agent records the reason in
`CatalogIndex.signature_index_fallback` and rebuilds the equivalent index in
process. The asset is bound to two things, and both are checked at load. It is bound to
the catalog by SHA-256, and it is bound to the parser that produced it, because
it stores this repository's own parse of every product: `build_signature_index`
writes `product_clarification_facets` for all 50,000, and that calls
`needle.state.extract_constraints`. A change to the negation or vocabulary rules
therefore makes the stored facets wrong while leaving the catalog binding and
the schema intact, so `facet_parser_sha256` records which rules produced them
and a mismatch retires the asset the same way a wrong catalog does.

Current asset, schema 9, 71,241,728 bytes:

| | |
|---|---|
| `catalog_sha256` | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| `facet_parser_sha256` | `6a56e3549d6da62b017546a5393ce59acfa49ebaae1049b967e0917998437bca` |
| product signature rows | 897,046 |
| distinct category-bound card keys | 177,768 |
| popularity-ordered card rows | 296,951 |
| clarification facet rows | 50,000 |

The file's own SHA-256 is deliberately not the reproducibility contract. Two
builds of identical content can differ byte for byte, so the table above is what
a rebuild is checked against, and the metadata above is what the loader checks.
An earlier revision of this file pinned a file hash that no longer reproduced,
which under the submission rules is the kind of thing that gets a bundle treated
as unreproducible.

Construction with the bundled index takes 2.895s and peaks at 208.8MB; the
in-process rebuild takes 27.870s and peaks at 287.7MB on the measured release machine.
Both reproduce TechnicalScore 0.978500, and construction happens once per
evaluation run rather than per session. A stale index is never trusted.

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
then writes the zip and manifest. The verified archive must write zero stderr
and reproduce TechnicalScore 0.978500. Its external SHA-256 and byte size are
recorded in the final evidence record because embedding an archive hash inside
the archive would be self-referential. Rebuild the asset from the exact scoring
catalog and rerun the bundle command immediately before upload.

```text
python scripts/build_submission_bundle.py \
  --asset .artifacts/indexes/catalog-signatures.sqlite3 \
  --output .artifacts/releases/needle-submission.zip
```
