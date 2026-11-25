"""Offline, platform-independent self-tests for the added preparation tooling."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import doctor


class DoctorTests(unittest.TestCase):
    def test_corpus_files_are_x64_pe(self):
        for name in ('plink.exe', 'jq.exe', 'rg.exe'):
            with self.subTest(name=name):
                path = doctor.ROOT / 'work/corpus' / name
                if not path.is_file():
                    self.skipTest(f'optional corpus file unavailable: {name}')
                valid, details = doctor.inspect_pe(path)
                self.assertTrue(valid, details)

    def test_reject_non_pe_and_truncated(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'test.exe'
            p.write_bytes(b'not a PE')
            self.assertFalse(doctor.inspect_pe(p)[0])
            p.write_bytes(b'MZ' + b'\x00' * 14)
            self.assertFalse(doctor.inspect_pe(p)[0])

    def test_wine_root_prefers_setup_wine_path_and_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            preferred = root / 'recompiler/wine-runtime' / doctor.WINE_SUFFIX
            legacy = root / 'work/wine' / doctor.WINE_SUFFIX
            legacy.mkdir(parents=True)
            with patch.object(doctor, 'ROOT', root), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(doctor.wine_root(), legacy)
                preferred.mkdir(parents=True)
                self.assertEqual(doctor.wine_root(), preferred)
                with patch.dict('os.environ', {'WINE_ROOT': '/custom/wine'}):
                    self.assertEqual(doctor.wine_root(), Path('/custom/wine'))

    def test_report_is_complete_and_side_effect_free(self):
        result = doctor.report('base')
        self.assertIn('ready', result)
        self.assertIn('checks', result)
        plink = next(c for c in result['checks'] if c['name'] == 'corpus/plink.exe')
        expected, _ = doctor.inspect_pe(doctor.ROOT / 'work/corpus/plink.exe')
        self.assertEqual(plink['ok'], expected)


if __name__ == '__main__':
    unittest.main()
