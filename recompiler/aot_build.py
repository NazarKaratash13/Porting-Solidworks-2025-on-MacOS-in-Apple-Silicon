"""Memory-conscious AOT compilation of one lifted LLVM module.

This is an opt-in LLVM backend strategy, NOT an alternative x86 lifter.
llvm-split retains LLVM's symbol handling; ThinLTO restores some cross-partition
optimization. The resulting code must still pass real macOS regression tests.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tempfile
from build_pressure import PressureGate


def available_memory_bytes() -> int | None:
    """Physical RAM: a conservative concurrency heuristic, not free memory."""
    if sys.platform == "darwin":
        try:
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        except (OSError, ValueError, subprocess.CalledProcessError):
            return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def max_compilers() -> int:
    """Reserve ~6 GiB for macOS/apps, allow ~5 GiB per heavy Clang job.

    On a 16 GiB M4 this defaults to two simultaneous compiler processes.
    Lower ARM64_RECOMPILER_MAX_COMPILES to 1 for very large functions.
    """
    override = os.environ.get("ARM64_RECOMPILER_MAX_COMPILES")
    if override is not None:
        if not override.isdecimal() or int(override) < 1:
            raise ValueError("ARM64_RECOMPILER_MAX_COMPILES must be a positive integer")
        return min(32, int(override))
    ram = available_memory_bytes()
    if ram is None:
        return 2
    gib = ram / (1 << 30)
    return min(os.cpu_count() or 2, 4, max(1, int(max(0, gib - 6) // 5)))


# The *same* semaphore is shared by all Python thread pools running this build.
COMPILE_JOBS = max_compilers()
COMPILE_SLOTS = threading.BoundedSemaphore(COMPILE_JOBS)
PRESSURE_GATE = PressureGate()


def run_compiler(command: list[str | Path]) -> None:
    """Limit concurrent Clang processes globally across modules and main EXE."""
    with COMPILE_SLOTS, PRESSURE_GATE.admit():
        subprocess.run([str(item) for item in command], check=True)


def digest_file(path: Path) -> str:
    """Streaming hash: do not duplicate a multi-gigabyte LLVM IR in Python RAM."""
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def llvm_toolchain(*, require_split: bool = True) -> tuple[Path, Path]:
    """Use a matching clang and llvm-split, never mix arbitrary LLVM versions."""
    bin_dir = os.environ.get("LLVM_BIN")
    if bin_dir:
        clang = Path(bin_dir).expanduser() / "clang"
        split = Path(bin_dir).expanduser() / "llvm-split"
    else:
        split_name = shutil.which("llvm-split")
        if not split_name and not require_split:
            clang_name = shutil.which("clang")
            if not clang_name: raise RuntimeError("clang not found")
            split_name = str(Path(clang_name).parent / "llvm-split")
        if not split_name:
            raise RuntimeError("LLVM llvm-split not found; install Homebrew llvm and set LLVM_BIN=$(brew --prefix llvm)/bin")
        split = Path(split_name)
        clang = split.parent / "clang"
    if (require_split and not split.is_file()) or not clang.is_file():
        raise RuntimeError(f"Need clang and llvm-split from one LLVM toolchain: {clang} / {split}")
    return clang, split


def part_count(workers: int = COMPILE_JOBS) -> int:
    override = os.environ.get("ARM64_RECOMPILER_PARTS")
    if override is not None:
        if not override.isdecimal() or int(override) < 2:
            raise ValueError("ARM64_RECOMPILER_PARTS must be an integer >= 2")
        return min(256, int(override))
    return max(2, workers * 2)


def split_program(source: Path, work: Path, *, split: Path, parts: int) -> list[Path]:
    """Split LLVM by function with the official LLVM tool (not by text/bytes)."""
    prefix = work / "part"
    run_compiler([split, "--round-robin", "-j", str(parts),
                  "-o", prefix, source])
    files = [p for p in work.iterdir()
             if p.is_file() and p.name.startswith("part")
             and p.name[len("part"):].isdigit()]
    files.sort(key=lambda path: int(path.name[len("part") :]))
    if len(files) != parts:
        raise RuntimeError(f"llvm-split expected {parts} partitions, found {len(files)}")
    return files


def compile_partitioned_program(source: Path, work: Path, *, store: Path | None = None,
                                flags: tuple[str, ...] = ("-O2",),
                                jobs: int = COMPILE_JOBS,
                                parts: int | None = None, direct: bool = False, prepartitioned: list[Path] | None = None) -> tuple[list[Path], Path]:
    """Compile lifted IR as independent ThinLTO bitcode objects.

    Store compiled partitions by content digest, but preserve separate temporary
    paths per invocation. The caller MUST link with the returned clang and
    '-flto=thin' to enable inter-partition optimization.
    """
    source, work = Path(source), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    clang, llvm_split = llvm_toolchain(require_split=not direct)
    count = parts if parts is not None else part_count(jobs)
    if count < 2 or count > 256:
        raise ValueError("partitions must be between 2 and 256")
    if jobs < 1:
        raise ValueError("jobs must be positive")
    if prepartitioned is not None:
        if not direct or len(prepartitioned) != count or not all(p.is_file() for p in prepartitioned):
            raise ValueError("invalid prepartitioned module list")
        shards = prepartitioned
    elif direct:
        from ir_partition import partition_generated_ir
        shards = partition_generated_ir(source, work, count)
    else:
        shards = split_program(source, work, split=llvm_split, parts=count)
    version = subprocess.run([str(clang), "--version"], capture_output=True,
                             text=True, check=True).stdout
    # Single-token compiler semaphore also limits other main-build subprocesses.
    def compile_one(index_shard: tuple[int, Path]) -> Path:
        index, shard = index_shard
        destination = work / f"part{index}.o"
        digest = hashlib.sha256((version + repr(flags) + "arm64-thinlto-v2").encode())
        digest.update(bytes.fromhex(digest_file(shard)))
        cached = store / f"{digest.hexdigest()}.o" if store is not None else None
        if cached is not None and cached.exists():
            shutil.copy2(cached, destination)
            return destination
        run_compiler([clang, "-arch", "arm64", *flags, "-flto=thin",
                      "-Wno-override-module", "-x", "ir", "-c", shard, "-o", destination])
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{cached.name}.", suffix=".tmp", dir=cached.parent)
            os.close(fd)
            temporary = Path(name)
            try:
                shutil.copy2(destination, temporary)
                temporary.replace(cached)
            finally:
                temporary.unlink(missing_ok=True)
        return destination

    with ThreadPoolExecutor(max_workers=min(jobs, COMPILE_JOBS)) as executor:
        results = list(executor.map(compile_one, enumerate(shards)))
    return results, clang


def thinlto_link_flags(workers: int = COMPILE_JOBS, cache: Path | None = None) -> list[str]:
    """ld64 ThinLTO needs an explicit backend-thread cap, too."""
    args = ["-flto=thin", f"-Wl,-mllvm,-threads={workers}"]
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        args.append(f"-Wl,-cache_path_lto,{cache}")
    return args
