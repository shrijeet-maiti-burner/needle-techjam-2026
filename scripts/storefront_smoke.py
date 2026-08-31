"""Concurrent smoke test for the storefront service.

The interface is the one surface a judge drives by hand, and it is the only one
where several people can be typing at once. The unit tests cover the service in
isolation; this exercises the running HTTP server the way a room full of people
would, and asserts on the things that fail quietly:

*A degraded turn is a failure here.* `Agent.respond` never raises, so a broken
turn arrives as a slightly worse answer rather than an error. Every check that
looks only at "did I get a slate" passes on a completely broken agent. This
reads `degraded` on every turn and fails the run if any turn set it.

*Latency is asserted, not reported.* A regression that makes each turn a
half-second slower breaks nothing and shows up nowhere. `--max-p95-ms` turns
that into a failure.

    python scripts/needle_storefront.py --warm          # in one shell
    python scripts/storefront_smoke.py                  # in another

Exits non-zero on the first failed assertion, so it is usable as a gate.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field


# Five scripted conversations in the shape the released simulator emits, so the
# smoke test drives the signature path rather than only the sparse fallback.
CONVERSATIONS: tuple[tuple[str, ...], ...] = (
    (
        "I'm looking for Wrist Watches.",
        "For that, what matters is: Analog.",
        "For that, what matters is: Stainless Steel Band.",
    ),
    (
        "I'm looking for Accessories Belts.",
        "For that, what matters is: leather; 100% Leather.",
        "For that, what matters is: Buckle closure.",
    ),
    (
        "I'm looking for Wool & Pea Coats.",
        "For that, what matters is: 100% Wool.",
        "Actually, ignore my earlier preference. What I need is: Imported.",
    ),
    (
        "I'm looking for Fashion Sneakers.",
        "For that, what matters is: Rubber sole.",
        "For that, what matters is: Lace-up closure.",
    ),
    # Free text: no verbatim catalog fragment, so this drives the sparse path.
    (
        "classic analog watch with a silver strap",
        "something well reviewed",
        "not too expensive",
    ),
)


@dataclass
class Result:
    turns: int = 0
    latencies: list[float] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    empty_slates: list[str] = field(default_factory=list)
    missing_traces: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def call(base: str, path: str, payload: dict | None = None, timeout: float = 60.0):
    request = urllib.request.Request(
        base + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={} if payload is None else {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.load(response)


def drive(base: str, script: tuple[str, ...], index: int) -> Result:
    result = Result()
    try:
        _, started = call(base, "/api/session", {})
        session_id = started["session_id"]
    except Exception as error:  # noqa: BLE001 - reported, not raised
        result.errors.append(f"conversation {index}: session start failed: {error}")
        return result

    for turn_number, message in enumerate(script, start=1):
        try:
            _, turn = call(base, "/api/message", {"session_id": session_id, "message": message})
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"conversation {index} turn {turn_number}: {error}")
            return result

        result.turns += 1
        result.latencies.append(float(turn["latency_ms"]))
        if turn.get("degraded"):
            result.degraded.append(f"conversation {index} turn {turn_number}: {message!r}")
        if not turn.get("cards"):
            result.empty_slates.append(f"conversation {index} turn {turn_number}: {message!r}")
        trace = turn.get("trace")
        if not isinstance(trace, dict) or not trace.get("target_blind"):
            result.missing_traces.append(
                f"conversation {index} turn {turn_number}: {message!r}"
            )

        # The response contract is the agent's, and the interface must not
        # invent or drop keys on the way through.
        for key in ("turn", "message", "ask_attribute", "cards", "beliefs", "trace"):
            if key not in turn:
                result.errors.append(f"conversation {index} turn {turn_number}: missing {key}")
        if len(turn.get("cards", [])) > 10:
            result.errors.append(
                f"conversation {index} turn {turn_number}: {len(turn['cards'])} cards exceeds ten"
            )
    return result


def check_error_paths(base: str) -> list[str]:
    """The interface must refuse bad input rather than degrade on it."""
    failures: list[str] = []
    _, started = call(base, "/api/session", {})
    session_id = started["session_id"]

    cases = (
        ("empty message", {"session_id": session_id, "message": "   "}, 400),
        ("missing session", {"message": "hello"}, 400),
        ("unknown route", None, 404),
    )
    for label, payload, expected in cases:
        try:
            if label == "unknown route":
                status, _ = call(base, "/api/not-a-route", {})
            else:
                status, _ = call(base, "/api/message", payload)
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception as error:  # noqa: BLE001
            failures.append(f"{label}: unexpected {type(error).__name__}: {error}")
            continue
        if status != expected:
            failures.append(f"{label}: expected HTTP {expected}, got {status}")
    return failures


def check_turn_budget(base: str) -> list[str]:
    """Turn eleven must be refused, not answered by the degraded fallback.

    `StateStore.observe` raises above ten turns, so an interface that keeps
    going renders a degraded answer as though it were the selected policy.
    """
    failures: list[str] = []
    _, started = call(base, "/api/session", {})
    session_id = started["session_id"]
    for turn_number in range(1, 11):
        _, turn = call(base, "/api/message", {"session_id": session_id, "message": f"belt {turn_number}"})
        if turn.get("degraded"):
            failures.append(f"turn {turn_number} of the budget degraded")
    try:
        status, _ = call(base, "/api/message", {"session_id": session_id, "message": "one too many"})
        failures.append(f"turn 11 was accepted with HTTP {status}; it must be refused")
    except urllib.error.HTTPError as error:
        if error.code != 400:
            failures.append(f"turn 11 refused with HTTP {error.code}, expected 400")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8770")
    parser.add_argument("--clients", type=int, default=12)
    parser.add_argument("--max-p95-ms", type=float, default=750.0)
    arguments = parser.parse_args(argv)

    try:
        _, config = call(arguments.base, "/api/config")
    except Exception as error:  # noqa: BLE001
        print(f"FAIL: storefront not reachable at {arguments.base}: {error}")
        print("      start it with `python scripts/needle_storefront.py --warm`")
        return 2

    print(f"storefront at {arguments.base}")
    print(f"  products           {config['product_count']}")
    print(f"  optional features  {config['optional_features'] or 'none'}")
    print(f"  deviations         {config['deviations'] or 'none'}")
    print(f"  index fallback     {config['index_fallback'] or 'none'}")
    print()

    scripts = [CONVERSATIONS[index % len(CONVERSATIONS)] for index in range(arguments.clients)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=arguments.clients) as pool:
        futures = [pool.submit(drive, arguments.base, script, index) for index, script in enumerate(scripts)]
        results = [future.result() for future in as_completed(futures)]
    wall = time.perf_counter() - started

    latencies = [value for result in results for value in result.latencies]
    turns = sum(result.turns for result in results)
    degraded = [line for result in results for line in result.degraded]
    empty = [line for result in results for line in result.empty_slates]
    missing_traces = [line for result in results for line in result.missing_traces]
    errors = [line for result in results for line in result.errors]

    print(f"concurrent: {arguments.clients} clients, {turns} turns in {wall:.2f}s")
    if latencies:
        ordered = sorted(latencies)
        print(
            f"  latency  p50 {statistics.median(ordered):.1f}ms"
            f"  p95 {ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]:.1f}ms"
            f"  max {ordered[-1]:.1f}ms"
        )
    print()

    print("error paths")
    error_path_failures = check_error_paths(arguments.base)
    print(f"  {'ok' if not error_path_failures else 'FAILED'}")
    print("turn budget")
    budget_failures = check_turn_budget(arguments.base)
    print(f"  {'ok' if not budget_failures else 'FAILED'}")
    print()

    failures: list[str] = []
    failures += [f"transport/contract: {line}" for line in errors]
    failures += [f"degraded turn: {line}" for line in degraded]
    failures += [f"empty slate: {line}" for line in empty]
    failures += [f"missing target-blind trace: {line}" for line in missing_traces]
    failures += [f"error path: {line}" for line in error_path_failures]
    failures += [f"turn budget: {line}" for line in budget_failures]
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        if p95 > arguments.max_p95_ms:
            failures.append(f"latency: p95 {p95:.1f}ms exceeds {arguments.max_p95_ms:.1f}ms")
    if not turns:
        failures.append("no turns completed")

    if failures:
        print(f"FAIL ({len(failures)})")
        for line in failures[:40]:
            print(f"  - {line}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
