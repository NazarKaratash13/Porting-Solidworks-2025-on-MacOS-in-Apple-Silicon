"""Legacy AES-NI semantics lowered to Apple Silicon AES instructions.

x86 applies the round key *after* the round; AESE/AESD apply it before.
Use a zero ARM key, then MixColumns (except final round), then XOR x86 key.
Byte order is little-endian XMM/NEON lane order. No guest flags are modified.
"""
OPS = frozenset(('aesenc', 'aesenclast', 'aesdec', 'aesdeclast', 'aesimc', 'aeskeygenassist'))
V = '<16 x i8>'
INTRINSICS = tuple(f'declare {V} @llvm.aarch64.crypto.{op}({V}{", " + V if op in ("aese", "aesd") else ""})'
                   for op in ('aese', 'aesd', 'aesmc', 'aesimc'))

# ARM AESE with zero: output position i = SubBytes(source[4*((col+row)%4)+row]).
# Select Intel's words 1 and 3, rotated words in positions 1 and 3.
KEYGEN_INPUTS = (4,5,6,7,5,6,7,4,12,13,14,15,13,14,15,12)
KEYGEN_SHUFFLE = tuple(4*((i//4-i%4)%4)+i%4 for i in KEYGEN_INPUTS)


def emit_round(value, op, a, b, imm=None):
    """Emit SSA, given already loaded <16 x i8> values. Returns SSA name."""
    if op not in OPS: raise ValueError(op)
    def intrinsic(name, arg, second=None):
        return value(f'call {V} @llvm.aarch64.crypto.{name}({V} {arg}' +
                     (f', {V} {second}' if second is not None else '') + ')')
    if op == 'aesimc': return intrinsic('aesimc', b)
    if op == 'aeskeygenassist':
        if imm is None or not 0 <= imm <= 255: raise ValueError('AESKEYGENASSIST immediate must be imm8')
        sub = intrinsic('aese', b, 'zeroinitializer')
        mask = ', '.join(f'i32 {i}' for i in KEYGEN_SHUFFLE)
        result = value(f'shufflevector {V} {sub}, {V} poison, <16 x i32> <{mask}>')
        key = ', '.join(f'i8 {imm if i in (4,12) else 0}' for i in range(16))
        return value(f'xor {V} {result}, <{key}>')
    encrypt = op.startswith('aese')
    result = intrinsic('aese' if encrypt else 'aesd', a, 'zeroinitializer')
    if not op.endswith('last'):
        result = intrinsic('aesmc' if encrypt else 'aesimc', result)
    return value(f'xor {V} {result}, {b}')
