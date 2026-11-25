"""Portable independent arithmetic model of ARM AES round sequence.
Used to cross-check hardware x86 oracle when ARM hardware is unavailable.
Not a substitute for executing actual generated ARM64 machine code.
"""
from functools import lru_cache
from aes_ir import KEYGEN_SHUFFLE


def gf(a,b):
    result=0
    for _ in range(8):
        if b & 1: result ^= a
        a=((a<<1) ^ (0x11b if a & 128 else 0)) & 255
        b >>= 1
    return result


@lru_cache(maxsize=256)
def sb(x):
    inv=1
    if x:
        for _ in range(254): inv=gf(inv,x)
    else: inv=0
    return inv ^ ((inv<<1)|(inv>>7))&255 ^ ((inv<<2)|(inv>>6))&255 ^ ((inv<<3)|(inv>>5))&255 ^ ((inv<<4)|(inv>>4))&255 ^ 0x63


@lru_cache(maxsize=1)
def inverse_table(): return {sb(i):i for i in range(256)}


def arm_subshift(v,inv=False):
    box=inverse_table().__getitem__ if inv else sb
    sign=-1 if inv else 1
    return bytes(box(v[4*((col+sign*row)%4)+row]) for col in range(4) for row in range(4))


def mix(v,inv=False):
    weights=(14,11,13,9) if inv else (2,3,1,1)
    return bytes(gf(weights[(-row)%4],v[col*4]) ^ gf(weights[(1-row)%4],v[col*4+1]) ^
                 gf(weights[(2-row)%4],v[col*4+2]) ^ gf(weights[(3-row)%4],v[col*4+3])
                 for col in range(4) for row in range(4))


def round_model(op,a,b,imm=None):
    if op=='aesimc':return mix(b,True)
    if op=='aeskeygenassist':
        sub=arm_subshift(b)
        return bytes(sub[j]^(imm if i in (4,12) else 0) for i,j in enumerate(KEYGEN_SHUFFLE))
    inv=op.startswith('aesd')
    v=arm_subshift(a,inv)
    if not op.endswith('last'):v=mix(v,inv)
    return bytes(x^y for x,y in zip(v,b))
