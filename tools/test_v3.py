"""Regression gates for v3: real cross-compiler/linker, scheduler, instrumentation."""
import sys
from pathlib import Path
import tempfile
import subprocess
import shutil
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'recompiler'), str(ROOT/'tools')]
from ir_partition import partition_generated_ir
from native_aot_gate import FIXTURE
from build_pressure import PressureGate
from measure_build import parse_processes, tree_rss
from ir_profile import event_for_line
from ir_spool import transform_ir_lines
from test_console_lifter_stream import lifter_mod, fake_lifter


class V3Tests(unittest.TestCase):
    def test_streamed_cross_link_and_execute_on_host(self):
        clang = shutil.which('clang')
        if not clang: self.skipTest('clang unavailable')
        # Test actual linkage and behavior on host; no macOS claim on Linux.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'input.ll'; source.write_text(FIXTURE)
            shards = partition_generated_ir(source, root/'shards', 3)
            self.assertEqual(len(shards), 3)
            self.assertEqual(sum('@payload = hidden constant' in p.read_text() for p in shards), 1)
            self.assertIn('@payload = external hidden constant', shards[1].read_text())
            objects = []
            for p in shards:
                obj = p.with_suffix('.o')
                subprocess.run([clang,'-O2','-flto=thin','-Wno-override-module','-x','ir','-c',str(p),'-o',str(obj)],check=True,capture_output=True)
                objects.append(obj)
            exe = root/'runner'
            if sys.platform == 'darwin': flags = []
            elif shutil.which('ld.lld'): flags = ['-fuse-ld=lld']
            else: self.skipTest('ThinLTO-capable host linker not available')
            subprocess.run([clang,*flags,'-flto=thin',*map(str,objects),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe)],check=True)

    def test_streamed_real_emitter_cross_compile(self):
        clang = shutil.which('clang')
        if not clang: self.skipTest('clang unavailable')
        # Real ConsoleLift finalization incl fast helpers, metadata, table, trap strings.
        body = ['define internal void @guest_fn_1000(ptr %cpu, i64 %return_va) {','entry:',
                '  %a = call i64 @guest_load(i64 7, i32 8)',
                '  call void @guest_store(i64 9, i64 %a, i32 8)', '  ret void','}',
                'define internal void @guest_fn_2000(ptr %cpu, i64 %return_va) {','entry:',
                '  call void @guest_fn_1000(ptr %cpu, i64 %return_va)', '  ret void','}',
                'declare i64 @guest_load(i64, i32)','declare void @guest_store(i64, i64, i32)',
                'declare void @guest_check_return(i64, i64)']
        obj = fake_lifter(body.copy()); obj.functions[0x2000]='guest_fn_2000'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); src=root/'source.ll'; src.write_text(obj.finish_module())
            for p in partition_generated_ir(src, root/'shards', 3):
                subprocess.run([clang,'-target','arm64-apple-macos11','-O2','-c',str(p),'-o',str(p.with_suffix('.o'))],check=True,capture_output=True)
                self.assertEqual(p.with_suffix('.o').read_bytes()[:4],bytes.fromhex('cffaedfe'))

    def test_lifter_finishes_directly_into_shards_without_main_ll(self):
        body = ['define internal void @guest_fn_1000(ptr %cpu, i64 %return_va) {',
                'entry:', '  ret void', '}']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            obj=fake_lifter([],fault_delivery=True)
            def simple_emit(self,*args,**kw):
                for line in body: self.line(line)
                return self.finish_module()
            with mock.patch.object(lifter_mod.ConsoleLift,'emit_console',simple_emit):
                files=obj.emit_console_to_file(0,0,b'',[],root/'main.ll',
                    partition_directory=root/'parts',partitions=2)
            self.assertFalse((root/'main.ll').exists())
            self.assertEqual(len(files),2)
            self.assertIn('define hidden void @guest_fn_1000',files[0].read_text())

    def test_unsupported_ir_fails_closed(self):
        for raw in ['target triple = "x86_64"\n', 'define void @bad(ptr %p) {\n', '@bad = alias i32, ptr @x\n']:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); src=root/'bad.ll';src.write_text(raw)
                with self.assertRaises(ValueError): partition_generated_ir(src, root/'out',2)

    def test_pressure_gate_reduces_and_recovers(self):
        gate=PressureGate(interval=.01); active=0; peak=0; lock=threading.Lock()
        def job(_):
            nonlocal active,peak
            with gate.admit():
                with lock: active+=1;peak=max(peak,active)
                time.sleep(.025)
                with lock: active-=1
        with mock.patch('build_pressure.pressure_free_percent',return_value=10):
            with ThreadPoolExecutor(max_workers=4) as p: list(p.map(job,range(4)))
        self.assertEqual(peak,1)
        time.sleep(.015);peak=0
        with mock.patch('build_pressure.pressure_free_percent',return_value=30):
            with ThreadPoolExecutor(max_workers=4) as p: list(p.map(job,range(4)))
        self.assertGreater(peak,1)

    def test_process_tree_sum(self):
        rows=parse_processes('1 0 10\n2 1 20\n3 2 30\n4 0 99\n')
        self.assertEqual(tree_rss(rows,1),(60*1024,3))
        self.assertEqual(tree_rss(rows,2),(50*1024,2))

    def test_differential_cli_detects_mismatch(self):
        from differential_cli import record,verify
        executable=Path(sys.executable)
        cases=[{'args':['-c','import sys; sys.stdout.write("A"); sys.exit(3)']}]
        data=record(executable,cases)
        self.assertTrue(verify(executable,data)['matched'])
        data['cases'][0]['expected']['exit']=0
        self.assertFalse(verify(executable,data)['matched'])

    def test_profile_runtime_counter_report(self):
        if not shutil.which('clang'):self.skipTest('clang unavailable')
        source=(ROOT/'recompiler/console_runtime.c').read_text()
        start=source.index('static _Atomic uint64_t guest_profile_counts[5];')
        end=source.index('int main(int argc, char **argv)',start)
        import json,os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=root/'profile.c';exe=root/'profile'
            c.write_text('#include <stdatomic.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n'+source[start:end]+'\nint main(void){ guest_profile_event(0); guest_profile_event(0); guest_profile_event(4); guest_profile_report(); return 0; }\n')
            subprocess.run(['clang','-std=c11',str(c),'-o',str(exe)],check=True,capture_output=True)
            report=root/'report.json'
            subprocess.run([str(exe)],env={**os.environ,'ARM64_RECOMPILER_PROFILE_OUT':str(report)},check=True)
            self.assertEqual(json.loads(report.read_text()),{'guest_load':2,'guest_store':0,'indirect_dispatch':0,'flag_read':0,'flag_write':1})

    def test_profile_counting_and_default_unchanged(self):
        lines=['define void @f() {\n','  %v = call i64 @guest_load(i64 0, i32 8)\n',
               '  store i1 true, ptr %zf\n','  ret void\n','}\n']
        self.assertEqual([event_for_line(l) for l in lines],[None,0,4,None,None])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x.ll'
            kw=dict(shared=False,fault_delivery=True,width_store=lifter_mod.WIDTH_STORE,
                    cpu_access=lifter_mod.CPU_ACCESS,guest_memory_inline='',guest_tbaa='')
            transform_ir_lines(lines,p,**kw)
            self.assertEqual(p.read_text(),''.join(lines))
            transform_ir_lines(lines,p,profile=True,**kw)
            self.assertIn('call void @guest_profile_event(i32 0)',p.read_text())
            self.assertIn('call void @guest_profile_event(i32 4)',p.read_text())

if __name__=='__main__': unittest.main()
