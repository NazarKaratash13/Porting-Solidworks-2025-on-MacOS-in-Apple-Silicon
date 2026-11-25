"""Bounded-memory, rollback-capable LLVM IR emission to a temporary disk file.

The existing lifter needs an instruction-local rollback when tolerant decoding
fails.  Keep that property without retaining every emitted IR line in RAM.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


class DiskLineSpool:
    """Append UTF-8 IR lines; checkpoint/rollback via byte offsets."""

    def __init__(self, directory: Path):
        self.file = tempfile.TemporaryFile(mode="w+b", dir=directory, buffering=1024 * 1024)
        self.bytes_written = 0

    def append(self, line: str) -> None:
        if not isinstance(line, str):
            raise TypeError("LLVM IR lines must be strings")
        encoded = (line + "\n").encode("utf-8")
        self.file.write(encoded)
        self.bytes_written += len(encoded)

    def checkpoint(self) -> int:
        return self.file.tell()

    def rollback(self, offset: int) -> None:
        if not 0 <= offset <= self.file.tell():
            raise ValueError("invalid IR checkpoint")
        self.file.seek(offset)
        self.file.truncate(offset)
        self.bytes_written = offset

    def iter_lines(self):
        self.file.flush()
        self.file.seek(0)
        for line in self.file:
            yield line.decode("utf-8")

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def iter_transformed_ir(lines, *, shared: bool, fault_delivery: bool,
                        width_store, cpu_access, guest_memory_inline: str,
                        guest_tbaa: str, profile: bool = False):
    """Stream existing transformations; output can feed a file or a shard sink."""
    import re
    from ir_profile import event_for_line
    for line in lines:
        if shared and width_store.match(line.rstrip("\n")):
            continue
        if not fault_delivery:
            line = cpu_access.sub(r"\1, !tbaa !990003", line)
            line = line.replace("call i64 @guest_load(", "call i64 @guest_load_fast(")
            line = line.replace("call void @guest_store(", "call void @guest_store_fast(")
            line = line.replace("call void @guest_check_return(", "call void @guest_check_return_fast(")
        if profile:
            event = event_for_line(line)
            if event is not None:
                yield f"  call void @guest_profile_event(i32 {event})\n"
        yield line
    if profile:
        yield "declare void @guest_profile_event(i32)\n"
    if not fault_delivery:
        helpers = re.sub(
            r"^(\s+(?:%\S+ = )?(?:load|store) [^\n]*ptr %pointer, align 1)$",
            r"\1, !tbaa !990004", guest_memory_inline, flags=re.M)
        yield from helpers.splitlines(keepends=True)
        yield from guest_tbaa.splitlines(keepends=True)


def transform_ir_lines(lines, output: Path, **options) -> None:
    """Atomically write the transformed module without assembling it in RAM."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as target:
            for line in iter_transformed_ir(lines, **options):
                target.write(line)
        os.replace(temporary, output)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
