# Final product-surface and archive verification - 31 August to 1 September 2026

## Scope

Source commit `44fb1c3` is the final shipped-code snapshot. The optional
storefront adds a catalog-grounded shopping journey, structured numeric
preferences, evidence traces and comparison controls. The official
`starter.agent:Agent` entry point and measured `PRIMARY_AGENT_KWARGS` remain
unchanged. These results establish reproducibility on the public evaluator;
they do not predict the private evaluation or guarantee a placement.

## Product behavior closed

- all catalog text fields remain searchable: title, features, description,
  details, categories and store;
- price, average rating and review count support typed lower, upper and bounded
  filters with strict and inclusive boundary semantics;
- explicit cheapest, most expensive, least or most reviewed, and lowest or
  best-rated requests order the complete catalog-derived category pool rather
  than the first returned slate;
- high-rating language such as `highly rated`, `well reviewed`, `5 star` and
  `rated 4.5 or higher` is parsed as a field and operator, not as a product- or
  threshold-specific exception;
- best-rated ordering uses a disclosed empirical-Bayes average weighted by
  review count, so one raw five-star review does not automatically win;
- explicit numeric filtering or ordering produces a direct result instead of
  asking an unrelated clarification question;
- missing numeric facts cannot satisfy a hard filter and sort after stated
  facts for an ordering;
- quantity and measurement language such as `up to 3 pairs` and `up to 30mm`
  cannot become a price;
- multiword categories require every category token, preventing running socks
  from entering a running-shoe slate;
- catalog taxonomy is authoritative when title audience text conflicts with
  the filed department;
- natural corrections remove retired terms from retrieval as well as from
  visible state;
- journey mode preserves shared occasion context across related line items,
  records compatibility evidence, and disables stale product actions;
- language, theme, comparison and alternative-question controls are usable
  without changing the scored agent path;
- no product identifier, evaluator target or fixed catalog answer is embedded
  in production retrieval or storefront code.

## Verification

| gate | result |
|---|---|
| `python -m compileall -q needle starter submission scripts tests robustness storefront` | pass |
| `python -m unittest discover -s tests` | 589 run; 586 pass; three expected asset-dependent checks skipped |
| focused preference and journey suites | 70 tests pass |
| `python scripts/journey_redteam.py` | pass on the real 50,000-product catalog, including rating language, numeric ranking, correction and category integrity |
| `python scripts/storefront_smoke.py --clients 12 --max-p95-ms 750` | 36 turns in 2.99s; p50 65.9ms; p95 185.6ms; max 372.9ms; error and turn-budget paths pass |
| official public evaluator | 200 sessions; HR@10 1.000000; MRR 0.996667; MTTC 2.025; TechnicalScore 0.978500; zero reported model tokens |
| `python scripts/bundle_rehearsal.py` | ten turns; every slate non-empty and catalog-valid |
| clean extracted archive, official evaluator | exact reproduction of the public metrics above |
| clean extracted archive, `scripts/demo_session.py` | intent-override scenario completes with the participant kit supplied only through `TECHJAM_KIT_ROOT` |
| clean extracted archive, `scripts/needle_storefront.py --warm` | HTTP interface and configuration endpoints return 200; bundled signature index accepted with no fallback; construction 4.56s |
| archive-local runbook, link, secret, unfinished-marker and network-import scans | pass |
| tracked Markdown local-link, fence, heading and strict UTF-8 scans | pass |
| unsafe browser-sink and external-network scans | pass |
| `git diff --check` | pass |

Rendered Chrome checks cover desktop and mobile widths in both themes, with
measured text contrast of at least 4.5:1 down to 10.5px. Static DOM,
accessibility, responsive-layout and injection-sink tests also pass, and the
team completed a manual desktop/mobile walkthrough. A second browser engine
was not tested.

## Verified archive

| field | value |
|---|---|
| path | `.artifacts/releases/needle-submission-final-44fb1c3.zip` |
| SHA-256 | `101f63b4094ba3df04367f2e015ac74633ab8dc51307c94c505bfd3518c69438` |
| size | 25,613,472 bytes |
| tracked shipping files | 36 |
| entry point | `starter.agent:Agent` |
| generated asset | schema 9; 71,241,728 bytes |
| asset SHA-256 | `f98fdce51ec6603724ab84b274e2223bf6c32a375e7a4e87e3a0330df1fa2ec5` |
| asset catalog binding | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| asset parser binding | `6a56e3549d6da62b017546a5393ce59acfa49ebaae1049b967e0917998437bca` |

The archive contains `storefront/preferences.py`, `demo/storefront.html`,
`submission/REPORT.md`, `scripts/run_official.py`, the self-contained archive
runbook at both `README.md` and `submission/README.md`, and `MANIFEST.json`.
The builder evaluated the extracted entry point against the official public
harness before writing the archive. A second clean extraction outside the
repository reproduced the evaluator result, the documented demo command, and
the optional storefront using the bundled index.

## Submission handoff

1. Upload exactly the verified archive above. Any shipped-file change requires
   a new clean build, evaluator run, extraction rehearsal and hash.
2. Copy the truthful inventory in `docs/SUBMISSION_DISCLOSURES.md` into the
   Devpost project description, including development tools, APIs, libraries
   and frameworks, datasets and assets actually used.
3. Use the verified desktop journey for the video and live demo. Keep the
   public evaluator result separate from claims about private performance.
4. Freeze code. Remaining work is submission assembly, link verification,
   video capture and a final upload/download hash comparison.
