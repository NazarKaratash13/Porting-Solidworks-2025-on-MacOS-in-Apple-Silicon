from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_ports


class ComparePortTests(unittest.TestCase):
    def test_matching_outputs(self):
        python = Path(sys.executable)
        result = compare_ports.compare(python, python, ['-c', 'print(42)'], repeats=2, warmups=0)
        self.assertTrue(result['match_cli_outputs'])
        self.assertEqual(len(result['samples']['monolithic']), 2)

    def test_detects_different_program_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / 'left.sh'
            right = Path(tmp) / 'right.sh'
            left.write_text('#!/bin/sh\necho correct\n')
            right.write_text('#!/bin/sh\necho incorrect\n')
            left.chmod(0o755)
            right.chmod(0o755)
            result = compare_ports.compare(left, right, [], repeats=2, warmups=0)
            self.assertFalse(result['match_cli_outputs'])
            self.assertEqual(result['differing_runs'], [0, 1])

    def test_bad_parameters(self):
        with self.assertRaises(ValueError):
            compare_ports.compare(Path('/none'), Path('/none'), [], repeats=0)
