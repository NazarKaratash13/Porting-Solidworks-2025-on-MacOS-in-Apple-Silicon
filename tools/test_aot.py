"""No-macOS tests for the memory-aware AOT scheduling/partition cache.

The fake llvm-split and fake clang below exercise orchestration only; they DO
NOT establish that Mach-O compilation or Windows application execution works.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recompiler"))
sys.path.insert(0, str(ROOT / "tools"))
import aot_build
import port


class AotTests(unittest.TestCase):
    def test_memory_cap_on_16gb_m4(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(aot_build, 'available_memory_bytes', return_value=16 * (1 << 30)), \
             mock.patch.object(aot_build.os, 'cpu_count', return_value=8):
            self.assertEqual(aot_build.max_compilers(), 2)
        with mock.patch.dict(os.environ, {"ARM64_RECOMPILER_MAX_COMPILES": "1"}):
            self.assertEqual(aot_build.max_compilers(), 1)
        with mock.patch.dict(os.environ, {"ARM64_RECOMPILER_MAX_COMPILES": "0"}):
            with self.assertRaises(ValueError):
                aot_build.max_compilers()

    def test_memory_cap_on_8gb_m4(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(aot_build, 'available_memory_bytes', return_value=8 * (1 << 30)):
            self.assertEqual(aot_build.max_compilers(), 1)

    def test_digest_is_streamed_and_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = b'abc' * 450_000
            path = Path(tmp) / 'large.ll'
            path.write_bytes(data)
            self.assertEqual(aot_build.digest_file(path), hashlib.sha256(data).hexdigest())

    def test_parts_and_lto_backend_limit(self):
        with mock.patch.dict(os.environ, {"ARM64_RECOMPILER_PARTS": "5"}):
            self.assertEqual(aot_build.part_count(), 5)
        with mock.patch.dict(os.environ, {"ARM64_RECOMPILER_PARTS": "1"}):
            with self.assertRaises(ValueError):
                aot_build.part_count()
        with tempfile.TemporaryDirectory() as tmp:
            args = aot_build.thinlto_link_flags(2, Path(tmp) / 'lto')
            self.assertEqual(args[1], '-Wl,-mllvm,-threads=2')
            self.assertTrue((Path(tmp) / 'lto').is_dir())

    def test_global_compiler_semaphore_across_pools(self):
        state = {"active": 0, "peak": 0}
        lock = threading.Lock()

        def fake_command(command, check):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.01)
            with lock:
                state["active"] -= 1

        with mock.patch.object(aot_build, "COMPILE_SLOTS", threading.BoundedSemaphore(2)), \
             mock.patch.object(aot_build, "PRESSURE_GATE", mock.MagicMock()), \
             mock.patch.object(aot_build.subprocess, "run", side_effect=fake_command):
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(aot_build.run_compiler, [["fake-clang"]] * 16))
        self.assertEqual(state["peak"], 2)
        self.assertEqual(state["active"], 0)

    def test_fail_closed_without_matching_toolchain(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"LLVM_BIN": tmp}):
                with self.assertRaises(RuntimeError):
                    aot_build.llvm_toolchain()

    def test_partition_cache_and_command_line(self):
        # Fake programs simulate deterministic LLVM shard and ThinLTO compilation.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tools = base / 'toolchain'
            tools.mkdir()
            compiler_log = base / 'compiler.log'
            clang = tools / 'clang'
            clang.write_text('''#!/usr/bin/env python3
import hashlib, os, pathlib, sys
args = sys.argv[1:]
if "--version" in args:
 print("Test clang version 1")
 sys.exit(0)
assert args[args.index("-x")+1] == "ir", args
source = pathlib.Path(args[args.index("-c")+1])
output = pathlib.Path(args[args.index("-o")+1])
output.write_bytes(b"bitcode:" + hashlib.sha256(source.read_bytes()).digest())
with open(os.environ["COMPILER_LOG"], "a") as f: f.write(str(source) + "\\n")
''')
            splitter = tools / 'llvm-split'
            splitter.write_text('''#!/usr/bin/env python3
import pathlib, sys
args = sys.argv[1:]
count = int(args[args.index("-j")+1]); prefix = args[args.index("-o")+1]
source = pathlib.Path(args[-1]).read_bytes()
for index in range(count):
 pathlib.Path(prefix + str(index)).write_bytes(source + b"\\npartition:" + str(index).encode())
''')
            clang.chmod(0o755)
            splitter.chmod(0o755)
            source = base / 'original.ll'
            source.write_text('define i32 @main(){ ret i32 0 }')
            store = base / 'store'
            with mock.patch.dict(os.environ, {"LLVM_BIN": str(tools),
                                             "COMPILER_LOG": str(compiler_log)}):
                first, used_clang = aot_build.compile_partitioned_program(
                    source, base / 'first', store=store, jobs=2, parts=4)
                self.assertEqual(used_clang, clang)
                self.assertEqual([p.name for p in first], ['part0.o', 'part1.o', 'part2.o', 'part3.o'])
                self.assertTrue(all(p.stat().st_size > 0 for p in first))
                self.assertEqual(len(compiler_log.read_text().splitlines()), 4)
                second, _ = aot_build.compile_partitioned_program(
                    source, base / 'second', store=store, jobs=2, parts=4)
                self.assertEqual(len(compiler_log.read_text().splitlines()), 4, 'second build must hit cache')
                self.assertEqual([p.read_bytes() for p in first], [p.read_bytes() for p in second])
                source.write_text('define i32 @main(){ ret i32 1 }')
                aot_build.compile_partitioned_program(source, base / 'changed', store=store, jobs=2, parts=4)
                self.assertEqual(len(compiler_log.read_text().splitlines()), 8, 'source changes must invalidate cache')

    def test_port_cli_dry_run_on_non_mac(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / 'input.exe'
            exe.touch()
            args = [str(exe), '-o', str(Path(folder) / 'output')]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(port.main([*args, '--dry-run']), 0)
            with mock.patch.object(port.platform, 'system', return_value='Linux'), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(port.main(args), 2)


if __name__ == '__main__':
    unittest.main()
