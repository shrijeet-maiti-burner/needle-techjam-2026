# Needle submission bundle

This file is the entry point for the extracted submission archive. All paths
below are relative to the archive root. The public repository contains
additional experiment, build and test tooling that is intentionally absent
from this minimal bundle.

## Requirements

- Python: 3.10 or later; the release was built and independently reproduced on
  CPython 3.10 and 3.12;
- the extracted official TechJam participant kit, including
  `evaluator/local_evaluator.py`, `data/catalog.jsonl` and
  `data/public_set.jsonl`;
- no package installation beyond the Python standard library;
- no network access, credentials, model download or environment variable for
  the scored agent.

The official entry point is `starter.agent:Agent`. The equivalent release
adapter is `submission.agent:Agent`.

## Run the unmodified official evaluator

Extract this zip and the official participant kit into separate directories.
From this bundle's root, run one command on Windows, macOS or Linux:

```text
python scripts/run_official.py --kit-root "/absolute/path/to/techjam-conversational-search" --output results.json
```

Replace the quoted path with the extracted participant-kit root. The helper
checks the three required organizer files, places this bundle first on Python's
import path so `starter.agent:Agent` cannot resolve to the kit's weak starter,
and executes the organizer's `evaluator/local_evaluator.py` unchanged. It does
not copy, edit or wrap evaluator logic. The evaluator writes its ordinary
`results.json` to the requested output path.

The verified public rehearsal contains 200 sessions and reports:

| metric | value |
|---|---:|
| HR@10 | 1.000000 |
| MRR | 0.996667 |
| MTTC | 2.025 |
| TechnicalScore | 0.978500 |
| prompt/completion tokens | 0 / 0 |

These are public-development measurements, not a private-score prediction.

## Run the demonstrated multi-turn session

The report contains a readable transcript. To reproduce it from the extracted
bundle, set the participant-kit path and run the shipped helper.

PowerShell:

```powershell
$env:TECHJAM_KIT_ROOT = "C:\absolute\path\to\techjam-conversational-search"
python scripts/demo_session.py --scenario intent_override --show 1
```

macOS or Linux:

```bash
TECHJAM_KIT_ROOT="/absolute/path/to/techjam-conversational-search" \
  python scripts/demo_session.py --scenario intent_override --show 1
```

## Run the optional storefront

After setting `TECHJAM_KIT_ROOT` as above:

```text
python scripts/needle_storefront.py --warm
```

Open `http://127.0.0.1:8770`. The storefront is an unscored demonstration
layer; `starter.agent:Agent` remains the measured submission.

## Bundled asset and fallback

`submission/assets/catalog-signatures.sqlite3` is a catalog-bound startup
optimisation. `MANIFEST.json` records its SHA-256, schema, catalog binding and
facet-parser binding. The loader validates every binding before use. If the
asset is absent, corrupt or mismatched, the agent rebuilds an equivalent index
in process instead of failing or trusting stale data.

The bundle contains no participant-kit files, evaluator, competition dataset,
raw results, bytecode cache, credential or secret. It requires no external
service. The method, model choice, measured resources, limitations and team
contributions are in `submission/REPORT.md`; development-tool and data-source
disclosures are in `docs/SUBMISSION_DISCLOSURES.md`.

## Environment variables

- `TECHJAM_KIT_ROOT` is used only by the optional demo and storefront helpers.
  `scripts/run_official.py` takes the kit path explicitly with `--kit-root`.
- `NEEDLE_SIGNATURE_INDEX` optionally overrides the signature-index path. It
  is unnecessary for this archive because the verified asset is bundled.

No other environment variable is read by the submitted agent.
