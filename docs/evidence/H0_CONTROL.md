# H0 evaluator controls

Date: 2026-08-29 SGT

## Artifact and environment pins

- Needle code: `dd1ff7c35fb2d9bade28a894814ba0fd2470a76a`
- official source: `34078351e1c3615e5505a2e829600b56a542e462`
- participant-kit zip SHA-256: `b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae`
- catalog SHA-256: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`
- public-set SHA-256: `857259f7a438e6188ac63e18995b6ff4489bfcfc4a716a798b9a2aa0ee8f7579`
- Python: 3.10.5
- OS: Microsoft Windows NT 10.0.26200.0
- CPU: AMD Ryzen 9 5900HS with Radeon Graphics
- network during scoring: not required
- mandatory third-party runtime packages: none

## EXP-001: untouched official weak baseline

Command, run from the extracted participant-kit root:

```text
python -m evaluator.local_evaluator --output <ignored-results-path>
```

| Metric | Reproduced | Published |
|---|---:|---:|
| HitRate@10 | 0.125 | 0.125 |
| MRR | 0.068034 | 0.068034 |
| MTTC | 9.81 | 9.81 |
| Efficiency | 0.119 | 0.119 |
| TechnicalScore | 0.10671 | 0.10671 |

Raw local result SHA-256: `39630afb92eef763e18e2056615191a4712d68e148249fee0f6bfbec2b0d5e0e`.

Decision: baseline reproduction passes. The raw result remains ignored and is not a submission artifact.

## H0-CONTROL-001: minimal integrated control

Command, run from the Needle repository root:

```text
python scripts/evaluate.py --output results/h0-control-dd1ff7c.json
```

| Slice | N | HitRate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| overall | 200 | 0.800000 | 0.480649 | 4.030000 |
| buying | 80 | 0.887500 | 0.497163 | 2.975000 |
| browsing | 80 | 0.862500 | 0.511022 | 3.450000 |
| intent override | 30 | 0.366667 | 0.268056 | 8.433333 |
| boundary | 10 | 0.900000 | 0.743333 | 3.900000 |

- Efficiency: `0.697000`
- TechnicalScore: `0.683595`
- reported token usage: `0`
- diagnostic wall time: `49.535` seconds on the pinned machine
- raw local result SHA-256: `95c877e72578fc5f29c26f34130056ff53b3adc8184f484a00f22f90f87a5edc`

This control combines accumulated active-intent text, repeated `other`, weak-FTS retrieval, and a narrow explicit-override reset. It does not isolate any component, and the released simulator makes repeated `other` unusually informative. The aggregate cannot validate the final architecture or predict private performance.

Decision: retain this as the runnable rollback/control. Prioritize the intent-override failure slice and replace each combined behavior only through a controlled experiment.
