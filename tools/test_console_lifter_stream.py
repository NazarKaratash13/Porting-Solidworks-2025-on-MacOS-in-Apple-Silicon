"""Run the actual ConsoleLift finishing and PE relocation logic with stub imports.

Capstone/pefile are not needed here because no instruction decoding occurs.
The real lifted x86 -> ARM64 path must still be tested on macOS.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import shutil
import tracemalloc
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recompiler'))


def load_lifter():
    capstone = types.ModuleType('capstone')
    x86_const = types.ModuleType('capstone.x86_const')
    capstone.x86_const = x86_const
    pefile = types.ModuleType('pefile')
    with mock.patch.dict(sys.modules, {
        'capstone': capstone, 'capstone.x86_const': x86_const,
        'pefile': pefile,
    }):
        spec = importlib.util.spec_from_file_location(
            '_stream_lifter_test', ROOT / 'recompiler/console_lift.py')
        lifter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lifter)
    return lifter


lifter_mod = load_lifter()
DiskLineSpool = lifter_mod.DiskLineSpool


def fake_lifter(lines, *, shared=False, fault_delivery=False):
    obj = lifter_mod.ConsoleLift.__new__(lifter_mod.ConsoleLift)
    obj.lines = lines
    obj.overrides = {}
    obj.override_caches = []
    obj.functions = {0x1000: 'guest_fn_1000'}
    obj.image_base = 0x140000000
    obj.is_module = False
    obj.bound_slots = []
    obj.traps = {}
    obj.strings = {}
    obj.shared = shared
    obj.fault_delivery = fault_delivery
    return obj


class LifterStreamTests(unittest.TestCase):
    def test_finish_module_is_byte_identical_across_flags(self):
        body = [
            'define internal void @guest_fn_1000(ptr %cpu, i64 %return_va) {',
            'entry:',
            '  %rax = getelementptr i64, ptr %cpu, i32 0',
            '  %v1 = load i64, ptr %rax',
            '  %v2 = call i64 @guest_load(i64 4, i32 8)',
            '  store i64 %v1, ptr %rax',
            '  store i8 128, ptr %rax_width',
            '  ret void', '}',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for shared in (False, True):
                for fault_delivery in (False, True):
                    expected = fake_lifter(body.copy(), shared=shared,
                                           fault_delivery=fault_delivery).finish_module()
                    with DiskLineSpool(Path(tmp)) as spool:
                        for line in body:
                            spool.append(line)
                        obj = fake_lifter(spool, shared=shared,
                                          fault_delivery=fault_delivery)
                        obj._output_path = Path(tmp) / f'{shared}-{fault_delivery}.ll'
                        self.assertIsNone(obj.finish_module())
                    self.assertEqual(obj._output_path.read_bytes(), expected.encode())

    def test_streaming_wrapper_frees_spool_on_success_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'main.ll'
            obj = fake_lifter([])
            def simple_emit(self, *args, **kwargs):
                self.line('define void @f() { ret void }')
                return self.finish_module()
            with mock.patch.object(lifter_mod.ConsoleLift, 'emit_console', simple_emit):
                self.assertIsNone(obj.emit_console_to_file(0, 0, b'', [], output))
            self.assertIn('define void @f()', output.read_text())
            self.assertEqual(obj.lines, [])
            bad = fake_lifter([])
            def broken_emit(self, *args, **kwargs):
                self.line('partial')
                raise ValueError('broken guest instruction')
            with mock.patch.object(lifter_mod.ConsoleLift, 'emit_console', broken_emit):
                with self.assertRaises(ValueError):
                    bad.emit_console_to_file(0, 0, b'', [], output)
            self.assertNotIn('partial', output.read_text())
            self.assertEqual(bad.lines, [])

    def test_real_emitter_stream_matches_legacy_and_assembles_arm64_ir(self):
        # Exercise the real emit_console() path with decoding intentionally
        # stubbed: tests LLVM declarations, section pointers and finish_module,
        # not x86 instruction support or the final macOS link.
        class Image:
            OPTIONAL_HEADER = types.SimpleNamespace(
                ImageBase=0x140000000, SizeOfImage=0x3000,
                AddressOfEntryPoint=0x1000)
            sections = []
            def get_section_by_rva(self, rva):
                return None
        def empty_guest_functions(obj, base, code):
            for name in obj.functions.values():
                obj.line(f'define internal void @{name}(ptr %cpu, i64 %return_va) {{')
                obj.line('entry:')
                obj.line('  ret void')
                obj.line('}')
        data = [(0, b'MZ' + b'\0' * 62, 64, False),
                (0x2000, b'guest!\0', 32, True)]
        with tempfile.TemporaryDirectory() as tmp:
            ll = Path(tmp) / 'lifted.ll'
            with mock.patch.object(lifter_mod.ConsoleLift, 'emit_functions',
                                   empty_guest_functions):
                first = lifter_mod.ConsoleLift(Image(), callback_targets={}, bound_dlls=set())
                first.emit_console_to_file(0x1000, 0x1000, b'', data, ll,
                                           module='unit_test', external_image=True)
                old = lifter_mod.ConsoleLift(Image(), callback_targets={}, bound_dlls=set())
                expected = old.emit_console(0x1000, 0x1000, b'', data,
                                            module='unit_test', external_image=True)
                legacy = lifter_mod.ConsoleLift(Image(), callback_targets={}, bound_dlls=set())
                old_text = legacy.emit_console(0x1000, 0x1000, b'', data,
                                                module='unit_test', external_image=False)
            self.assertEqual(ll.read_text(), expected)
            self.assertEqual(ll.read_text().split('\n', 1)[1],
                             old_text.split('\n', 1)[1],
                             'section descriptors must be byte-identical')
            self.assertTrue(ll.read_text().startswith(
                '@unit_test_guest_image = external global [16384 x i8]'))
            if shutil.which('clang') and shutil.which('llvm-objdump'):
                out = Path(tmp) / 'lifted.o'
                cmd = subprocess.run(['clang', '-target', 'arm64-apple-macos11',
                                      '-c', str(ll), '-o', str(out)],
                                     capture_output=True, text=True)
                if cmd.returncode:
                    self.skipTest('cross LLVM backend unavailable: ' + cmd.stderr)
                symbols = subprocess.run(['llvm-objdump', '--syms', str(out)],
                                         capture_output=True, text=True, check=True).stdout
                self.assertIn('_unit_test_guest_image', symbols)

    def test_real_primary_emitter_links_external_section_symbols_in_ir(self):
        empty_directory = types.SimpleNamespace(VirtualAddress=0, Size=0)
        class Image:
            OPTIONAL_HEADER = types.SimpleNamespace(
                ImageBase=0x140000000, SizeOfImage=0x4000,
                AddressOfEntryPoint=0x1000,
                DATA_DIRECTORY=[empty_directory] * 4)
            sections = []
            def get_section_by_rva(self, rva):
                return None
        def empty_guest_functions(obj, base, code):
            for name in obj.functions.values():
                obj.line(f'define internal void @{name}(ptr %cpu, i64 %return_va) {{')
                obj.line('entry:')
                obj.line('  ret void')
                obj.line('}')
        data = [(0, b'MZ\0\0', 8, False), (0x2000, b'ABC', 16, True)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'main.ll'
            with mock.patch.object(lifter_mod.ConsoleLift, 'emit_functions', empty_guest_functions):
                obj = lifter_mod.ConsoleLift(Image(), callback_targets={})
                obj.emit_console_to_file(0x1000, 0x1000, b'', data, output,
                                         external_sections=True)
                old = lifter_mod.ConsoleLift(Image(), callback_targets={})
                baseline = old.emit_console(0x1000, 0x1000, b'', data)
            text = output.read_text()
            self.assertIn('@guest_section_0 = external constant [4 x i8]', text)
            self.assertIn('@guest_section_1 = external constant [3 x i8]', text)
            self.assertNotIn('c"\\4d\\5a', text)
            # Removing ONLY payload declarations leaves byte-identical code,
            # dispatch metadata, guest section addresses/sizes, and helpers.
            def strip_section_declarations(ir):
                return '\n'.join(line for line in ir.split('\n')
                                 if not line.startswith('@guest_section_'))
            self.assertEqual(strip_section_declarations(text),
                             strip_section_declarations(baseline))
            if shutil.which('clang'):
                result = subprocess.run(['clang', '-target', 'arm64-apple-macos11',
                                         '-c', str(output), '-o', str(root / 'main.o')],
                                        capture_output=True, text=True)
                if result.returncode:
                    self.skipTest('cross LLVM compiler unavailable: ' + result.stderr)
                if shutil.which('llvm-objdump'):
                    symbols = subprocess.run(['llvm-objdump', '--syms', str(root / 'main.o')],
                                             capture_output=True, text=True, check=True).stdout
                    self.assertIn('_guest_section_0', symbols)
                    self.assertIn('_guest_section_1', symbols)

    def test_sparse_bss_is_not_materialized_for_unused_relocations(self):
        image_base = 0x140000000
        code = bytearray(b'\x90' * 64)
        code[8:16] = (image_base + 0x2000).to_bytes(8, 'little')
        class Section:
            def __init__(self, address, size, flags, raw, initialized=True):
                self.VirtualAddress = address
                self.Misc_VirtualSize = size
                self.Characteristics = flags
                self.SizeOfRawData = len(raw)
                self.PointerToRawData = int(initialized)
                self.raw = bytes(raw)
            def get_data(self):
                return self.raw
        section = Section(0x1000, len(code), 0x60000000, code)
        bss = Section(0x2000, 8 * 1024 * 1024, 0xC0000000, b'', initialized=False)
        class Image:
            FILE_HEADER = types.SimpleNamespace(Machine=0x8664)
            OPTIONAL_HEADER = types.SimpleNamespace(
                Magic=0x20B, AddressOfEntryPoint=0x1000,
                SizeOfHeaders=0x100, SizeOfImage=0x810000, ImageBase=image_base)
            __data__ = b'MZ' + b'\0' * 254
            sections = [section, bss]
            DIRECTORY_ENTRY_BASERELOC = [types.SimpleNamespace(entries=[
                types.SimpleNamespace(type=10, rva=0x1008)])]
            def get_section_by_rva(self, rva):
                return section if rva == 0x1000 else None
        tracemalloc.start()
        try:
            entry, base, decoded, chunks = lifter_mod.read_console_image(
                Image(), load_base=0x10000000000)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual((entry, base), (0x1000, 0x1000))
        self.assertEqual(int.from_bytes(chunks[1][1][8:16], 'little'), 0x10000002000)
        self.assertEqual(chunks[2][1], b'')
        self.assertLess(peak, 2 * 1024 * 1024, 'large zero-fill section must remain lazy')


if __name__ == '__main__':
    unittest.main()
