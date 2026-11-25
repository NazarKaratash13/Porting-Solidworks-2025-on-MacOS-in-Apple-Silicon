"""Portable tests for the development harness; do not require third-party packages."""
from __future__ import annotations

from pathlib import Path
import contextlib
import io
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev


class DevTests(unittest.TestCase):
    def test_source_scan_detects_invalid_python_and_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'good.py').write_text('x = 1\n')
            (root / 'bad.py').write_text('def broken(\n')
            (root / 'bad.sh').write_text('#!/bin/bash\nif\n')
            result = dev.scan_sources(root)
            self.assertFalse(result['ok'])
            self.assertEqual(result['python_files'], 2)
            self.assertEqual(result['shell_files'], 1)
            self.assertTrue(any('bad.py' in err for err in result['errors']))
            if dev.shutil.which('bash'):
                self.assertTrue(any('bad.sh' in err for err in result['errors']))

    def test_source_digest_changes_with_content_not_mtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'module.py'
            source.write_text('x=1')
            first, count = dev.source_digest(root)
            self.assertEqual(count, 1)
            source.write_text('x=1')
            second, _ = dev.source_digest(root)
            self.assertEqual(first, second)
            source.write_text('x=2')
            third, _ = dev.source_digest(root)
            self.assertNotEqual(first, third)

    def test_ignores_generated_work_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'test.py').write_text('pass')
            (root / 'work').mkdir()
            (root / 'work/venv.py').write_text('bad syntax (')
            (root / '__pycache__').mkdir()
            (root / '__pycache__/bad.py').write_text('bad syntax (')
            result = dev.scan_sources(root)
            self.assertTrue(result['ok'], result['errors'])
            self.assertEqual(result['python_files'], 1)

    def test_native_test_is_rejected_before_execution_off_mac(self):
        with patch.object(dev, 'native_platform', return_value=False):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(dev.native_gate(), 2)

    def test_manifest_contains_real_corpus_hashes(self):
        report = dev.manifest()
        self.assertEqual(report['format'], 1)
        self.assertEqual(set(report['corpus']), set(dev.CORPUS))
        for name, item in report['corpus'].items():
            with self.subTest(name=name):
                if not (dev.ROOT / 'work/corpus' / name).is_file():
                    self.assertFalse(item['valid_x86_64_pe'])
                    self.assertIsNone(item['sha256'])
                else:
                    self.assertTrue(item['valid_x86_64_pe'])
                    self.assertEqual(len(item['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
