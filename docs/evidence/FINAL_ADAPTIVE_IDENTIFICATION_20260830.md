# Category-bound disclosure promotion selection, 30 August 2026

Status: selected final development primary. Private performance remains unknown.

## Reproducibility boundary

- official source commit: `34078351e1c3615e5505a2e829600b56a542e462`
- evaluator SHA-256: `79a5ea06f9a1b8c5036f30efa85dc1f36b8f6b06eb8feb8f545dfa767bc45564`
- catalog SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- public-set SHA-256: `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- runtime: CPython 3.10.5, standard library only, network disabled, no model
- contract and behavior tests: 312 passed

## Selected mechanism

The official simulator builds an intent card from target-product metadata and
discloses up to four cleaned values in order. The selected production path uses
that structure without public labels:

1. schema-v6 stores every catalog product in category-bound buckets for the
   empty disclosure and every ordered one-through-four-value prefix;
2. a turn retrieves every bucket admitted by a plausible semicolon parse and
   unions the products, avoiding the unsafe choice of whichever parse happens
   to produce the smallest bucket;
3. products in that union are ordered only by catalog `rating_number`, then
   stable `parent_asin` tie-break; already emitted products are skipped;
4. any parse over the 50,000-row safety limit makes promotion decline rather
   than silently truncate the evidence set;
5. ordered promotion is disabled after intent revision; post-override direct
   identification requires the complete four-position unordered disclosure;
6. direct identification is allowed only when all resolving parses agree and
   the category-bound key names exactly one catalog product;
7. if promotion or identification declines, bounded exact-signature retrieval
   and fielded FTS5 remain in control.

Before turn 5 and four active constraints, the agent emits one item; afterward
it may emit ten. Only emitted items enter seen-item exclusion. The opening
category bucket is enabled because it adds 0.003300 on the released set; its
dependence on the released popularity distribution is recorded as a limitation.

## Official public result

```text
python scripts/run_experiment.py --experiment-id PROD-PROMOTION-V6-ENTRYPOINT --agent starter.agent:Agent --network-state disabled
```

| metric | result |
|---|---:|
| TechnicalScore | 0.978500 |
| HR@10 | 1.000000 |
| MRR | 0.996667 |
| MTTC | 2.025000 |
| responses | 405 |
| contract violations | 0 |

Every scenario has HR@10 1.0. Buying MRR is 0.991667; boundary, browsing, and
intent-override MRR are 1.0. This is released-development evidence, not a
private result.

## Ablations and transfer

The same production implementation measures 0.954400 without disclosure-bucket
promotion and 0.975200 when opening-category promotion is disabled. Removing
the separate direct-identification shortcut leaves the released result at
0.978500, so promotion, not a strict unique-key shortcut, supplies the gain.

`catalog-matched-v1` excludes all released targets and preserves released
scenario marginals while matching target-popularity and catalog-eligibility
properties. Each seed selects 200 different targets.

| seed | TechnicalScore | HR@10 | MRR | MTTC | violations |
|---|---:|---:|---:|---:|---:|
| 20260830 | 0.979075 | 1.000 | 0.996250 | 1.990 | 0 |
| 20260831 | 0.965725 | 0.990 | 0.979750 | 2.160 | 0 |
| 20260901 | 0.961950 | 0.985 | 0.978500 | 2.205 | 0 |

These panels argue against released-target memorisation. They still use our
sampler and the released simulator, so they are not private-score estimates.

## Ground-truth safety audit

`scripts/audit_identification.py` instruments both category-bound mechanisms on
all released sessions. The schema-v6 run records:

- 117 non-null direct identifications: 117 correct, 0 wrong;
- 386 non-empty disclosure-bucket promotions: target retained in 386, removed
  in 0;
- TechnicalScore 0.978500 through the same run.

The audit found and removed an earlier unsafe partial-set implementation. The
historical EXP-021 wrapper is not the runtime safety claim.

## Robustness

The full registered seed-0 matrix was run without weakening its zero-removal
threshold. The exact surface and nine perturbation slices have zero removal;
the seven failures are explicit below.

| slice | meaning | HR@10 | MRR | MTTC | target-removal rate |
|---|---|---:|---:|---:|---:|
| exact | baseline | 1.000 | 0.996667 | 2.025 | - |
| filler | preserving | 0.995 | 0.980333 | 2.195 | 0.005000 |
| paraphrase | preserving | 0.990 | 0.939667 | 2.640 | 0.010000 |
| typo | preserving | 0.990 | 0.959597 | 2.765 | 0.010000 |
| word order | preserving | 0.990 | 0.948506 | 2.440 | 0.012658 |
| negation | changing | 0.995 | 0.981339 | 2.285 | 0.006410 |
| attribute swap | changing | 0.960 | 0.871722 | 3.015 | 0.040000 |
| constraint drop | changing | 0.965 | 0.955833 | 2.360 | 0.035000 |

Casing, whitespace, punctuation, accents, synonym, politeness, contraction,
number format, and override paraphrase have zero target removal. Number format
has only one effective sample and is not strong evidence. No claim of complete
robustness is made.

## Asset and runtime

The schema-v6 asset contains 869,240 exact-signature pairs, 177,768 distinct
category-bound keys, and 296,951 popularity-ordered card rows. It is 64,884,736
bytes with SHA-256
`73c91b4473772532cc22a39918885e00898b8eadbada8544bfad84dd8e9904e4`.
It is bound to the catalog hash above. Missing, corrupt, or mismatched assets
fall back to an equivalent in-process build rather than aborting construction.

The bundled development run records 6.774s construction, 2.853s evaluation,
507,654,144 bytes peak process working set, and response latency p50/p95/p99/max
of 2.0/42.7/95.6/418.6 ms.

With the asset path forced to a verified-nonexistent file, the source-only
fallback reproduces 0.978500 with zero violations. Construction takes 84.788s
and the complete run peaks at 594,825,216 bytes. It is survivability evidence,
not the preferred deployment.

The allowlisted release builder excludes the participant kit, datasets,
evaluator, caches, results, and secrets. The clean extracted bundle writes no
stderr, reproduces 0.978500, and contains 19 tracked files plus the ignored
catalog-bound asset. The 23,967,155-byte archive has SHA-256
`80dd232a4691d4e9501bf859ba9f6e39425d873a9a6234412f282c9a4060f226`.

## Decision

Select category-bound disclosure promotion with plausible-parse union,
popularity ordering, post-override ordering guard, adaptive slate, and the
existing sparse fallback. Keep strict direct identification because its public
audit is exact, while recognising that its released score contribution is zero
after promotion. Reject broad filler and category-typo rewrites that did not
recover their official robustness failures. Carry all seven registered gate
failures into the final limitations; do not convert public or proxy measurements
into a private-score or winning claim.
