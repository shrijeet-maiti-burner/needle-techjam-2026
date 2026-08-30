# Needle Lens

Needle Lens is a local, target-blind runtime certificate for the selected agent. It makes the system's decision process inspectable without introducing a second demo policy or giving the agent access to evaluator labels.

## Run it

Bootstrap the official participant kit and build the catalog asset first, then start the local server:

```bash
python scripts/bootstrap.py
python scripts/build_signature_index.py
python scripts/needle_lens.py
```

Open `http://127.0.0.1:8765`. The console replays any released public session with the unmodified official simulator and the same `PRIMARY_AGENT_KWARGS` used by `starter.agent:Agent`.

For a portable trace artifact:

```bash
python scripts/needle_lens.py \
  --sample public_0002 \
  --export .artifacts/demo/needle-lens.json
```

## Faithfulness boundary

- the trace is created inside the same `Agent.respond` call that emits the scored recommendation slate;
- the trace receives catalog state, observed messages, candidate sets, and the final response, but never the hidden target;
- trace generation happens after ranking and cannot change recommendation order;
- the evaluator-owned envelope reveals the public target only after replay so the interface can mark a hit;
- enabling tracing is optional and disabled in the submission preset;
- the console has no network, model, JavaScript package, or frontend build dependency.

The interface separates two question policies on purpose. **Scored policy** is the measured official-simulator action. **Human-shopping shadow** is a presupposition-safe expected-value-of-information board computed from catalog evidence; it is explanatory only and never influences the scored response. This avoids presenting an evaluator-specific optimum as a general claim about human conversation.

## What the certificate exposes

- a versioned belief ledger with active and superseded constraints;
- all plausible disclosure parses and their catalog bucket cardinalities;
- the candidate funnel from frozen catalog to emitted slate;
- a bounded ambiguity certificate explaining whether uniqueness is safe to claim;
- per-recommendation catalog evidence and active-constraint matches;
- the selected decision path, question action, latency, and zero-token usage.

This is observability, not a score claim. Official metrics remain sourced only from the pinned evaluator and registered experiment artifacts.
