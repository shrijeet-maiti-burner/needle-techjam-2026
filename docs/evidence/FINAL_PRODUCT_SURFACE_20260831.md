# Final product-surface and archive verification — 31 August 2026

## Scope

Source commit `1023207` adds typed catalog-property behavior only to the
optional storefront. The official `starter.agent:Agent` import graph and
`PRIMARY_AGENT_KWARGS` are unchanged. This record separates product evidence
from the released-set score; neither predicts private judging or a win.

## Product behavior closed

- all catalog text fields remain searchable: title, features, description,
  details, categories and store;
- price, average rating and review count have typed lower, upper and bounded
  filters with strict/inclusive boundary semantics;
- explicit cheapest, most expensive, least/most reviewed and lowest/best-rated
  requests order the complete catalog-derived category pool rather than the
  first returned slate;
- best-rated ordering uses a disclosed empirical-Bayes average weighted by
  review count, so one raw five-star review does not automatically win;
- missing numeric facts cannot satisfy a hard filter and sort after stated
  facts for an ordering;
- quantity and measurement language such as `up to 3 pairs` and `up to 30mm`
  cannot become a price;
- a multiword category requires every category token, preventing running socks
  from entering a running-shoe slate;
- catalog taxonomy is authoritative when title audience text conflicts with
  the filed department;
- a product-mode preference retraction rotates only the active line item's
  retrieval session and clears its live selection/question cache, while the
  scored benchmark mode keeps its measured override policy.

## Verification

| gate | result |
|---|---|
| `python -m compileall -q needle starter submission scripts tests robustness storefront` | pass |
| `python -m unittest discover -s tests -v` | 568 run; 565 pass; three expected pre-archive asset checks skipped |
| `python scripts/journey_redteam.py` | pass on the real 50,000-product catalog, including numeric ranking and category integrity |
| `python scripts/storefront_smoke.py --clients 12 --max-p95-ms 750` | 36 turns in 3.08s; p50 63.4ms; p95 191.9ms; max 386.4ms; error and turn-budget paths pass |
| official released evaluator | 200 sessions; HR@10 1.000000; MRR 0.996667; MTTC 2.025; TechnicalScore 0.978500; zero model tokens |
| `python scripts/bundle_rehearsal.py` | ten turns; every slate non-empty and catalog-valid |
| tracked Markdown local-link and strict UTF-8 scan | pass |
| `git diff --check` | pass |

The base interface at `cac5a30` has recorded rendered Chrome evidence at
1440x1000 and 390x844. The additive numeric receipt and plan chips pass the
static no-`innerHTML` artifact gate, but a fresh rendered desktop/mobile pass
was not possible in this session because no browser connection was available.
That remains a manual pre-upload gate and is not represented as complete.

## Verified archive

| field | value |
|---|---|
| path | `.artifacts/releases/needle-submission-final-1023207.zip` |
| SHA-256 | `8d8aafed5ff521fbf31228993492a8c3afa899c5d13dc6c0d0cf0e5ad935810b` |
| size | 25,606,971 bytes |
| tracked shipping files | 35 |
| entry point | `starter.agent:Agent` |
| generated asset | schema 9; 71,241,728 bytes |
| asset catalog binding | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| asset parser binding | `6a56e3549d6da62b017546a5393ce59acfa49ebaae1049b967e0917998437bca` |

The archive contains `storefront/preferences.py`, `demo/storefront.html`,
`submission/REPORT.md` and `MANIFEST.json`. The builder evaluated the extracted
entry point against the official public harness before writing the archive.

## Remaining human gates

1. Render the final numeric interface once on desktop and a narrow mobile
   viewport; check overflow, receipt readability, keyboard flow and active-card
   controls.
2. Have every contributor confirm that `docs/SUBMISSION_DISCLOSURES.md` lists
   every development tool, API, library/framework, dataset and asset they used.
3. Use the verified archive above for upload unless any shipped file changes.
   Any shipped change invalidates its hash and requires the full build again.
