# Contributing

The build window is short; every change must remain reviewable, reversible, and reproducible.

## Workflow

1. Accept the GitHub invitation and clone this repository.
2. Run `python scripts/bootstrap.py` and `python -m unittest discover -s tests -v`.
3. Create a short-lived branch from current `main` using the prefixes below.
4. Change one concern only and add focused tests or an experiment record.
5. Open a pull request; do not commit directly to `main`.

Branch prefixes:

- `state/` — Athul
- `semantic/` or `robustness/` — Aryaman
- `evaluation/`, `reliability/`, or `submission/` — Yazhiniyan
- `retrieval/` or `integration/` — Shrijeet
- `docs/` — focused shared documentation

## Pull-request evidence

A technical pull request must state:

- the experiment ID or exact correctness check;
- the command and configuration used;
- code, official source, evaluator, and data pins;
- aggregate and scenario-slice effects where applicable;
- latency, memory, dependency, and offline impact where applicable;
- known regressions, limitations, and rollback path.

Do not merge a public-score gain that fails the registered robustness or contract gate. Do not resolve a conflict by silently dropping another owner's behavior or evidence.

## Required checks

```bash
python -m compileall -q needle starter submission scripts tests robustness
python -m unittest discover -s tests -v
git diff --check
```

The official evaluator must also complete before an integration or release-candidate merge.

Use `scripts/run_experiment.py` for decision-grade runs. Dirty-tree runs require the explicit `--allow-dirty` flag and remain diagnostic only.
