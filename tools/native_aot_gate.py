#!/usr/bin/env python3
"""Required Apple Silicon integration: official split and streamed -> ThinLTO -> execution."""
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recompiler'))
from aot_build import compile_partitioned_program, thinlto_link_flags

# Cross-partition direct call, private data, function pointer identity and a
# callback table. Keep this in ConsoleLift's generated IR dialect.
FIXTURE = '''@payload = private constant [1 x i8] c"\\2a"
@dispatch = constant [2 x ptr] [ptr @foo, ptr @bar]
define i32 @main() {
entry:
  %x = call i32 @foo()
  %slot = getelementptr [2 x ptr], ptr @dispatch, i32 0, i32 1
  %fp = load ptr, ptr %slot
  %y = call i32 %fp()
  %eq = icmp eq ptr %fp, @bar
  %sum = add i32 %x, %y
  %correct = icmp eq i32 %sum, 84
  %ok = and i1 %eq, %correct
  %rc = select i1 %ok, i32 0, i32 1
  ret i32 %rc
}
define internal i32 @foo() {
entry:
  %b = load i8, ptr @payload
  %i = zext i8 %b to i32
  ret i32 %i
}
define internal i32 @bar() {
entry:
  %v = call i32 @foo()
  ret i32 %v
}
'''


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('This required gate needs native macOS arm64; not a skip/PASS')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ir = root / 'fixture.ll'
        ir.write_text(FIXTURE)
        for name, direct in [('partitioned', False), ('streamed', True)]:
            objects, clang = compile_partitioned_program(ir, root / name, jobs=2, parts=3, direct=direct)
            runner = root / f'{name}.run'
            subprocess.run([str(clang), '-arch', 'arm64', *thinlto_link_flags(2),
                            *map(str, objects), '-o', str(runner)], check=True)
            subprocess.run([str(runner)], check=True)
            print(f'PASS native {name}: real ThinLTO, link and execution')

if __name__ == '__main__': main()
