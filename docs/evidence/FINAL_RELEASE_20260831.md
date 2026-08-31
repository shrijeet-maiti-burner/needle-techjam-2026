# Final merged release evidence — 31 August 2026

## Scope

This is the final release-candidate rerun after grounded messages,
catalog-derived clarification choices, clause-scoped human corrections, the
storefront decision receipt, and the target-blind Needle Lens were integrated.
The working tree is intentionally not labelled as a frozen commit until the
release PR is reviewed; the experiment runner records its dirty-tree fingerprint.

## Official released set

Command:

```bash
python scripts/run_experiment.py \
  --experiment-id FINAL-HUMAN-LOOP-TOKEN-CACHE \
  --agent starter.agent:Agent \
  --network-state disabled \
  --allow-dirty
```

| Metric | Result |
|---|---:|
| Sessions | 200 |
| TechnicalScore | 0.978500 |
| HR@10 | 1.000000 |
| MRR | 0.996667 |
| MTTC | 2.025 |
| Contract violations | 0 / 405 responses |
| Response latency p50 / p95 / p99 / max | 6.529 / 147.513 / 254.434 / 631.962 ms |

These are development measurements on the released set, not a private-score
estimate or a winning claim.

## Catalog-disjoint transfer diagnostics

Three 200-target, distribution-matched panels excluded every released target
and were rerun from this exact working tree. Their TechnicalScores were
0.979075, 0.965625, and 0.959900 for seeds 20260830, 20260831, and 20260901,
respectively, with zero contract violations. They reuse the released simulator,
so they test target disjointness rather than estimating private performance.

## Tests and clean bundle

- `python -m unittest discover -s tests -v`: 429 ran, 426 passed and three
  skipped because the generated bundled index is intentionally absent from the
  tracked tree;
- the release builder copied only tracked shipping paths, injected the
  catalog-bound schema-8 index, and reproduced the official metrics above from
  an empty staging tree;
- `python scripts/bundle_rehearsal.py`: ten turns completed with non-empty,
  in-catalog slates and no recorded degradation;
- the resulting archive contained 24 entries and no `.artifacts/`, `data/`, or
  `evaluator/` path.

The verified submission archive is
`.artifacts/releases/needle-submission-final.zip`: 24,881,401 bytes, 22 tracked
source files plus the generated manifest and schema-8 asset, SHA-256
`43a5d5182e11caa5004fc23439c1bc8016827f022cc3faf7e3a874db4890bdf8`.
The builder extracted it into an empty staging tree and reproduced
TechnicalScore 0.978500 through `starter.agent:Agent` before writing the zip.

## Registered robustness rerun

Command:

```bash
python scripts/run_robustness.py --agent starter.agent:Agent
```

Report: `.artifacts/qa/robustness-freeze/20260831T040850Z-7cfd093f/report.json`
(ignored raw artifact). The baseline reproduced HR@10 1.000000, MRR 0.996667,
and MTTC 2.025.

Eleven meaning-preserving slices had zero target removal: accents, casing,
contraction, filler, number formatting, override paraphrase, politeness,
punctuation, synonym substitution, typo, and whitespace. Five preregistered
gates remain unresolved:

| Slice | Meaning | Changed sessions | HR@10 | Target-removal rate |
|---|---|---:|---:|---:|
| paraphrase | preserving | 200 | 0.995 | 0.005000 |
| word order | preserving | 158 | 0.990 | 0.012658 |
| negation | changing | 156 | 0.965 | 0.044872 |
| attribute swap | changing | 200 | 0.970 | 0.030000 |
| constraint drop | changing | 200 | 0.965 | 0.035000 |

The gate is deliberately strict: no changed sample may remove a target that
the baseline surfaced. The two preserving failures are real robustness limits;
typo keeps every target but still loses MRR. The three meaning-changing failures
show that changing the reconstructed intent card can make the original target
disappear; they remain failures under the registered zero-removal gate and are
not relabelled as successes.

## Human storefront checks

The unscripted two-turn flow was rendered in headless Chrome at 1440x1000 and
390x844. Both viewports reported `scrollWidth == clientWidth`. The correction
`Actually, no black - make it blue and lightweight.` left `blue` active,
`black` excluded, two decision receipts present, and no degraded turn. The
receipt rendered the target-blind 50,000 -> 200 -> 1 candidate funnel and the
catalog-derived question utility carried by `Agent.trace_for()`.

The freeze-hardening integration then ran 12 concurrent scripted customers
through the live HTTP service: 36 traced turns in 6.62s, p50 140.6ms, p95
430.0ms, max 820.3ms, with no degraded turn, empty slate, missing target-blind
trace, malformed response, bad error status, or accepted eleventh turn.

## Freeze-hardening state corrections

Four structural corrections were integrated after the human-loop release:
negation scope now terminates at general clause boundaries without terminating
coordination; a retraction verb governed by a negated auxiliary no longer
resets intent; catalog measurements no longer become budgets; and the final
standing price in an in-message correction wins. The official metrics remained
identical, all three catalog-disjoint panels remained 0.979075, 0.965625, and
0.959900, and the full robustness matrix retained the same five gate names.
Meaning-changing negation MTTC improved from 2.595 to 2.590; every other
comparison metric was identical.

## Release decision

Keep the selected primary. The final additions are response explanation and
diagnostic surfaces; they do not change the measured ranking policy. No late
retrieval arm replaces the eight-set-selected primary without new disjoint-set
evidence. The unresolved robustness slices remain explicit limitations for the
submission and demo rehearsal.
