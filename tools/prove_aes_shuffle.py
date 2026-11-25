#!/usr/bin/env python3
"""SMT proof of AESKEYGENASSIST byte shuffle and round-constant placement only.
SubBytes outputs are arbitrary independent 8-bit values; the proof assumes
AESE's documented ShiftRows layout. It does not prove the AES primitive itself.
"""
import argparse
import ctypes
import ctypes.util
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'recompiler'))
from aes_ir import KEYGEN_SHUFFLE


def formula():
    lines=['(set-logic QF_BV)']
    for i in range(16): lines.append(f'(declare-fun b{i} () (_ BitVec 8))')
    lines.append('(declare-fun rc () (_ BitVec 8))')
    # Model AESE output layout independently from generated shuffle.
    arm=[f'b{4*((col+row)%4)+row}' for col in range(4) for row in range(4)]
    got=[arm[i] for i in KEYGEN_SHUFFLE]
    expected=['b4','b5','b6','b7','b5','b6','b7','b4','b12','b13','b14','b15','b13','b14','b15','b12']
    # Each selected byte is independent. Any counterexample makes SAT.
    for i in (4,12):
        got[i]=f'(bvxor {got[i]} rc)';expected[i]=f'(bvxor rc {expected[i]})'
    lines.append('(assert (or '+' '.join(f'(not (= {a} {b}))' for a,b in zip(got,expected))+'))')
    lines.append('(check-sat)')
    return '\n'.join(lines)+'\n'


def solve(text):
    binary=shutil.which('z3')
    if binary: return subprocess.check_output([binary,'-in'],input=text,text=True).strip()
    lib=ctypes.util.find_library('z3')
    if not lib: raise RuntimeError('Z3 unavailable: install brew install z3')
    z=ctypes.CDLL(lib)
    z.Z3_mk_config.restype=ctypes.c_void_p
    z.Z3_mk_context.argtypes=[ctypes.c_void_p];z.Z3_mk_context.restype=ctypes.c_void_p
    z.Z3_del_config.argtypes=[ctypes.c_void_p]
    z.Z3_del_context.argtypes=[ctypes.c_void_p]
    z.Z3_eval_smtlib2_string.argtypes=[ctypes.c_void_p,ctypes.c_char_p];z.Z3_eval_smtlib2_string.restype=ctypes.c_char_p
    cfg=z.Z3_mk_config();ctx=z.Z3_mk_context(cfg);z.Z3_del_config(cfg)
    try: return z.Z3_eval_smtlib2_string(ctx,text.encode()).decode().strip()
    finally: z.Z3_del_context(ctx)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--emit',action='store_true');args=parser.parse_args()
    if args.emit: print(formula(),end='')
    else:
        result=solve(formula());print(result)
        if result!='unsat': raise SystemExit(1)
        print('PASS: no byte-permutation/round-constant counterexample under stated model')
