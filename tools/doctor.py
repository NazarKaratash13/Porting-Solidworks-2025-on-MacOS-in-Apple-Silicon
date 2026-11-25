#!/usr/bin/env python3
"""Offline prerequisite and bundled-corpus preflight for arm64-recompiler.

Does not install software, download files, or execute any Windows PE binaries.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
WINE_SUFFIX = Path('Wine Stable.app/Contents/Resources/wine')
PACKAGES = {'capstone': '5.0.9', 'pefile': '2024.8.26',
            'unicorn': '2.1.4', 'ziglang': '0.15.2'}


def wine_root() -> Path:
    if os.environ.get('WINE_ROOT'):
        return Path(os.environ['WINE_ROOT']).expanduser()
    preferred = ROOT / 'recompiler/wine-runtime' / WINE_SUFFIX
    legacy = ROOT / 'work/wine' / WINE_SUFFIX
    return preferred if preferred.is_dir() or not legacy.is_dir() else legacy


def inspect_pe(path: Path) -> tuple[bool, str]:
    """Validate the PE header and AMD64 machine type, without loading code."""
    if not path.is_file():
        return False, 'missing'
    try:
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                return False, 'no DOS MZ signature'
            stream.seek(0x3c)
            header = stream.read(4)
            if len(header) != 4:
                return False, 'truncated DOS header'
            offset, = struct.unpack('<I', header)
            if offset < 0x40 or offset > 1024 * 1024:
                return False, 'invalid PE offset'
            stream.seek(offset)
            signature = stream.read(4)
            if signature != b'PE\x00\x00':
                return False, 'no PE signature'
            machine_bytes = stream.read(2)
            if len(machine_bytes) != 2:
                return False, 'truncated machine field'
            machine, = struct.unpack('<H', machine_bytes)
            if machine != 0x8664:
                return False, f'not x86-64 (machine=0x{machine:04x})'
        return True, f'x86-64 PE, {path.stat().st_size:,} bytes'
    except OSError as error:
        return False, str(error)


def tool_path(name: str) -> str | None:
    return shutil.which(name)


def probe(args: list[str], timeout: float = 8) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout, check=False)
        detail = (result.stdout or result.stderr).strip().splitlines()
        return result.returncode == 0, (detail[0] if detail else f'exit {result.returncode}')
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)


def llvm_bin() -> Path | None:
    paths = []
    if os.environ.get('LLVM_BIN'):
        paths.append(Path(os.environ['LLVM_BIN']).expanduser())
    paths.extend([Path('/opt/homebrew/opt/llvm@22/bin'),
                  Path('/usr/local/opt/llvm@22/bin')])
    for path in paths:
        if all((path / name).is_file() for name in ('clang', 'llvm-link', 'llvm-split')):
            return path
    return None


def report(mode: str) -> dict:
    checks = []

    def check(name: str, ok: bool, description: str, *, required: bool = True) -> None:
        checks.append({'name': name, 'ok': bool(ok), 'required': required,
                       'detail': str(description)})

    native = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    check('macOS Apple Silicon (native)', native,
          f'{platform.system()} / {platform.machine()}')
    version_ok = sys.version_info >= (3, 10)
    check('Python >= 3.10', version_ok,
          f'{platform.python_version()} ({sys.executable})')
    for pkg, wanted in PACKAGES.items():
        try:
            version = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            version = None
        check(f'Python {pkg}=={wanted}', version == wanted,
              f'installed {version}' if version else 'not installed')
    check('clang', bool(tool_path('clang')), tool_path('clang') or 'missing')
    check('xcrun', bool(tool_path('xcrun')), tool_path('xcrun') or 'missing')
    for name in ('plink.exe', 'jq.exe', 'rg.exe'):
        path = ROOT / 'work/corpus' / name
        ok, detail = inspect_pe(path)
        check(f'corpus/{name}', ok, detail)

    if mode in ('hosted', 'jq'):
        llvm = llvm_bin()
        check('LLVM 22 (clang / llvm-link / llvm-split)', llvm is not None,
              str(llvm) if llvm else 'install llvm@22, or set LLVM_BIN')

    if mode == 'hosted':
        wine = wine_root()
        check('Wine 11.0 x86-64 files',
              (wine / 'bin/wine').is_file() and
              (wine / 'bin/wineserver').is_file() and
              (wine / 'lib/wine/x86_64-windows').is_dir(),
              str(wine) + ' (run python3 recompiler/setup_wine.py)')
        if native:
            ros_ok, ros_detail = probe(['arch', '-x86_64', '/usr/bin/true'])
        else:
            ros_ok, ros_detail = False, 'requires Apple Silicon macOS'
        check('Rosetta 2 for wineserver', ros_ok, ros_detail)
        bison = next((str(path) for path in (
            Path('/opt/homebrew/opt/bison/bin/bison'),
            Path('/usr/local/opt/bison/bin/bison'),
        ) if path.is_file()), tool_path('bison'))
        if bison:
            bison_ok, detail = probe([bison, '--version'])
            try:
                major = int(detail.split()[-1].split('.')[0]); bison_ok &= major >= 3
            except (ValueError, IndexError):
                bison_ok = False
        else:
            bison_ok, detail = False, 'missing'
        check('bison >= 3', bison_ok, f'{bison or "missing"}: {detail}')
        freetype = (Path('/opt/homebrew/include/freetype2/ft2build.h').is_file() or
                    Path('/usr/local/include/freetype2/ft2build.h').is_file())
        check('FreeType development headers', freetype,
              'present in Homebrew' if freetype else 'install Homebrew freetype')
        host = ROOT / 'work/wine-host/host/lib/wine/x86_64-unix'
        check('Wine arm64 host layer (built)',
              (host / 'hostthunks.dylib').is_file() and (host / 'ntdll.so').is_file(),
              str(host) + ' (run recompiler/wine-host/build.sh)', required=False)

    required = [c for c in checks if c['required']]
    return {'mode': mode, 'ready': all(c['ok'] for c in required),
            'checks': checks, 'project_root': str(ROOT),
            'note': 'Preflight only; a passing result does not guarantee lifted binaries will work.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('base', 'jq', 'hosted'), default='base')
    parser.add_argument('--json', action='store_true', help='machine-readable report')
    parser.add_argument('--strict', action='store_true', help='exit nonzero if prerequisites are missing')
    args = parser.parse_args()
    result = report(args.mode)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"arm64-recompiler preflight: {args.mode} / " +
              ('READY' if result['ready'] else 'NOT READY'))
        for item in result['checks']:
            state = 'OK' if item['ok'] else ('MISSING' if item['required'] else 'OPTIONAL')
            print(f"[{state:8}] {item['name']}: {item['detail']}")
        print(result['note'])
    return 0 if (result['ready'] or not args.strict) else 1


if __name__ == '__main__':
    raise SystemExit(main())
