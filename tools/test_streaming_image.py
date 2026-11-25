"""Regression gates for disk IR emission and binary Mach-O DLL payloads.

These tests run without Capstone/pefile or a macOS host linker. The optional
cross-assembler test verifies the generated object format when Clang supports it.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recompiler'))
from ir_spool import DiskLineSpool, transform_ir_lines
from guest_image_object import emit_guest_image, emit_primary_sections, guest_image_span

WIDTH_STORE = re.compile(r'\s+store i8 \S+, ptr %\w+_width$')
CPU_ACCESS = re.compile(r'^(\s+(?:%\S+ = )?(?:load|store) [^\n]*ptr %(?!v\d+\b)[A-Za-z_]\w*(?:, align \d+)?)$', re.M)
HELPERS = '\ndefine internal i64 @guest_load_fast(i64 %addr) {\n  %val = load i8, ptr %pointer, align 1\n  ret i64 0\n}\n'
TBAA = '\n!990003 = !{!990001, !990001, i64 0}\n'


def original_transform(lines, *, shared, fault_delivery):
    text = '\n'.join(line for line in lines if not shared or not WIDTH_STORE.match(line)) + '\n'
    if not fault_delivery:
        text = CPU_ACCESS.sub(r'\1, !tbaa !990003', text)
        text = text.replace('call i64 @guest_load(', 'call i64 @guest_load_fast(')
        text = text.replace('call void @guest_store(', 'call void @guest_store_fast(')
        text = text.replace('call void @guest_check_return(', 'call void @guest_check_return_fast(')
        helpers = re.sub(r'^(\s+(?:%\S+ = )?(?:load|store) [^\n]*ptr %pointer, align 1)$',
                         r'\1, !tbaa !990004', HELPERS, flags=re.M)
        text += helpers + TBAA
    return text


class StreamingIRTests(unittest.TestCase):
    def test_stream_matches_old_ir_for_all_flags(self):
        cases = [
            'define internal void @demo(ptr %cpu) {',
            'entry:',
            '  %rax = getelementptr i64, ptr %cpu, i32 0',
            '  %v2 = load i64, ptr %rax',
            '  %v3 = call i64 @guest_load(i64 10, i32 8)',
            '  call void @guest_store(i64 1, i64 2, i32 4)',
            '  call void @guest_check_return(i64 1, i64 2)',
            '  store i8 64, ptr %rax_width',
            '  store i64 %v2, ptr %rax',
            '  ret void', '}',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for shared in (False, True):
                for fault_delivery in (False, True):
                    out = Path(tmp) / f'{shared}-{fault_delivery}.ll'
                    with DiskLineSpool(Path(tmp)) as spool:
                        for line in cases:
                            spool.append(line)
                        transform_ir_lines(spool.iter_lines(), out, shared=shared,
                                           fault_delivery=fault_delivery,
                                           width_store=WIDTH_STORE, cpu_access=CPU_ACCESS,
                                           guest_memory_inline=HELPERS, guest_tbaa=TBAA)
                    self.assertEqual(out.read_text(), original_transform(
                        cases, shared=shared, fault_delivery=fault_delivery))

    def test_rollback_removes_only_partial_instruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            with DiskLineSpool(Path(tmp)) as spool:
                spool.append('define void @f() {')
                before = spool.checkpoint()
                spool.append('  %invalid = add i64 1, 2')
                spool.append('  %invalid2 = xor i32 2, 1')
                spool.rollback(before)
                spool.append('  call void @trap()')
                spool.append('}')
                self.assertEqual(''.join(spool.iter_lines()),
                                 'define void @f() {\n  call void @trap()\n}\n')

    def test_large_ir_does_not_collect_lines_in_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracemalloc.start()
            try:
                with DiskLineSpool(Path(tmp)) as spool:
                    line = '  ; ' + 'x' * 8192
                    for _ in range(1600):
                        spool.append(line)
                    current, peak = tracemalloc.get_traced_memory()
                    self.assertGreater(spool.bytes_written, 12 * 1024 * 1024)
                    self.assertLess(peak, 3 * 1024 * 1024)
            finally:
                tracemalloc.stop()

    def test_atomic_output_not_replaced_on_failed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'keep.ll'
            out.write_text('old good output')
            def bad_lines():
                yield 'header\n'
                raise RuntimeError('interrupted')
            with self.assertRaises(RuntimeError):
                transform_ir_lines(bad_lines(), out, shared=False, fault_delivery=True,
                                   width_store=WIDTH_STORE, cpu_access=CPU_ACCESS,
                                   guest_memory_inline=HELPERS, guest_tbaa=TBAA)
            self.assertEqual(out.read_text(), 'old good output')
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])


class MachOGuestImageTests(unittest.TestCase):
    def test_guest_payload_preserves_layout_and_zero_gaps(self):
        data = [(0, b'MZ\x00\x01', 12, False),
                (0x1000, b'\x10\x20\x30', 24, False),
                (0x8000, b'\xfb' * 12, 0x4000, True)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, assembly = root / 'mapped.bin', root / 'mapped.s'
            size = emit_guest_image(data, 0xc100, binary=binary,
                                    assembly=assembly, symbol='module_test_guest_image')
            self.assertEqual(size, 0x10000)
            raw = binary.read_bytes()
            original = bytearray(size)
            for rva, blob, _, _ in data:
                original[rva:rva + len(blob)] = blob
            self.assertEqual(raw, original)
            self.assertIn('.section __DATA,__guest_image,regular', assembly.read_text())
            self.assertIn('.p2align 14', assembly.read_text())
            self.assertIn('_module_test_guest_image:', assembly.read_text())

    def test_primary_section_assets_preserve_exact_initialized_bytes(self):
        data = [(0, b'MZ\x00', 32, False), (4096, b'', 8192, True),
                (8192, bytes(range(256)), 4096, True)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assembly = root / 'main_sections.s'
            blobs = emit_primary_sections(data, directory=root / 'data',
                                          assembly=assembly)
            self.assertEqual([p.read_bytes() for p in blobs], [b'MZ\x00', bytes(range(256))])
            asm = assembly.read_text()
            self.assertIn('_guest_section_0:', asm)
            self.assertNotIn('_guest_section_1:', asm)
            self.assertIn('_guest_section_2:', asm)
            self.assertIn('.section __TEXT,__const,regular', asm)
            if shutil.which('clang') and shutil.which('llvm-objdump'):
                obj = root / 'main_sections.o'
                compiled = subprocess.run(['clang', '-target', 'arm64-apple-macos11',
                                           '-c', str(assembly), '-o', str(obj)],
                                          capture_output=True, text=True)
                if compiled.returncode:
                    self.skipTest('cross assembler unavailable: ' + compiled.stderr)
                symbols = subprocess.run(['llvm-objdump', '--syms', str(obj)],
                                         capture_output=True, text=True, check=True).stdout
                self.assertIn('_guest_section_0', symbols)
                self.assertIn('_guest_section_2', symbols)
                self.assertNotIn('_guest_section_1', symbols)

    def test_bad_bounds_and_symbols_rejected(self):
        with self.assertRaises(ValueError):
            guest_image_span([(5, b'ABC', 2, False)], 4096)
        with self.assertRaises(ValueError):
            guest_image_span([(-1, b'A', 1, False)], 4096)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                emit_guest_image([], 1, binary=Path(tmp) / 'a.bin',
                                 assembly=Path(tmp) / 'a.s', symbol='x;evil')

    @unittest.skipUnless(shutil.which('clang') and shutil.which('llvm-objdump'),
                         'optional Mach-O cross assembler unavailable')
    def test_macho_arm64_assembler_emits_real_data_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assembly, obj = root / 'guest.s', root / 'guest.o'
            emit_guest_image([(0, b'MZ', 2, False), (0x2000, b'PE', 2, False)],
                             0x3000, binary=root / 'guest.bin', assembly=assembly,
                             symbol='module_test_guest_image')
            compiled = subprocess.run(['clang', '-target', 'arm64-apple-macos11',
                                       '-c', str(assembly), '-o', str(obj)],
                                      capture_output=True, text=True)
            if compiled.returncode:
                self.skipTest('toolchain cannot cross-assemble Apple Mach-O: ' + compiled.stderr)
            symbols = subprocess.run(['llvm-objdump', '--syms', '--section-headers', str(obj)],
                                     capture_output=True, text=True, check=True).stdout
            self.assertIn('file format mach-o arm64', symbols)
            self.assertIn('_module_test_guest_image', symbols)
            self.assertIn('__DATA,__guest_image', symbols)
            self.assertIn('00004000', symbols)


if __name__ == '__main__':
    unittest.main()
