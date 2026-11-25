"""Emit an exact mapped guest-DLL byte image as a Mach-O assembler input.

The DLL's already-relocated PE section data is written directly to a sparse
binary file, rather than hex-escaping a contiguous bytearray into LLVM IR.
The assembler's .incbin embeds that file once in the native object. This is
AOT data emission; it never loads or executes the guest PE during the build.
"""
from __future__ import annotations

from pathlib import Path
import re

GUEST_IMAGE_ALIGN = 16384
_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def guest_image_span(data, declared_size: int, alignment: int = GUEST_IMAGE_ALIGN) -> int:
    if declared_size < 0 or alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("invalid image size or alignment")
    end = max((rva + size for rva, _, size, _ in data), default=0)
    if any(rva < 0 or size < 0 or len(blob) > size for rva, blob, size, _ in data):
        raise ValueError("invalid guest PE section bounds")
    return (max(end, declared_size) + alignment - 1) & ~(alignment - 1)


def emit_guest_image(data, declared_size: int, *, binary: Path, assembly: Path,
                     symbol: str) -> int:
    """Generate data and .s exposing the same guest_image pointer used before.

    Truncate creates sparse zero-filled gaps on supporting filesystems; section
    payloads are written at exactly their RVA without layout transformations.
    The assembler materializes a real contiguous __DATA,__guest_image region.
    """
    span = guest_image_span(data, declared_size)
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("unsafe Mach-O symbol")
    binary, assembly = Path(binary).resolve(), Path(assembly).resolve()
    if any(char in str(binary) for char in ('\r', '\n', '"')):
        raise ValueError("invalid image file path for .incbin")
    binary.parent.mkdir(parents=True, exist_ok=True)
    assembly.parent.mkdir(parents=True, exist_ok=True)
    with binary.open("wb") as out:
        out.truncate(span)
        for rva, blob, size, _ in data:
            if rva + size > span:
                raise ValueError("section outside mapped guest image")
            if blob:
                out.seek(rva)
                out.write(blob)
    # Mach-O C external symbols have a leading underscore in assembler.
    escaped_path = str(binary).replace("\\", "\\\\")
    assembly.write_text(
        '.section __DATA,__guest_image,regular\n'
        '.p2align 14\n'
        f'.globl _{symbol}\n'
        f'_{symbol}:\n'
        f'.incbin "{escaped_path}"\n', encoding='utf-8')
    return span


def emit_primary_sections(data, *, directory: Path, assembly: Path) -> list[Path]:
    """Embed each initialized main-EXE section without hex-escaped LLVM text.

    Unlike DLLs, primary PE sections are copied independently by the runtime;
    they do not need to be assembled as a single contiguous image. The
    associated section descriptors still retain each original RVA and size.
    """
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    assembly = Path(assembly).resolve()
    assembly.parent.mkdir(parents=True, exist_ok=True)
    sources = []
    asm = ['.section __TEXT,__const,regular']
    for index, (rva, blob, size, _writable) in enumerate(data):
        if rva < 0 or size < 0 or len(blob) > size:
            raise ValueError(f'invalid primary section {index} bounds')
        if not blob:
            continue
        asset = directory / f'primary_section_{index}.bin'
        if any(c in str(asset) for c in ('\r', '\n', '"')):
            raise ValueError('invalid path for primary PE section')
        asset.write_bytes(blob)
        sources.append(asset)
        escaped_path = str(asset).replace("\\", "\\\\")
        asm.extend(('.p2align 4', f'.globl _guest_section_{index}',
                    f'_guest_section_{index}:', f'.incbin "{escaped_path}"'))
    assembly.write_text('\n'.join(asm) + '\n', encoding='utf-8')
    return sources
