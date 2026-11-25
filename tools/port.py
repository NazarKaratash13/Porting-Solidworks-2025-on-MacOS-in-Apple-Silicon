#!/usr/bin/env python3
"""Produce a native ARM64 macOS binary from an experimental x86-64 PE.

The output is not guaranteed to work: missing x86 instructions and Win32 API
shims are explicit blockers. Binary porting is NOT the same as guaranteed
compatibility with all Windows programs.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def arguments(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path, help="original Windows x86-64 executable")
    parser.add_argument("-o", "--output", type=Path, required=True, help="output Mach-O executable")
    parser.add_argument("--dll", type=Path, action="append", default=[], help="DLL to lift (repeatable)")
    parser.add_argument("--standalone-gui", action="store_true", help="link the native AppKit Win32 backend")
    parser.add_argument("--mode", choices=("monolithic", "partitioned", "streamed"), default="monolithic")
    parser.add_argument("--max-compilers", type=int, help="total concurrent Clang subprocesses (M4 16GB: start with 2)")
    parser.add_argument("--parts", type=int, help="LLVM function partitions, default 2 * compiler count")
    parser.add_argument("--llvm-bin", type=Path, help="path to matching llvm-split and clang binaries")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--coverage-dir", type=Path, help="write lift coverage including traps; forces fresh build")
    parser.add_argument("--profile-ir", action="store_true", help="instrument primary IR; diagnostic only, forces fresh build")
    parser.add_argument("--allow-traps", action="store_true", help="allow unsupported instruction traps, WITHOUT per-instruction tracing (not a complete port)")
    parser.add_argument("--trace", action="store_true", help="debug tracing and allow traps (not a complete port)")
    parser.add_argument("--dry-run", action="store_true", help="validate plan, do not load PE")
    args = parser.parse_args(argv)
    if args.max_compilers is not None and not 1 <= args.max_compilers <= 32:
        parser.error("--max-compilers must be 1..32")
    if args.parts is not None and not 2 <= args.parts <= 256:
        parser.error("--parts must be 2..256")
    if not args.exe.is_file():
        parser.error(f"PE not found: {args.exe}")
    for path in args.dll:
        if not path.is_file():
            parser.error(f"DLL not found: {path}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        if not args.dry_run:
            print("ERROR: native build needs macOS ARM64 (Apple Silicon)", file=sys.stderr)
            return 2
    overrides = {
        "ARM64_RECOMPILER_AOT": args.mode,
    }
    if args.max_compilers is not None:
        overrides["ARM64_RECOMPILER_MAX_COMPILES"] = str(args.max_compilers)
    if args.parts is not None:
        overrides["ARM64_RECOMPILER_PARTS"] = str(args.parts)
    if args.llvm_bin is not None:
        overrides["LLVM_BIN"] = str(args.llvm_bin.expanduser().resolve())
    if args.coverage_dir:
        overrides["ARM64_RECOMPILER_COVERAGE_DIR"] = str(args.coverage_dir.resolve())
    if args.profile_ir:
        overrides["ARM64_RECOMPILER_PROFILE_IR"] = "1"
    if args.no_cache or args.coverage_dir or args.profile_ir:
        overrides["ARM64_RECOMPILER_NO_CACHE"] = "1"
    os.environ.update(overrides)
    # Import AFTER env overrides so compile semaphore is correctly configured.
    sys.path.insert(0, str(ROOT / "recompiler"))
    from aot_build import COMPILE_JOBS, llvm_toolchain, part_count
    if args.mode != "monolithic":
        try:
            clang, splitter = llvm_toolchain(require_split=args.mode != "streamed")
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"LLVM toolchain: clang={clang}, llvm-split={splitter}")
    print(f"Port plan: {args.exe} -> {args.output}")
    print(f"mode={args.mode} compile_slots={COMPILE_JOBS} " +
          (f"partitions={part_count(COMPILE_JOBS)}" if args.mode != "monolithic" else ""))
    if args.dry_run:
        return 0
    import pefile
    from build_console_modules import build
    try:
        if args.trace or args.allow_traps:
            print("WARNING: tolerant lifting may generate executable traps, not a complete port", file=sys.stderr)
        build(args.exe, args.output, args.dll, trace=args.trace, tolerant=args.allow_traps,
              standalone_gui=args.standalone_gui, strict_modules=not (args.trace or args.allow_traps))
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError,
            pefile.PEFormatError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Compiled: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
