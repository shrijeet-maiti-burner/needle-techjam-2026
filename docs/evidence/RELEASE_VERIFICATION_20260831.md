# Independent release verification — 31 August 2026

## Scope

An independent reproduction of the published release numbers, performed by the
team member who wrote none of the code being verified. Independence is the
point: every figure below was measured from a clean, committed tree by someone
with no prior knowledge of the implementation, on hardware and an interpreter
that were not used to produce the published values.

Every published release measurement to date was taken from a dirty tree.
`docs/evidence/FINAL_RELEASE_20260831.md` states this and its command carries
`--allow-dirty`. This pass drops that flag.

The freeze candidate is `0f0ca06`. This verification was committed on top of it
as `f10bfa9`, which changes documentation only and no code, so the code under
test is `0f0ca06` throughout.

An earlier pass ran against `8a9c9b74`, five commits behind. It is retained in
the archive-comparison section below, because the difference between the two is
what surfaced finding 1.

## Verification environment

The published disclosure table names no measurement environment. This one does,
because the reproducibility rules make an unreproducible figure worth nothing.

| Field | Value |
|---|---|
| Platform | Windows-10-10.0.26200-SP0 |
| Processor | Intel64 Family 6 Model 186 Stepping 2 |
| Logical CPUs | 16 |
| Physical memory | 16,890,519,552 bytes |
| Python | CPython 3.10.5 (the `BUILD_RECORD.md` pin) |
| SQLite | 3.37.2 |
| Network | disabled |

Official artifact bindings recorded by the run, all matching `H0_CONTROL.md`:

| Artifact | SHA-256 |
|---|---|
| catalog | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| public set | `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579` |
| evaluator | `79a5ea06f9a1b8c5036f30efa85dc1f36b8f6b06eb8feb8f545dfa767bc45564` |
| kit upstream commit | `34078351e1c3615e5505a2e829600b56a542e462` |

## What reproduced

### Clean-tree provenance

`scripts/run_experiment.py --experiment-id VERIFY-0F0CA06`, without
`--allow-dirty`, recorded:

```
git    : branch evaluation/release-verification, commit f10bfa9678ba909c268d825942f0b282c8005ed2,
         dirty false, dirty_entries []
python : 3.10.5
asset  : 71,241,728 bytes, def519218d210ce1…
```

| Metric | Result |
|---|---:|
| Sessions | 200 |
| TechnicalScore | 0.978500 |
| HR@10 | 1.000000 |
| MRR | 0.996667 |
| MTTC | 2.025 |
| Efficiency | 0.8975 |
| Contract violations | 0 / 405 responses |

### TechnicalScore, three independent paths

| Path | Score |
|---|---:|
| `scripts/run_experiment.py`, clean tree, no `--allow-dirty` | 0.978500 |
| bundler public rehearsal, staged from tracked paths | 0.978500 |
| official `evaluator.local_evaluator`, **extracted archive** | 0.978500 |

The third path carries the weight. It scores the contents of the built zip,
extracted into an empty directory containing no `.artifacts/`, with the
organizer's own evaluator. It is the closest reachable approximation of
official scoring. Scenario metrics were identical across all three: boundary 10,
browsing 80, buying 80, intent override 30.

### Official weak baseline (EXP-001)

0.10671 from the unmodified participant kit, matching the published value
exactly. Measured twice, under Python 3.12.10 and again under the pinned
3.10.5, with every scenario metric identical. The baseline is therefore
invariant across both interpreters, which is a stronger claim than the
verification plan required. It is a property of the kit and is unaffected by
the freeze commit.

### Test suite

529 tests, all passed, no skips, 704.331 s. The absence of skips matters: the
three `BundledIndexTest` guards executed rather than being disabled, which is
what confirms the rebuilt asset is bound to the current parser. See finding 1
for why they normally do not run at all.

### Asset identity

| Field | Value |
|---|---|
| schema version | 9 |
| size | 71,241,728 bytes |
| SHA-256 | `def519218d210ce15675173d055875f81cf3726060623d4b9fb451b85c05e3e1` |
| catalog binding | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| parser binding | `6a56e3549d6da62b017546a5393ce59acfa49ebaae1049b967e0917998437bca` |
| products / signatures / card keys | 50,000 / 897,046 / 177,768 |

## Independent corroboration

A second team member reproduced the result on different hardware, from a
separately built archive, with `PYTHONPATH`, `NEEDLE_SIGNATURE_INDEX` and
`TECHJAM_KIT_ROOT` unset and no `.artifacts/` on the path. Their archive hashes
to `c267e5e6…`, this one to `0714061c…`.

TechnicalScore 0.9785, HR@10 1.0, MRR 0.996667, MTTC 2.025, efficiency 0.8975,
and all four scenario breakdowns identical to six decimals. Their suite also
reported 529 passing tests.

Two independent machines, two independently built archives, one result.

## What did not reproduce

Timing figures are machine-dependent, and every deviation runs in the same
direction with no inversions. This is consistent with different hardware, not
with incorrect published values. The defect is the absent environment
declaration, not the numbers.

| Disclosure row | Published (M2, macOS, 3.12.3) | This machine (Intel, Windows, 3.10.5) | Ratio |
|---|---:|---:|---:|
| latency p50 | 1.361 ms | 10.421 ms | 7.66x |
| latency p95 | 94.287 ms | 232.271 ms | 2.46x |
| latency p99 | 173.244 ms | 406.228 ms | 2.34x |
| latency max | 304.992 ms | 928.888 ms | 3.05x |
| construction, bundled index | 2.895 s | 12.496 s | 4.32x |

Construction timings were measured on the bundled path with the correct asset,
so they describe what a judge would experience.

**Peak memory reproduces across architectures.** The published 208.8 MB is a
construction peak, and construction peak measured here is 190.4 MB at construct
and 205.5 MB after the first turn; a third machine reported 216 MB. Three
machines, three operating systems, two processor architectures, agreement within
nine percent.

An earlier draft of this document compared the published figure against
`peak_process_memory_bytes` and reported a 2.3x understatement. That was a
category error: the recorded field is a whole-run peak across 200 sessions, not
a construction peak. Measured like for like, the published figure stands.

Whole-run peak on this machine is 545,759,232 bytes against 450 MB reported
elsewhere, a spread consistent with the timing spread above.

The pattern is the point: wall-clock figures vary by up to 7.7x across machines
while memory agrees within nine percent. Memory is a property of the workload;
time is a property of the box. That is why the environment declaration matters,
and it is now present — see finding 3.

## The frozen archive

Built from the clean committed tree with `scripts/build_submission_bundle.py`.

| Property | Value |
|---|---|
| name | `needle-submission.zip` |
| size | 25,595,837 bytes |
| SHA-256 | `0714061cc4301ea94c9bc852b8eb9babb3f447d2053c9d463489dc418e513ea9` |
| tracked source files | 34 |
| archive entries | 36 |
| built at | commit `f10bfa9`, `dirty: false` |

Entry accounting: 34 tracked, plus `MANIFEST.json`, plus the injected asset,
equals 36.

Audit against `docs/submission_rules.md`: no `__pycache__`, no `.pyc`, no
`.artifacts/`, no `data/`, no `evaluator/`. No private evaluation data and no
organizer-only files ship. The report's disclosure table and `MANIFEST.json`
agree on the asset's size and parser binding.

### Per-file digests

Computed by hand from a pristine extraction, before anything executed inside it.
`MANIFEST.json` checksums only the asset, so no per-file record existed anywhere
prior to this one.

```
ed31852425214f9f4a47c09f5991bfe1aa1fa61817321dcb07b815395ea7ac1b  MANIFEST.json
6fb1d6831d4f0bc4ab164ba8abfd519268aecca80ef456274002ee878266e777  README.md
67173b196769a20a16bcb7e0bea1c4f764cda10081016f288aa26d5bf71caeb6  demo/storefront.html
55c15973b38a8347e5bc89679c1af2a74b32401f376fa69f77a3f5610d88b59b  docs/OWNERSHIP.md
72564b61687d5412207378205cd8d3f4f0c555047146e98f170ad2dca8218404  docs/STOREFRONT.md
a50a84f22021d01dcc36a86cb679b3c635e4675e492f54362fb0c93568fbf247  docs/SUBMISSION_DISCLOSURES.md
5cc27b1a47999f2476d0f05ef0dfc37ee23011c289d081c2ec5eeb083bec2645  needle/__init__.py
0f9fc34a9ec95619b9c2e9bac05e2692f8a8a98d64e8cd79d1d9d68a666c3639  needle/agent.py
a3e62959c53a73d8f008c504e0c8985fca6efa8253341f48b0d8331d8e3d9ae8  needle/catalog.py
2a1b7cbc9c30b16e9fdd0901d95fbffe4a57cd5a581a0afe5293474ace612480  needle/contracts.py
fe2c96311e69997306cfe18adb1e0f8e56d9a0307f059e21b550aee249159607  needle/diagnostics.py
3c185bea1a800d35cd3270384a8696168d83abd64de4a36c4123d79f61c6c356  needle/evaluation.py
2eef43006728b06e5fac44d3497315cbab8257f4e3461eafdc54a29a3ea9e043  needle/explain.py
38a5ab1484348c60419599974737ca6d409dc253084b64afa1f5d3a3edeeca33  needle/language.py
3337591d77d94d40b6f556188acaab24c151cb1be4f138aebde05defc42c9f8a  needle/lens.py
734d86e0c6936e55da58e5d22d460c7e6b19425326b51417f5f4ddde374bae8e  needle/presets.py
3140426dc214b3f433f4083a92f4566ba6d4b701556f21804caa0079d0212b76  needle/questions.py
270f1b3a0d03b3725370a3a1093be741a5261918d3998bc606667920045145ed  needle/semantic.py
024a6c06ff4e2b5be158b30b140274e467655ce44c076582337fb25af871a995  needle/state.py
164368853caae0e891bff8e40f0a79c05e67289f094e5ec79b87908d4dffb396  requirements.txt
e03349640686994bc5a6c42753581057ef892b78efda0bdee55c3b72d9bfd1e3  scripts/demo_session.py
6f834353d828854fa8d9be7149dea6e30fda1cbf6a7e8824bdf95dcf18fe6623  scripts/needle_storefront.py
b85e4ec0fe8d0e962c5fd091818984896022225ad533abb620adaca12bd8d369  starter/__init__.py
16cd5fd7be74848d472dc6a750e10c1a9d32b22499879ee8ca830c20cf497ac3  starter/agent.py
71dded3e85553a2fecd606cf4b41073ff925e7a5e58910080d225b94f8a3d718  storefront/__init__.py
89d8d24ba1fca89b18fb8657d41ea4c877f3bb508655a482c8abee5b667904ea  storefront/catalog_view.py
32903216fe074e4c6ab1a99d7e497044108ca62de473806b69ff29716e2e10b2  storefront/compatibility.py
d63155c6199ee37891df50e9baf027fc81e91d019fa3e7c1965c11b87da9e490  storefront/journey.py
cb62f99ed1c13a1f1541b739a903b195f52b98531e9a70013b4d7ab8dbc1e9a0  storefront/service.py
1e6a4291fb67496562d7aec44450f8ad2f99feb1bc0f3c224806244b457d82d1  submission/README.md
66ff81c3ee39821d8a2abc582472751d491670fbbe848d30e2362cca27e6f40a  submission/REPORT.md
95c5b4246d8a3903883d1f49a6863986a31de961e7dadd1b2c6fa4b14552fec9  submission/__init__.py
ae45f8fc5c687f5f2c9355f73b19c181b5fe34cb86d07f5515ccef6f62afc8a5  submission/agent.py
a14efa87dd3616f972020688e33a605c753006ca3dc2203d3f7b4ef2281621ce  submission/assets/README.md
def519218d210ce15675173d055875f81cf3726060623d4b9fb451b85c05e3e1  submission/assets/catalog-signatures.sqlite3
1d1d45e4aa62ad5a57d7812eb318151fe91d0f4c299424f7b5d74f284bf0c676  submission/requirements.txt
```

This is also the reliable way to compare two builds. Zip entries store per-file
modification timestamps and `MANIFEST.json` is generated at build time, so two
builds of identical content differ byte for byte:

```
docs/OWNERSHIP.md     mtime=(2026, 8, 31, 15, 57, 14)
MANIFEST.json         mtime=(2026, 8, 31, 18, 24, 48)
```

The two archives built independently for this freeze demonstrate it:
`c267e5e6…` and `0714061c…` from the same code. An archive digest identifies a
build event; per-file digests identify content.

### Comparison with the earlier pass

The `8a9c9b74` archive was verified in full before the freeze moved. It is
internally consistent and scored 0.978500 by the same three paths.

| Property | `8a9c9b74` | `0f0ca06` freeze |
|---|---|---|
| archive size | 24,890,213 bytes | 25,595,837 |
| archive SHA-256 | `c5a076a7…f13fed` | `0714061c…13ea9` |
| tracked / entries | 25 / 27 | 34 / 36 |
| asset size | 68,702,208 bytes | 71,241,728 |
| asset parser binding | `5d1bae73…24938` | `6a56e354…37bca` |
| suite | 463 run, 3 skipped | 529 run, 0 skipped |

The published record in `FINAL_RELEASE_20260831.md` describes the `8a9c9b74`
build and reproduces exactly on size, tracked count and entry count, differing
only in the archive digest, for the timestamp reason above, and in the archive
filename, which that document names as `needle-submission-final-schema9.zip`
without recording the `--output` flag that produces it.

## Findings

**1. Three bundled-index guards have never executed in CI, and caught a stale
asset the first time they were run.** `.gitignore` excludes
`submission/assets/*.sqlite3`, so the asset is absent on every fresh checkout,
so `@unittest.skipUnless(ASSET.is_file(), ...)` disables `BundledIndexTest` on
every CI run. The suite reports `OK (skipped=3)` in 0.002 s. The guard against a
stale asset shipping — the failure `tests/test_bundled_index.py` documents as
having already happened once, at schema 1 against code at schema 6 — had
therefore never run on any machine.

Placed and run at `8a9c9b74`, all three pass. Run at `0f0ca06` against that same
asset, the third fails:

```
AssertionError: 'ValueError: signature index metadata mismatch: facet_parser_sha256'
  is not None : bundled index was rejected and silently rebuilt in process
```

Construction rose to 115 s, a full in-process rebuild, with a 68.7 MB asset
present and unused. The cause is that `needle/catalog.py::_facet_rules_fingerprint`
hashes its own source alongside the state rules, deliberately, so that changes
to field-derived facets retire an asset that `needle.state.facet_rules_fingerprint`
alone would still accept. `catalog.py` changed at `0f0ca06`, so the fingerprint
moved from `5d1bae73…` to `6a56e354…` while the state half stayed identical.
Rebuilding reports `stale: schema '9' against '9', catalog bound, parser stale`
and produces the 71,241,728-byte asset this release ships.

The failure is silent: the score is unaffected, and only construction time and
bundle weight reveal it. Any freeze candidate requires a rebuilt asset, and
without these guards nothing says so.

**2. `run_experiment.py` never records `signature_index_fallback`.** The
provenance record captures the asset's path, SHA-256 and size, but not whether
the loader used it or silently rebuilt. Against a component whose documented
failure mode is silence, the record cannot distinguish success from swallowed
failure. Finding 1 is exactly the case it would have caught.

**3. The disclosure table named no measurement environment. Resolved in #48.**
Under § Reproducibility Requirements a judge cannot reproduce a latency figure
whose machine, operating system and interpreter are unstated. The table now
records "an Apple M2, 8 cores, 16 GB, macOS 26.6.2, CPython 3.12.3, from the
extracted archive rather than from the repository", and every figure was
re-measured there.

That declaration is what makes the comparison above interpretable rather than
alarming: a 7.7x p50 spread between an M2 on 3.12.3 and an Intel laptop on
3.10.5 is a hardware fact, and a reader can now see it. The finding is retained
here because the reconciliation that motivated it was independent of the fix.

**4. `FINAL_RELEASE_20260831.md` omits the `--output` flag.** The documented
build reproduces a differently-named archive than the document names, because
the builder's default is `needle-submission.zip`. `submission/README.md`
§ Packaging does record the flag; the two documents disagree.

**5. `MANIFEST.json` carries no per-file digests.** It checksums the asset and
asserts `tracked_file_count`. A judge holding the archive cannot verify any
individual shipped file against it. `SHA256SUMS-final.txt` now supplies this.

**6. The report cites the uncompressed asset rather than the delivered
archive.** Against the allow-list phrase "lightweight local assets", what a
judge downloads is 25,595,837 bytes, not the 71 MB uncompressed asset. The
published framing is the least favourable reading of the team's own position.

**7. The archive-root layout is unjustified in writing.**
`docs/submission_rules.md` recommends `submission/src/`. The archive places
`needle/` and `starter/` at the root because `evaluator/local_evaluator.py:12`
imports `from starter.agent import Agent`, resolved against the extraction
root, and both entry points import `needle` absolutely. Relocating either
raises `ModuleNotFoundError` before `Agent()` is constructed, outside the
evaluator's `try/except`, which wraps `respond` only, scoring zero. The
deviation is correct and forced; nothing states why where a judge reads.

**8. Nothing asserts the asset contains no `public_set` labels.** It is built
from `catalog.jsonl` alone, so the claim is true and cheap to verify, and its
absence leaves a disallowed-content question open.

**9. `tracked_file_count` differs from the archive entry count without
explanation.** 34 against 36 files on disk. Correct, but a judge counting files
sees a mismatch.

Findings 7, 8 and 9 are documentation gaps carried forward deliberately rather
than resolved in this pass, to avoid further changes to the frozen report.

## Corrections applied

- `submission/README.md`: records CPython 3.10.5 as the verified interpreter
  alongside the 3.10 floor, which § Reproducibility Requirements asks for.
- `submission/REPORT.md` team contributions: the release verification work
  added to the existing row.

Two corrections this pass identified were made independently in #48 before this
branch opened, and are not carried here:

- the disclosure table's generated index size and parser binding, which
  described the pre-freeze asset and contradicted the `MANIFEST.json` shipping
  beside them. #48 reached 71,241,728 bytes and `6a56e354…`, the same values
  this pass measured.
- the measurement environment, finding 3.

Arriving at identical asset values from an independent route is itself a
verification result, and it is recorded here rather than duplicated in the
report.

## Status

The published TechnicalScore, official baseline, contract result and asset
identity all reproduce exactly from a clean committed tree on the pinned
interpreter, and again from the extracted archive under the organizer's own
evaluator, and again on a second machine from a separately built archive.

The latency disclosures do not reproduce and cannot, as written, on any machine
other than the one that produced them. The memory disclosure does reproduce
when compared like for like.
