#!/usr/bin/env python3
"""Native x86 AES-NI oracle vectors vs our actual ARM64 LLVM instruction emitter.

The checked-in vectors are recorded from x86 hardware, not from the ARM
implementation. ARM64 comparison is compulsory with --require-arm64.
"""
import argparse
import ctypes
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'recompiler'))
from aes_ir import INTRINSICS, V, emit_round

VECTORS = ROOT/'tools/fixtures/aes_x86_oracle.json'
CASES = [('aesenc',None),('aesenclast',None),('aesdec',None),('aesdeclast',None),('aesimc',None)] + [('aeskeygenassist',i) for i in (0,1,0x1b,0x80,0xff)]


def name(op, imm): return 'test_'+op + ('' if imm is None else '_'+str(imm))


def arm_ir():
    out = [*INTRINSICS]
    for op, imm in CASES:
        out.extend([f'define void @{name(op,imm)}(ptr %ap, ptr %bp, ptr %out) {{','entry:',
                    f'  %a = load {V}, ptr %ap, align 1',f'  %b = load {V}, ptr %bp, align 1'])
        counter = 0
        def value(expr):
            nonlocal counter
            counter += 1
            symbol = f'%r{counter}'
            out.append(f'  {symbol} = {expr}')
            return symbol
        result = emit_round(value,op,'%a','%b',imm)
        out.extend([f'  store {V} {result}, ptr %out, align 1','  ret void','}'])
    return '\n'.join(out)+'\n'


def x86_source():
    out=['#include <wmmintrin.h>']
    for op, imm in CASES:
        args = 'b' if op=='aesimc' else (f'b, {imm}' if imm is not None else 'a, b')
        out.append(f'void {name(op,imm)}(const void *ap, const void *bp, void *out) {{'
                   '\n  __m128i a=_mm_loadu_si128(ap), b=_mm_loadu_si128(bp);'
                   f'\n  _mm_storeu_si128(out, _mm_{op}_si128({args}));\n}}')
    return '\n'.join(out)+'\n'


def oracle_inputs():
    rng=random.Random(0xA35)
    pairs=[(bytes(16),bytes(16)),(bytes(range(16)),bytes(range(16,32))),
           (bytes([255])*16,bytes([0x55])*16),(bytes([0x80])*16,bytes([1])*16)]
    pairs.extend((rng.randbytes(16),rng.randbytes(16)) for _ in range(60))
    return pairs


def execute(lib, a, b):
    result={}
    for op, imm in CASES:
        fn=getattr(lib,name(op,imm));fn.argtypes=[ctypes.c_void_p]*3;fn.restype=None
        left=ctypes.create_string_buffer(a,16);right=ctypes.create_string_buffer(b,16);out=ctypes.create_string_buffer(16)
        fn(left,right,out)
        result[name(op,imm)]=out.raw.hex()
    return result


def compile_library(root, arm):
    clang=shutil.which('clang')
    if not clang: raise RuntimeError('clang missing')
    source=root/('aes.ll' if arm else 'aes.c');source.write_text(arm_ir() if arm else x86_source())
    binary=root/('aes.dylib' if sys.platform=='darwin' else 'aes.so')
    flags=['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']
    subprocess.run([clang,*flags,'-O2',*([] if arm else ['-maes']),str(source),'-o',str(binary)],check=True)
    return ctypes.CDLL(str(binary))


def x86_aes_available():
    if sys.platform=='linux': return ' aes ' in (' '+Path('/proc/cpuinfo').read_text().replace('\n',' ')+' ')
    if sys.platform=='darwin':
        return 'AES' in subprocess.check_output(['sysctl','-n','machdep.cpu.features'],text=True)
    return False


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-x86',action='store_true')
    parser.add_argument('--require-arm64',action='store_true')
    a=parser.parse_args(argv)
    machine=platform.machine().lower()
    arm=machine in ('arm64','aarch64')
    if a.require_arm64 and not arm: raise RuntimeError('ARM64 required')
    if a.record_x86 and arm: raise RuntimeError('oracle recording requires real x86 AES-NI')
    if not arm and (machine not in ('x86_64','amd64') or not x86_aes_available()): raise RuntimeError('native AES-NI unavailable')
    with tempfile.TemporaryDirectory() as tmp:
        lib=compile_library(Path(tmp),arm)
        if a.record_x86:
            rows=[{'a':x.hex(),'b':y.hex(),'expected':execute(lib,x,y)} for x,y in oracle_inputs()]
            VECTORS.parent.mkdir(exist_ok=True)
            VECTORS.write_text(json.dumps({'oracle':'Native x86 AES-NI via Clang intrinsics; deterministic seed 0xA35','rows':rows},indent=2)+'\n')
        data=json.loads(VECTORS.read_text())
        for i,row in enumerate(data['rows']):
            got=execute(lib,bytes.fromhex(row['a']),bytes.fromhex(row['b']))
            if got!=row['expected']:
                raise AssertionError(f'vector {i}: {[(k,got[k],v) for k,v in row["expected"].items() if got[k]!=v]}')
        print(f'PASS {machine}: {len(data["rows"])*len(CASES)} comparisons to native x86 oracle'+(' (ARM emitter)' if arm else ' (oracle replay, not ARM execution)'))
    return 0

if __name__=='__main__': raise SystemExit(main())
