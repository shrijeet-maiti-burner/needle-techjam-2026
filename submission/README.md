# Submission run notes

Status: development scaffold, not a release candidate.

- Python: 3.10 or later
- mandatory runtime dependencies: Python standard library only
- network required for scoring: no
- credentials required: no
- entry point: `submission.agent.Agent`
- local official-harness command from repository root: `python scripts/evaluate.py --output results/official.json`

The final bundle will include only required source, helper modules, dependency instructions, and approved lightweight assets. The participant kit, datasets, evaluator, raw outputs, generated indexes, secrets, and development-only files must not be packaged.
