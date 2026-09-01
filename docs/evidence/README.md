# Evidence index

Needle's experiment records are retained chronologically, including negative
results, rejected configurations, and earlier release candidates. They are
immutable evidence of decisions made during the build, not competing
instructions for submission.

## Definitive release record

[`FINAL_PRODUCT_SURFACE_20260831.md`](FINAL_PRODUCT_SURFACE_20260831.md) records
the selected source snapshot, verified submission archive, final public
evaluator result, product-surface checks, test count, and archive SHA-256. If an
older record names another archive or hash, it describes the candidate tested
at that point in the build and is superseded for upload purposes.

The concise method, model, cost, resource, limitation, transcript, and team
summary is [`../../submission/REPORT.md`](../../submission/REPORT.md).

## How to read the remaining records

- `EXP_*` documents contain preregistered comparisons and individual
  experiment outcomes;
- `FINAL_SELECTION_*` and `FINAL_RETRIEVAL_*` explain why the primary retrieval
  and robustness controls were selected;
- `FINAL_RELEASE_*` and `RELEASE_VERIFICATION_*` preserve earlier clean-build
  and independent-reproduction checkpoints;
- `REDTEAM_*` documents record adversarial conversation and state tests;
- a result is evidence only for the code, artifact pins, dataset, and controls
  named in its own record.
