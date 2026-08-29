from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KIT_ROOT = ROOT / ".artifacts" / "participant-kit" / "techjam-conversational-search"
OFFICIAL_SOURCE_COMMIT = "34078351e1c3615e5505a2e829600b56a542e462"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def agent_asset_records(agent_kwargs: dict[str, object]) -> dict[str, object]:
    records: dict[str, object] = {}
    for key, value in agent_kwargs.items():
        if not key.endswith("_path") or not isinstance(value, str):
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        path = path.resolve()
        records[key] = {
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": sha256_file(path) if path.is_file() else None,
        }
    return records


def git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def total_memory_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
        return None
    if hasattr(os, "sysconf"):
        try:
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (ValueError, OSError):
            return None
    return None


def peak_process_memory_bytes() -> int | None:
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return int(counters.peak_working_set_size)
        return None
    try:
        import resource

        maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(maximum_rss if sys.platform == "darwin" else maximum_rss * 1024)
    except (ImportError, ValueError):
        return None


def load_symbol(specifier: str) -> type:
    module_name, separator, symbol_name = specifier.partition(":")
    if not separator or not module_name or not symbol_name:
        raise ValueError("agent must use module:Class syntax")
    symbol: Any = importlib.import_module(module_name)
    for part in symbol_name.split("."):
        symbol = getattr(symbol, part)
    if not isinstance(symbol, type):
        raise TypeError(f"agent symbol is not a class: {specifier}")
    return symbol


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="run a fingerprinted official-evaluator experiment")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--agent", default="needle.agent:Agent")
    parser.add_argument("--agent-kwargs", default="{}", help="JSON object passed to the agent constructor")
    parser.add_argument("--kit-root", type=Path, default=DEFAULT_KIT_ROOT)
    parser.add_argument("--output-root", type=Path, default=ROOT / "results")
    parser.add_argument("--network-state", choices=("enabled", "disabled", "unknown"), default="unknown")
    parser.add_argument("--allow-dirty", action="store_true", help="permit diagnostic runs from a dirty tree")
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    if not args.experiment_id or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for character in args.experiment_id):
        raise SystemExit("experiment id must contain only uppercase letters, digits, and hyphens")
    try:
        agent_kwargs = json.loads(args.agent_kwargs)
    except json.JSONDecodeError as error:
        raise SystemExit(f"agent kwargs is not valid JSON: {error}") from error
    if not isinstance(agent_kwargs, dict):
        raise SystemExit("agent kwargs must decode to an object")

    dirty_lines = [line for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines() if line]
    if dirty_lines and not args.allow_dirty:
        raise SystemExit("working tree is dirty; commit the implementation or use --allow-dirty for a diagnostic run")

    kit_root = args.kit_root.expanduser().resolve()
    evaluator_path = kit_root / "evaluator" / "local_evaluator.py"
    catalog_path = kit_root / "data" / "catalog.jsonl"
    dataset_path = kit_root / "data" / "public_set.jsonl"
    required = (evaluator_path, catalog_path, dataset_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"official kit is incomplete: {', '.join(missing)}")

    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(kit_root))
    official = importlib.import_module("evaluator.local_evaluator")
    from needle.evaluation import ContractCheckingAgent

    samples = official.load_jsonl(dataset_path)
    catalog_ids, categories, products = official.catalog_index(catalog_path)
    agent_class = load_symbol(args.agent)
    effective_kwargs = {"catalog_path": catalog_path, **agent_kwargs}

    tracemalloc.start()
    total_started = time.perf_counter()
    startup_started = time.perf_counter()
    agent = agent_class(**effective_kwargs)
    startup_seconds = time.perf_counter() - startup_started
    checked_agent = ContractCheckingAgent(agent, catalog_ids)
    evaluation_started = time.perf_counter()
    result = official.evaluate(checked_agent, samples, catalog_ids, categories, products)
    evaluation_seconds = time.perf_counter() - evaluation_started
    total_seconds = time.perf_counter() - total_started
    current_traced_bytes, peak_traced_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    code_sha = git("rev-parse", "HEAD")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_directory = args.output_root.resolve() / args.experiment_id / f"{timestamp}-{code_sha[:8]}"
    output_directory.mkdir(parents=True, exist_ok=False)
    raw_path = output_directory / "raw-result.json"
    write_json(raw_path, result)

    summary = {key: value for key, value in result.items() if key != "sessions"}
    contract = checked_agent.report.as_dict()
    record = {
        "schema_version": 1,
        "experiment_id": args.experiment_id,
        "recorded_at_utc": timestamp,
        "command": subprocess.list2cmdline([sys.executable, *sys.argv]),
        "git": {
            "commit": code_sha,
            "branch": git("branch", "--show-current"),
            "dirty": bool(dirty_lines),
            "dirty_entries": dirty_lines,
        },
        "agent": {
            "specifier": args.agent,
            "kwargs": agent_kwargs,
            "configuration_sha256": canonical_sha256({"agent": args.agent, "kwargs": agent_kwargs}),
            "assets": agent_asset_records(agent_kwargs),
        },
        "official_artifacts": {
            "upstream_commit": OFFICIAL_SOURCE_COMMIT,
            "evaluator_sha256": sha256_file(evaluator_path),
            "catalog_sha256": sha256_file(catalog_path),
            "public_set_sha256": sha256_file(dataset_path),
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_bytes": total_memory_bytes(),
            "sqlite": sqlite3.sqlite_version,
            "network_state": args.network_state,
        },
        "performance": {
            "startup_seconds": round(startup_seconds, 6),
            "evaluation_seconds": round(evaluation_seconds, 6),
            "total_seconds": round(total_seconds, 6),
            "current_python_traced_bytes": current_traced_bytes,
            "peak_python_traced_bytes": peak_traced_bytes,
            "peak_process_memory_bytes": peak_process_memory_bytes(),
            "memory_measurement_limit": "tracemalloc excludes some native allocations, including sqlite internals",
        },
        "contract": contract,
        "summary": summary,
        "raw_result": {
            "path": raw_path.name,
            "sha256": sha256_file(raw_path),
        },
    }
    record_path = output_directory / "record.json"
    write_json(record_path, record)
    manifest_path = output_directory / "SHA256SUMS"
    manifest_path.write_text(
        f"{sha256_file(raw_path)}  {raw_path.name}\n{sha256_file(record_path)}  {record_path.name}\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_directory": str(output_directory), **summary, "contract": contract}, indent=2))
    if not contract["passed"]:
        raise SystemExit("strict contract validation failed; inspect record.json")


if __name__ == "__main__":
    main()
