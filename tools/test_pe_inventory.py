"""Portable safety and corpus regression tests for PE import inventory."""
from __future__ import annotations
from pathlib import Path
import sys
import struct
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_inventory


class PEInventoryTests(unittest.TestCase):
    def test_real_corpus_parses_as_pe64(self):
        for name in ('plink.exe', 'jq.exe', 'rg.exe'):
            with self.subTest(name=name):
                path = Path(__file__).resolve().parent.parent / 'work/corpus' / name
                if not path.is_file():
                    self.skipTest(f'optional corpus file unavailable: {name}')
                info = pe_inventory.inventory(path)
                self.assertEqual(info['architecture'], 'x86-64')
                self.assertGreater(info['dll_count'], 0)
                self.assertGreater(info['symbol_count'], 0)

    def test_synthetic_import_by_name_ordinal_and_delay(self):
        """Probe import descriptor/thunk logic independently from bundled samples."""
        buf = bytearray(4096)
        buf[:2] = b'MZ'
        struct.pack_into('<I', buf, 0x3c, 0x80)
        buf[0x80:0x84] = b'PE\x00\x00'
        struct.pack_into('<HHIIIHH', buf, 0x84,
                         0x8664, 1, 0, 0, 0, 240, 0x0022)
        optional = 0x98
        struct.pack_into('<H', buf, optional, 0x20b)
        struct.pack_into('<Q', buf, optional + 24, 0x140000000)
        struct.pack_into('<I', buf, optional + 60, 0x200)
        struct.pack_into('<H', buf, optional + 68, 3)
        struct.pack_into('<I', buf, optional + 108, 16)
        struct.pack_into('<II', buf, optional + 112 + 1 * 8, 0x1100, 40)
        struct.pack_into('<II', buf, optional + 112 + 13 * 8, 0x1180, 64)
        # VirtualAddress=0x1000, PointerToRawData=0x200, size=0xC00
        section = optional + 240
        buf[section:section + 8] = b'.idata\0\0'
        struct.pack_into('<IIII', buf, section + 8, 0xC00, 0x1000, 0xC00, 0x200)
        # Import directory: ORIGINAL_FIRST_THUNK, Name, FirstThunk
        struct.pack_into('<IIIII', buf, 0x300, 0x1250, 0, 0, 0x1200, 0x1250)
        # Delay-import directory with RVA mode
        struct.pack_into('<IIIIIIII', buf, 0x380, 1, 0x1210, 0, 0x1270,
                         0x1270, 0, 0, 0)
        buf[0x400:0x400+13] = b'KERNEL32.dll\0'
        buf[0x410:0x410+11] = b'USER32.dll\0'
        struct.pack_into('<QQQ', buf, 0x450, 0x1300, 1 << 63 | 42, 0)
        struct.pack_into('<QQ', buf, 0x470, 0x1310, 0)
        buf[0x500:0x500+14] = b'\0\0ExitProcess\0'
        buf[0x510:0x510+14] = b'\0\0MessageBoxW\0'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'small.exe'
            path.write_bytes(buf)
            report = pe_inventory.inventory(path)
        self.assertEqual(report['dll_count'], 2)
        self.assertEqual(report['symbol_count'], 3)
        self.assertEqual(report['imports'][0]['symbols'], ['ExitProcess', '#42'])
        self.assertEqual(report['imports'][1]['symbols'], ['MessageBoxW'])
        self.assertTrue(report['imports'][1]['delay'])

    def test_invalid_pe_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.exe'
            path.write_bytes(b'bad')
            with self.assertRaises(pe_inventory.PEError):
                pe_inventory.inventory(path)
            path.write_bytes(b'MZ' + b'\0' * 200)
            with self.assertRaises(pe_inventory.PEError):
                pe_inventory.inventory(path)

    def test_oob_rva_rejected(self):
        path = Path(__file__).resolve().parent.parent / 'work/corpus/plink.exe'
        if not path.is_file():
            self.skipTest('optional corpus file unavailable: plink.exe')
        pe = pe_inventory.PE64(path)
        with self.assertRaises(pe_inventory.PEError):
            pe.rva_to_offset(0xFFFFFFFF, 4)


if __name__ == '__main__':
    unittest.main()
