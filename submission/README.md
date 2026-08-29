# Submission run notes

Status: measured development candidate, not a frozen release.

- Python: 3.10 or later
- mandatory runtime dependencies: Python standard library only
- network required for scoring: no
- credentials required: no
- entry point: `submission.agent.Agent`
- required bundled asset: `submission/assets/catalog-signatures.sqlite3`
- local official-harness command from repository root: `python scripts/evaluate.py --output results/official.json`

The final bundle will include only required source, helper modules, dependency instructions, and the approved catalog-bound signature asset. The participant kit, datasets, evaluator, raw outputs, secrets, and development-only files must not be packaged. Before release, rebuild the asset from the exact scoring catalog, verify its catalog binding and SHA-256, and run the evaluator from a clean extracted bundle.
