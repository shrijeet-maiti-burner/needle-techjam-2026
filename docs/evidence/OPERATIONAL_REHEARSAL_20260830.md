# Clean-bundle operational rehearsal, 30 August 2026

Owner: Aryaman, standing in while the evaluation/packaging owner is away. This
covers the operational gate, not a score. Nothing here changes the selected
configuration.

## Method

`git archive` of `main`, extracted to a directory outside the repository, run
with the official evaluator and official data on `PYTHONPATH`, working directory
set to the extracted bundle. Entry point is `submission.agent:Agent`, the
documented one, rather than the development adapter. The signature asset is
gitignored, so the bundle a grader receives contains none -- that is the state
tested here.

Environment: Python 3.11.9, SQLite 3.45.1, Windows, no network used during
scoring.

## Result: the bundle runs and reproduces exactly

| | |
|---|---|
| TechnicalScore | **0.878039** |
| HR@10 / MRR / MTTC | 0.995 / 0.684131 / 2.235 |
| bundle size | 423 KB, 64 files |
| data, assets, credentials, results in bundle | none |
| missing-asset fallback | engaged, rebuilt in process |
| evaluation | 37.0 s for 200 sessions, 185 ms/session |

This independently confirms the packaging claim in
`FINAL_SELECTION_20260830.md`. The fallback path and the bundled-asset path
produce identical scores, so they are behaviourally equivalent, not merely
similar.

## Finding 1: startup is 5x slower without the asset, and worse cold

| Bundle state | Startup |
|---|---:|
| asset present | **3.0 s** |
| asset absent, warm disk cache | 15.7 s |
| asset absent, cold | **49.4 s** |

The asset is 30.6 MiB and is gitignored, so unless it is deliberately added to
the submission archive a grader gets the 49-second cold path. Extrapolating to
800 private sessions at 185 ms each: roughly 50 s startup plus 150 s scoring.

That is comfortable against a generous limit and fatal against a tight startup
timeout. R-03 is still unanswered, so this cannot be resolved by measurement --
it is a decision about how much risk to carry:

- **ship the 30.6 MiB asset**: 3 s startup, but the archive grows and the asset
  must match the scoring catalog exactly or the fallback fires anyway;
- **ship without it**: no size question, no catalog-binding risk, ~49 s cold.

Recommendation: ship it, and keep the fallback. The fallback already handles a
catalog mismatch safely, so including the asset costs only archive size and
removes the timeout exposure. Flagging rather than deciding -- this is
Shrijeet's and Yazhiniyan's call.

## Finding 2: the unreleased SQLite handle blocks asset replacement

While measuring the above, deleting the asset after use failed:

```
PermissionError: [WinError 32] The process cannot access the file because it is
being used by another process: submission/assets/catalog-signatures.sqlite3
```

`CatalogIndex` holds the signature index open for the lifetime of the object.
This has been visible only as two test teardown errors, and was easy to read as
a test-harness quirk. It is not: it blocks replacing or removing the asset in a
real packaging workflow, on the platform two of us develop on. PR #13 adds
`close()` and context-manager support; this run is the non-test case for it.

## Not covered

- Peak process memory. `tracemalloc` reports 63 MiB, but it excludes SQLite's
  native allocations, which are the bulk of the footprint, so the figure is not
  usable as a limit check and is not quoted as one.
- A genuinely network-isolated run. Nothing in the scoring path opens a socket
  and `bootstrap.py` is setup rather than scoring, but that is an argument from
  reading the code, not an enforced test.
- A second machine, and a non-Windows platform.
