#!/usr/bin/env python3
"""Differential CLI smoke/performance gate for two native variants.

Tests ONLY the supplied inputs. Equal outputs do not prove full equivalence to
Windows or correctness of GUI, exception, timing, or memory semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
import statistics
import subprocess
import time


def run(binary: Path, argv: list[str], timeout: float) -> dict:
    start = time.perf_counter_ns()
    proc = subprocess.run([str(binary), *argv], capture_output=True, timeout=timeout,
                          check=False)
    elapsed_ms = (time.perf_counter_ns() - start) / 1e6
    return {"returncode": proc.returncode,
            "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
            "stdout_bytes": len(proc.stdout), "stderr_bytes": len(proc.stderr),
            "elapsed_ms": elapsed_ms}


def compare(left: Path, right: Path, argv: list[str], *, repeats: int = 5,
            warmups: int = 1, timeout: float = 30.0) -> dict:
    if repeats < 1 or warmups < 0 or timeout <= 0:
        raise ValueError("repeats >= 1, warmups >= 0, timeout > 0 required")
    for path in (left, right):
        if not path.is_file():
            raise FileNotFoundError(path)
    for _ in range(warmups):
        run(left, argv, timeout)
        run(right, argv, timeout)
    samples = {"monolithic": [], "partitioned": []}
    matches = True
    differences = []
    for i in range(repeats):
        # Alternate execution order to reduce systematic time drift bias.
        order = (("monolithic", left), ("partitioned", right)) if i % 2 == 0 else (
            ("partitioned", right), ("monolithic", left))
        result = {label: run(binary, argv, timeout) for label, binary in order}
        for label, entry in result.items():
            samples[label].append(entry)
        comparable = ("returncode", "stdout_sha256", "stderr_sha256",
                      "stdout_bytes", "stderr_bytes")
        if any(result["monolithic"][key] != result["partitioned"][key] for key in comparable):
            matches = False
            differences.append(i)
    summary = {label: {"median_ms": statistics.median(s["elapsed_ms"] for s in rows),
                       "min_ms": min(s["elapsed_ms"] for s in rows)}
               for label, rows in samples.items()}
    return {"match_cli_outputs": matches, "differing_runs": differences,
            "arguments": argv, "repeats": repeats, "warmups": warmups,
            "summary": summary, "samples": samples,
            "warning": "CLI-only comparison. No proof of equivalent Windows behavior or GUI semantics."}


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if '--' in raw:
        boundary = raw.index('--')
        guest_args = raw[boundary + 1:]
        raw = raw[:boundary]
    else:
        guest_args = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("monolithic", type=Path)
    parser.add_argument("partitioned", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(raw)
    try:
        outcome = compare(args.monolithic, args.partitioned, guest_args,
                          repeats=args.repeats, warmups=args.warmups, timeout=args.timeout)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"Compare failed: {error}\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(outcome, indent=2) + '\n')
    print(json.dumps({k: v for k, v in outcome.items() if k not in ('samples',)}, indent=2))
    return 0 if outcome['match_cli_outputs'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
