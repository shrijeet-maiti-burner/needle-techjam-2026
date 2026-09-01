# Needle

Needle is a conversational product-retrieval system built for TikTok TechJam
2026 Track 4. The task is strict: identify one hidden product in a frozen
50,000-item catalog within ten turns, and count a hit only when the exact
`parent_asin` is returned.

Needle keeps a versioned record of what the shopper wants, distinguishes active
preferences from corrections and exclusions, retrieves only catalog-backed
products, and exposes the evidence behind each turn. Its scored path is
deterministic, offline, and implemented entirely with the Python standard
library—no model call, embedding service, vector database, credential, or
network connection is required.

## What Needle does

- preserves intent across a conversation without carrying retracted
  preferences forward;
- handles clause-scoped negation, corrections, alternatives, and explicit
  intent changes;
- combines bounded catalog signatures with fielded SQLite FTS5 retrieval and a
  small catalog-popularity prior;
- asks catalog-grounded questions on the human-facing surface and reports why
  each question was selected;
- supports multi-item shopping plans, typed price/rating/review preferences,
  evidence-bounded comparisons, and catalog-grounded compatibility signals;
- returns a target-blind decision trace without allowing explanation or
  interface code to change the scored ranking;
- validates every response against the official contract and rebuilds its
  catalog-bound index safely if the bundled asset is unavailable or mismatched.

## Verified public evaluation

The selected preset was run on the unmodified public evaluator and all 200
released sessions:

| metric | result |
|---|---:|
| HR@10 | 1.000000 |
| MRR | 0.996667 |
| MTTC | 2.025 |
| TechnicalScore | 0.978500 |
| contract violations | 0 / 405 responses |
| prompt and completion tokens | 0 / 0 |

Three separate 200-target proxy panels exclude every released target while
matching the released set's catalog and scenario marginals. They score
0.979075, 0.965625, and 0.959900 from the same code. These are development
measurements, not estimates of private evaluation performance. The complete
selection evidence and unresolved robustness failures are recorded in
[`docs/evidence/`](docs/evidence/) and summarized in the
[`technical report`](submission/REPORT.md).

The release suite contains 589 tests: 586 pass in a source checkout and three
asset-dependent checks skip until the untracked release asset is present. The
same archive was also reproduced from a clean extraction on CPython 3.10 and
3.12.

## Try the conversational storefront

Python 3.10 or later is required. No package installation is needed.

```bash
python scripts/bootstrap.py
python scripts/build_signature_index.py
python scripts/needle_storefront.py --warm
```

Open `http://127.0.0.1:8770`.

The default storefront adds a clearly separated product layer over the frozen
candidate generator. It supports linked shopping journeys, explicit
alternatives, user-confirmed anchors, numeric catalog-property filtering,
review-confidence-aware rating order, seven reply languages, and an expandable
decision receipt. Run it with `--benchmark-mode` to remove that layer and use
the one-target session shape measured by the official evaluator. Details and
scope boundaries are in [`docs/STOREFRONT.md`](docs/STOREFRONT.md).

## Reproduce the official result

```bash
python scripts/bootstrap.py
python scripts/build_signature_index.py
python scripts/evaluate.py --output results/primary.json
```

For the full contract and behavior suite:

```bash
python -m unittest discover -s tests
```

`bootstrap.py` downloads the official participant kit, verifies its pinned
SHA-256, and extracts it beneath the ignored `.artifacts/` directory.
`build_signature_index.py` derives the catalog-bound development index.
`evaluate.py` executes `starter.agent:Agent` through the organizer's evaluator
without changing evaluator code or labels.

## Architecture

```text
official evaluator
      |
starter.agent.Agent                 strict entry point, one frozen preset
      |
versioned belief state              corrections, negation, intent revision
      |
catalog signatures                  bounded exact evidence
      |
fielded SQLite FTS5                 sparse fallback
      |
category and popularity priors      soft, catalog-derived reranking
      |
adaptive slate + seen exclusion     ordered, unique catalog products
      |
strict response                     message, question, recommendations, usage

human storefront                    separate product policy and decision trace
```

The scored import graph cannot reach the storefront. Tests enforce that
boundary, so product demonstrations, explanations, language rendering, and
shopping-plan logic cannot silently alter the measured agent. The detailed
architecture and model-choice rationale are in
[`submission/REPORT.md`](submission/REPORT.md) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Honest boundaries

- public intent cards are generated from catalog metadata; transfer to a
  differently written private simulator is not established;
- measured paraphrase and word-order perturbations still remove a small number
  of targets, while meaning-changing perturbations fail stricter robustness
  gates more often;
- unrecognized retraction language can leave an earlier intent active because
  no semantic model is present;
- negative constraints are recorded and softly demoted rather than used as
  absolute filters when catalog metadata may be incomplete;
- multilingual support covers routing and reply templates in seven languages,
  not open-domain translation of arbitrary preferences.

The report provides the measured rates, rejected alternatives, latency, memory,
cost, and fallback behavior rather than converting these limits into broader
claims.

## Repository guide

```text
needle/                 scored retrieval, state, questions, and explanations
starter/agent.py        official evaluator entry-point adapter
storefront/             unscored conversational product layer
demo/                   dependency-free local interfaces
scripts/                bootstrap, evaluation, experiments, and release tools
tests/                  contract, behavior, robustness, and packaging checks
submission/             archive entry point, runbook, report, and asset binding
docs/                   architecture, evidence, ownership, and disclosures
```

## Reproducibility and provenance

- official source: [`TechJam2026/techjam-conversational-search`](https://github.com/TechJam2026/techjam-conversational-search)
- source commit: `34078351e1c3615e5505a2e829600b56a542e462`
- participant-kit zip SHA-256: `b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae`
- catalog source: [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/)
- team contributions: [`docs/OWNERSHIP.md`](docs/OWNERSHIP.md)
- tools, APIs, libraries, datasets, and assets:
  [`docs/SUBMISSION_DISCLOSURES.md`](docs/SUBMISSION_DISCLOSURES.md)

Datasets, participant-kit files, raw evaluator results, generated development
indexes, credentials, and secrets are excluded from version control. The
submission archive carries only the catalog-bound generated index required for
fast startup, together with the code needed to validate or rebuild it.
