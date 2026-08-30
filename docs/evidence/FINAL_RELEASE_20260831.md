# Final merged release evidence — 31 August 2026

## Scope

This is the final rerun after grounded messages, catalog-derived clarification
choices, the storefront, and the target-blind Needle Lens were merged. The
runtime under test is commit `687cfac`; this record and the latency correction
in `submission/REPORT.md` are documentation-only changes after that pin.

## Official released set

Command:

```bash
python scripts/run_experiment.py \
  --experiment-id FINAL-MERGED-MAIN \
  --agent starter.agent:Agent \
  --network-state disabled
```

| Metric | Result |
|---|---:|
| Sessions | 200 |
| TechnicalScore | 0.978500 |
| HR@10 | 1.000000 |
| MRR | 0.996667 |
| MTTC | 2.025 |
| Contract violations | 0 / 405 responses |
| Response latency p50 / p95 / p99 / max | 64.3 / 218.9 / 331.7 / 733.8 ms |

These are development measurements on the released set, not a private-score
estimate or a winning claim.

## Tests and clean bundle

- `python -m unittest discover -s tests -v`: 379 passed, three skipped because
  the generated bundled index is intentionally absent from the tracked tree;
- the release builder copied only tracked shipping paths, injected the
  catalog-bound schema-6 index, and reproduced the official metrics above from
  an empty staging tree;
- `python scripts/bundle_rehearsal.py`: ten turns completed with non-empty,
  in-catalog slates and no recorded degradation;
- the resulting archive contained 24 entries and no `.artifacts/`, `data/`, or
  `evaluator/` path.

## Registered robustness rerun

Command:

```bash
python scripts/run_robustness.py --agent starter.agent:Agent
```

Report: `results/robustness/20260830T182702Z-687cfac3/report.json` (ignored raw
artifact). The baseline reproduced HR@10 1.000000, MRR 0.996667, and MTTC 2.025.

Ten meaning-preserving slices had zero target removal: accents, casing,
contraction, filler, number formatting, override paraphrase, politeness,
punctuation, synonym substitution, and whitespace. Six preregistered gates
remain unresolved:

| Slice | Meaning | Changed sessions | HR@10 | Target-removal rate |
|---|---|---:|---:|---:|
| paraphrase | preserving | 200 | 0.990 | 0.010000 |
| typo | preserving | 200 | 0.990 | 0.010000 |
| word order | preserving | 158 | 0.990 | 0.012658 |
| negation | changing | 156 | 0.995 | 0.006410 |
| attribute swap | changing | 200 | 0.960 | 0.040000 |
| constraint drop | changing | 200 | 0.965 | 0.035000 |

The gate is deliberately strict: no changed sample may remove a target that
the baseline surfaced. The three preserving failures are real robustness
limits. The three meaning-changing failures show that changing the reconstructed
intent card can make the original target disappear; they remain failures under
the registered zero-removal gate and are not relabelled as successes.

## Release decision

Keep the selected primary. The final additions are response explanation and
diagnostic surfaces; they do not change the measured ranking policy. No late
retrieval arm replaces the eight-set-selected primary without new disjoint-set
evidence. The unresolved robustness slices remain explicit limitations for the
submission and demo rehearsal.
