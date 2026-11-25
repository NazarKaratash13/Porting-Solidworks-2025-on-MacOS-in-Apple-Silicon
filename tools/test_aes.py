import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'recompiler')]
from aes_differential import CASES, VECTORS, arm_ir, name, x86_aes_available
from aes_model import round_model
from prove_aes_shuffle import formula, solve


class AesTests(unittest.TestCase):
    def test_portable_arm_model_against_native_x86_oracle(self):
        for row in json.loads(VECTORS.read_text())['rows']:
            a,b=bytes.fromhex(row['a']),bytes.fromhex(row['b'])
            for op,imm in CASES:
                self.assertEqual(round_model(op,a,b,imm).hex(),row['expected'][name(op,imm)],(op,imm,a.hex(),b.hex()))

    def test_actual_emitter_cross_compiles_to_hardware_aes(self):
        if not shutil.which('clang'):self.skipTest('clang unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'aes.ll';path.write_text(arm_ir());out=path.with_suffix('.s')
            subprocess.run(['clang','-target','arm64-apple-macos11','-O2','-S',str(path),'-o',str(out)],check=True,capture_output=True)
            assembly=out.read_text()
            for instruction in ('aese','aesmc','aesd','aesimc'):
                self.assertRegex(assembly,r'\b'+instruction+r'\b')

    def test_hardware_differential_when_available(self):
        if not shutil.which('clang'):self.skipTest('clang unavailable')
        arch=platform.machine().lower()
        if arch in ('arm64','aarch64'): args=['--require-arm64']
        elif arch in ('x86_64','amd64') and x86_aes_available():args=[]
        else:self.skipTest('native AES unavailable')
        subprocess.run([sys.executable,str(ROOT/'tools/aes_differential.py'),*args],check=True)

    def test_smt_keygen_permutation(self):
        try: result=solve(formula())
        except RuntimeError as e:self.skipTest(str(e))
        self.assertEqual(result,'unsat')

if __name__=='__main__': unittest.main()
