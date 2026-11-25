"""Check both build() branches connect program objects to final link command.

Uses fake PE/lifter/Clang; macOS integration must still be verified separately.
"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recompiler'))


class FakePE:
    OPTIONAL_HEADER = types.SimpleNamespace(ImageBase=0x140000000, SizeOfImage=0x10000)
    DIRECTORY_ENTRY_IMPORT = ()

    def __init__(self, path='source.exe'):
        self.dll = str(path).endswith('.dll')

    def is_dll(self):
        return self.dll


class FakeLift:
    def __init__(self, *args, **kwargs):
        pass

    def emit_console_to_file(self, *args, **kwargs):
        # Last positional arg is the LLVM IR destination.
        Path(args[-1]).write_text('define i32 @lifted_console() { ret i32 0 }\n')


class BuildWiringTests(unittest.TestCase):
    def test_both_modes_produce_correct_link_strategy(self):
        fake_pefile = types.ModuleType('pefile')
        fake_pefile.PE = FakePE
        fake_pefile.PEFormatError = ValueError
        fake_lift = types.ModuleType('console_lift')
        fake_lift.ConsoleLift = FakeLift
        fake_lift.read_console_image = lambda _, **kwargs: (0, 0, b'', [])
        with mock.patch.dict(sys.modules, {'pefile': fake_pefile, 'console_lift': fake_lift}):
            spec = importlib.util.spec_from_file_location(
                '_aot_builder_wiring_test', ROOT / 'recompiler/build_console_modules.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        commands = []

        def fake_clang(command):
            commands.append([str(item) for item in command])
            if '-o' in command:
                Path(command[command.index('-o') + 1]).write_bytes(b'fake MachO')

        def fake_mono(source, target, no_cache):
            target.write_bytes(b'fake mono code')

        def fake_parts(source, work, **kwargs):
            work.mkdir(parents=True, exist_ok=True)
            objects = [work / 'part0.o', work / 'part1.o']
            for path in objects:
                path.write_bytes(b'fake ThinLTO code')
            return objects, Path('/fake-homebrew-llvm/bin/clang')

        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'source.exe'
            exe.write_bytes(b'PE-fixture')
            with mock.patch.object(module, 'run_compiler', side_effect=fake_clang), \
                 mock.patch.object(module, 'compile_program', side_effect=fake_mono), \
                 mock.patch.object(module, 'compile_partitioned_program', side_effect=fake_parts), \
                 mock.patch.object(module, 'compile_parallel', return_value=[Path('/fake-runtime.o')]), \
                 mock.patch.object(module, 'llvm_toolchain', return_value=(Path('/fake-homebrew-llvm/bin/clang'), Path('/fake-homebrew-llvm/bin/llvm-split'))), \
                 mock.patch.object(module, 'thinlto_link_flags', return_value=['-flto=thin', '-Wl,-mllvm,-threads=2']):
                for mode in ('monolithic', 'partitioned', 'streamed'):
                    commands.clear()
                    target = Path(tmp) / f'{mode}.out'
                    with mock.patch.dict(os.environ, {'ARM64_RECOMPILER_NO_CACHE': '1',
                                                    'ARM64_RECOMPILER_AOT': mode}):
                        module.build(exe, target, [])
                    self.assertEqual(target.read_bytes(), b'fake MachO')
                    self.assertEqual(len(commands), 1)
                    line = commands[0]
                    self.assertEqual('-flto=thin' in line, mode != 'monolithic')
                    self.assertEqual(line[0] == '/fake-homebrew-llvm/bin/clang', mode != 'monolithic')
                    self.assertIn('/fake-runtime.o', line)
                    self.assertEqual(sum(item.endswith('part0.o') for item in line),
                                     int(mode != 'monolithic'))


    def test_static_dll_link_includes_both_code_and_image_objects(self):
        # Link orchestration gate: a lifted DLL must contribute two objects,
        # not just its IR object. No platform linker is invoked here.
        fake_pefile = types.ModuleType('pefile')
        fake_pefile.PE = FakePE
        fake_pefile.PEFormatError = ValueError
        fake_lift = types.ModuleType('console_lift')
        fake_lift.ConsoleLift = FakeLift
        fake_lift.read_console_image = lambda _, **kwargs: (0, 0, b'', [])
        with mock.patch.dict(sys.modules, {'pefile': fake_pefile, 'console_lift': fake_lift}):
            spec = importlib.util.spec_from_file_location(
                '_streaming_builder_wiring_test', ROOT / 'recompiler/build_console_modules.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        commands = []
        source_lists = []

        def fake_compiler(command):
            commands.append([str(item) for item in command])
            if '-o' in command:
                Path(command[command.index('-o') + 1]).write_bytes(b'linked')

        def fake_mono(source, destination, no_cache):
            destination.write_bytes(b'program')

        def fake_lift_module(path, image, work, registry, base, **kwargs):
            ir, assembly = work / 'test.dll.ll', work / 'test.dll.s'
            ir.write_text('declare void @noop()\n')
            assembly.write_text('.section __DATA,__guest_image,regular\n')
            registry.append('extern unsigned char test_guest_image[];')
            return ir, '{0}', assembly

        def fake_parallel(sources, work, flags):
            source_lists.append([Path(source) for source in sources])
            result = []
            for index, source in enumerate(sources):
                target = Path(work) / f'unit{index}-{Path(source).stem}.o'
                target.write_bytes(b'object')
                result.append(target)
            return result

        with tempfile.TemporaryDirectory() as tmp:
            exe, dll = Path(tmp) / 'source.exe', Path(tmp) / 'test.dll'
            exe.write_bytes(b'fake PE')
            dll.write_bytes(b'fake DLL')
            with mock.patch.object(module, 'run_compiler', side_effect=fake_compiler), \
                 mock.patch.object(module, 'compile_program', side_effect=fake_mono), \
                 mock.patch.object(module, 'compile_parallel', side_effect=fake_parallel), \
                 mock.patch.object(module, 'lift_module', side_effect=fake_lift_module), \
                 mock.patch.object(module, 'module_range', return_value=(1 << 40, (1 << 40) + 0x10000)), \
                 mock.patch.object(module, 'module_cache_key', return_value='fakecode'), \
                 mock.patch.dict(os.environ, {'ARM64_RECOMPILER_NO_CACHE': '1',
                                              'ARM64_RECOMPILER_AOT': 'monolithic'}, clear=False):
                output = Path(tmp) / 'port'
                module.build(exe, output, [dll])
                self.assertEqual(output.read_bytes(), b'linked')
                self.assertEqual(len(source_lists), 1)
                self.assertEqual([source.suffix for source in source_lists[0]],
                                 ['.c', '.s', '.ll', '.s', '.c'])
                self.assertEqual(len(commands), 1)
                # One program object + runtime + primary sections + DLL IR/image + registry.
                self.assertEqual(len([x for x in commands[0] if x.endswith('.o')]), 6)
                self.assertTrue(any('test.dll' in x and x.endswith('.o')
                                    for x in commands[0]))

    def test_dynamic_dll_includes_assembled_guest_image(self):
        fake_pefile = types.ModuleType('pefile')
        fake_pefile.PE = FakePE
        fake_pefile.PEFormatError = ValueError
        fake_lift = types.ModuleType('console_lift')
        fake_lift.ConsoleLift = FakeLift
        fake_lift.read_console_image = lambda _, **kwargs: (0, 0, b'', [])
        with mock.patch.dict(sys.modules, {'pefile': fake_pefile, 'console_lift': fake_lift}):
            spec = importlib.util.spec_from_file_location(
                '_dynamic_builder_wiring_test', ROOT / 'recompiler/build_console_modules.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        commands = []
        compiled = []
        def fake_lift_module(path, image, work, registry, base, **kwargs):
            ir, image_asm = work / 'plugin.ll', work / 'plugin.s'
            ir.write_text('declare void @noop()\n')
            image_asm.write_text('.section __DATA,__guest_image,regular\n')
            return ir, '{0}', image_asm

        def fake_compile_parallel(sources, work, flags=None):
            compiled.extend(Path(p).suffix for p in sources)
            outputs = []
            for i, _ in enumerate(sources):
                output = work / f'unit{i}.o'
                output.write_bytes(b'obj')
                outputs.append(output)
            return outputs

        def fake_compiler(command):
            commands.append([str(item) for item in command])
            if '-o' in command:
                Path(command[command.index('-o') + 1]).write_bytes(b'dylib')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dll = root / 'plugin.dll'
            dll.write_bytes(b'fake DLL')
            with mock.patch.object(module, 'lift_module', side_effect=fake_lift_module), \
                 mock.patch.object(module, 'compile_parallel', side_effect=fake_compile_parallel), \
                 mock.patch.object(module, 'run_compiler', side_effect=fake_compiler), \
                 mock.patch.object(module, 'module_cache_key', return_value='fakecode'):
                target = module.module_library(dll, FakePE(dll), 1 << 40,
                                               set(), False, root / 'store')
            self.assertEqual(target.read_bytes(), b'dylib')
            self.assertEqual(compiled, ['.c', '.ll', '.s'])
            self.assertEqual(len([x for x in commands[0] if x.endswith('.o')]), 3)


    def test_static_dll_cache_never_reuses_code_without_matching_image(self):
        fake_pefile = types.ModuleType('pefile')
        fake_pefile.PE = FakePE
        fake_pefile.PEFormatError = ValueError
        fake_lift = types.ModuleType('console_lift')
        fake_lift.ConsoleLift = FakeLift
        fake_lift.read_console_image = lambda _, **kwargs: (0, 0, b'', [])
        with mock.patch.dict(sys.modules, {'pefile': fake_pefile, 'console_lift': fake_lift}):
            spec = importlib.util.spec_from_file_location(
                '_dual_object_cache_builder_test', ROOT / 'recompiler/build_console_modules.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        key = 'unitdualobjectcachetest'
        cache = ROOT / 'recompiler' / '.cache'
        artifacts = [cache / f'module_{key}.o',
                     cache / f'module_{key}_image.o',
                     cache / f'module_{key}.json',
                     cache / f'fixture_{key}.o',
                     cache / f'fixture_{key}_sections.o']
        lifts = []
        sources_seen = []
        def fake_lift_module(path, image, work, registry, base, **kwargs):
            lifts.append(str(path))
            registry.append('extern unsigned char test_guest_image[];')
            ir, image_asm = work / 'cached.ll', work / 'cached.s'
            ir.write_text('declare void @noop()\n')
            image_asm.write_text('.section __DATA,__guest_image,regular\n')
            return ir, '{0}', image_asm
        def fake_parallel(sources, work, flags):
            sources_seen.append([Path(p).suffix for p in sources])
            outputs = []
            for i, source in enumerate(sources):
                if Path(source).suffix == '.o':
                    outputs.append(Path(source))
                    continue
                output = work / f'unit{i}.o'
                output.write_bytes(f'obj{i}'.encode())
                outputs.append(output)
            return outputs
        def fake_mono(source, destination, no_cache):
            destination.write_bytes(b'main code')
        def fake_compiler(command):
            if '-o' in command:
                Path(command[command.index('-o') + 1]).write_bytes(b'linked')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                exe, dll = Path(tmp) / 'fixture.exe', Path(tmp) / 'cached.dll'
                exe.write_bytes(b'fake PE')
                dll.write_bytes(b'fake DLL')
                env = {'ARM64_RECOMPILER_NO_CACHE': '', 'ARM64_RECOMPILER_AOT': 'monolithic',
                       'ARM64_RECOMPILER_STATIC_MODULES': '1'}
                with mock.patch.object(module, 'lift_module', side_effect=fake_lift_module), \
                     mock.patch.object(module, 'compile_parallel', side_effect=fake_parallel), \
                     mock.patch.object(module, 'compile_program', side_effect=fake_mono), \
                     mock.patch.object(module, 'run_compiler', side_effect=fake_compiler), \
                     mock.patch.object(module, 'module_range', return_value=(1 << 40, (1 << 40) + 0x10000)), \
                     mock.patch.object(module, 'module_cache_key', return_value=key), \
                     mock.patch.object(module, 'cache_key', return_value=key), \
                     mock.patch.dict(os.environ, env):
                    module.build(exe, Path(tmp) / 'first.app', [dll])
                    self.assertTrue(all(p.is_file() for p in artifacts))
                    module.build(exe, Path(tmp) / 'second.app', [dll])
                    self.assertEqual(len(lifts), 1, 'second build should reuse both cached objects')
                    self.assertIn('.ll', sources_seen[0]); self.assertIn('.s', sources_seen[0])
                    self.assertEqual(sources_seen[-1].count('.o'), 2,
                                     'second build should link DLL code and image objects')
        finally:
            for file in artifacts:
                file.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
