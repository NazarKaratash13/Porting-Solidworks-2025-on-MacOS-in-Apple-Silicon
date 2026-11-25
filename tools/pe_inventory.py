#!/usr/bin/env python3
"""Read static/delay PE32+ x64 imports without running Windows code or requiring pip.

This is inventory, NOT proof of ABI/API compatibility or DLL loadability.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

MAX_FILE = 256 * 1024 * 1024
MAX_DESCRIPTORS = 4096
MAX_IMPORTS = 65536


class PEError(ValueError):
    pass


class PE64:
    def __init__(self, path: Path):
        self.path = path
        if path.stat().st_size > MAX_FILE:
            raise PEError(f'file exceeds inventory limit of {MAX_FILE} bytes')
        self.data = path.read_bytes()
        if len(self.data) < 0x40 or self.data[:2] != b'MZ':
            raise PEError('missing DOS MZ header')
        pe_off, = self.unpack('<I', 0x3c)
        if pe_off > len(self.data) - 24 or self.data[pe_off:pe_off + 4] != b'PE\0\0':
            raise PEError('missing PE signature')
        self.machine, self.section_count, _, _, _, opt_size, _ = self.unpack('<HHIIIHH', pe_off + 4)
        if self.machine != 0x8664:
            raise PEError(f'expected x86-64 PE (machine 0x8664), got {self.machine:#x}')
        if not (0 < self.section_count <= 96):
            raise PEError('invalid section count')
        opt = pe_off + 24
        if opt_size < 112 or opt + opt_size > len(self.data):
            raise PEError('invalid PE optional header')
        magic, = self.unpack('<H', opt)
        if magic != 0x20b:
            raise PEError('expected PE32+ (64-bit) optional header')
        self.image_base, = self.unpack('<Q', opt + 24)
        self.size_of_headers, = self.unpack('<I', opt + 60)
        self.subsystem, = self.unpack('<H', opt + 68)
        directory_count, = self.unpack('<I', opt + 108)
        self.directories = {}
        for number in (1, 13):  # Import and Delay Import Directory
            if number < directory_count and 112 + (number + 1) * 8 <= opt_size:
                self.directories[number] = self.unpack('<II', opt + 112 + number * 8)
            else:
                self.directories[number] = (0, 0)
        self.sections = []
        for index in range(self.section_count):
            sec = opt + opt_size + index * 40
            if sec + 40 > len(self.data):
                raise PEError('truncated section table')
            vs, va, rawsize, rawptr = self.unpack('<IIII', sec + 8)
            if rawsize and rawptr > len(self.data):
                raise PEError('section raw pointer outside file')
            self.sections.append((va, vs, rawptr, rawsize))

    def unpack(self, fmt: str, offset: int):
        if offset < 0 or offset + struct.calcsize(fmt) > len(self.data):
            raise PEError(f'truncated PE data at file offset {offset:#x}')
        return struct.unpack_from(fmt, self.data, offset)

    def rva_to_offset(self, rva: int, needed: int = 1) -> int:
        if rva < self.size_of_headers and rva + needed <= len(self.data):
            return rva
        for va, vsize, rawptr, rawsize in self.sections:
            delta = rva - va
            if 0 <= delta and delta + needed <= rawsize and delta < max(vsize, rawsize):
                offset = rawptr + delta
                if offset + needed <= len(self.data):
                    return offset
        raise PEError(f'RVA {rva:#x} is not backed by file data')

    def c_string(self, rva: int) -> str:
        off = self.rva_to_offset(rva)
        end = self.data.find(b'\x00', off, min(len(self.data), off + 4096))
        if end == -1:
            raise PEError(f'unterminated import name at RVA {rva:#x}')
        return self.data[off:end].decode('ascii', errors='replace')

    def thunks(self, table_rva: int, *, is_va: bool = False) -> list[str]:
        if table_rva == 0:
            return []
        if is_va:
            table_rva -= self.image_base
        entries = []
        for index in range(MAX_IMPORTS):
            item_rva = table_rva + index * 8
            offset = self.rva_to_offset(item_rva, 8)
            value, = self.unpack('<Q', offset)
            if value == 0:
                return entries
            if value & (1 << 63):
                entries.append(f'#{value & 0xffff}')
                continue
            name_rva = value - self.image_base if is_va else value
            self.rva_to_offset(name_rva, 3)  # 2-byte hint followed by name
            entries.append(self.c_string(name_rva + 2))
        raise PEError('import thunk count exceeds safety limit')

    def regular_imports(self) -> list[dict]:
        rva, size = self.directories[1]
        if not rva or not size:
            return []
        result = []
        for index in range(min(MAX_DESCRIPTORS, size // 20)):
            off = self.rva_to_offset(rva + index * 20, 20)
            ilt, timestamp, chain, name_rva, iat = self.unpack('<IIIII', off)
            if not any((ilt, timestamp, chain, name_rva, iat)):
                return result
            if not name_rva:
                raise PEError('import descriptor without DLL name RVA')
            result.append({'dll': self.c_string(name_rva),
                           'symbols': self.thunks(ilt or iat), 'delay': False})
        if size // 20 >= MAX_DESCRIPTORS:
            raise PEError('import descriptor count exceeds safety limit')
        raise PEError('unterminated import descriptor array')

    def delay_imports(self) -> list[dict]:
        rva, size = self.directories[13]
        if not rva or not size:
            return []
        result = []
        for index in range(min(MAX_DESCRIPTORS, size // 32)):
            off = self.rva_to_offset(rva + index * 32, 32)
            values = self.unpack('<IIIIIIII', off)
            if not any(values):
                return result
            attrs, name, _, iat, int_table, _, _, _ = values
            is_va = not bool(attrs & 1)
            name_rva = name - self.image_base if is_va else name
            result.append({'dll': self.c_string(name_rva),
                           'symbols': self.thunks(int_table or iat, is_va=is_va),
                           'delay': True})
        if size // 32 >= MAX_DESCRIPTORS:
            raise PEError('delay-import descriptor count exceeds safety limit')
        raise PEError('unterminated delay-import descriptor array')


def inventory(path: Path) -> dict:
    image = PE64(path)
    imports = image.regular_imports() + image.delay_imports()
    return {'file': str(path), 'architecture': 'x86-64',
            'subsystem': image.subsystem, 'image_base': hex(image.image_base),
            'dll_count': len({x['dll'].lower() for x in imports}),
            'symbol_count': sum(len(x['symbols']) for x in imports),
            'imports': imports}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+', help='PE files or folders (non-recursive)')
    parser.add_argument('--output', '-o', type=Path, help='write JSON report to a file')
    options = parser.parse_args(argv)
    files = sorted({child for path in options.files for child in (
        sorted(p for p in path.iterdir() if p.suffix.lower() in {'.exe', '.dll'})
        if path.is_dir() else [path])})
    results = []
    for path in files:
        try:
            results.append(inventory(path))
        except (OSError, PEError) as error:
            results.append({'file': str(path), 'error': str(error)})
    data = json.dumps(results, indent=2, ensure_ascii=False) + '\n'
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(data, encoding='utf-8')
        print(f'Inventory saved: {options.output}')
    else:
        sys.stdout.write(data)
    return int(any('error' in item for item in results))


if __name__ == '__main__':
    raise SystemExit(main())
