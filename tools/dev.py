#!/usr/bin/env python3
"""Repeatable development gates for arm64-recompiler.

The portable checks intentionally require no pip packages, internet, Wine or macOS.
Native gates are opt-in and fail closed outside Apple Silicon macOS.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {'.git', '.venv', 'venv', '__pycache__', '.cache', 'build'}
CORPUS = ('jq.exe', 'plink.exe', 'rg.exe')


def sources(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    """Enumerate tracked-style source paths; ignore generated code and caches."""
    paths = []
    excluded = SKIP_PARTS | {'work'}
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in excluded]
        base = Path(directory)
        paths.extend(
            path for name in files
            if (path := base / name).suffix.lower() in extensions and path.is_file()
        )
    return sorted(paths)


def source_digest(root: Path) -> tuple[str, int]:
    """Path- and content-sensitive deterministic digest, independent of timestamps."""
    paths = sources(root, (
        '.py', '.sh', '.c', '.h', '.m', '.swift', '.s', '.def', '.patch',
        '.json', '.yml', '.yaml',
    ))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(paths)


def scan_sources(root: Path) -> dict:
    """Fast, cross-platform syntax gate, without importing application modules."""
    failures: list[str] = []
    python_files = sources(root, ('.py',))
    shell_files = sources(root, ('.sh',))
    for path in python_files:
        try:
            # Parse rather than import or compile to bytecode: zero side effects.
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (SyntaxError, UnicodeError, OSError) as error:
            failures.append(f'{path.relative_to(root)}: {error}')
    if not shutil.which('bash'):
        failures.append('bash unavailable: shell syntax not checked')
    else:
        for path in shell_files:
            result = subprocess.run(['bash', '-n', str(path)], text=True,
                                    capture_output=True, check=False)
            if result.returncode:
                failures.append(f'{path.relative_to(root)}: {result.stderr.strip()}')
    return {'ok': not failures, 'python_files': len(python_files),
            'shell_files': len(shell_files), 'errors': failures}


def run_command(command: list[str], *, cwd: Path = ROOT, env: dict | None = None) -> dict:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, check=False)
        return {'ok': result.returncode == 0, 'exit_code': result.returncode,
                'command': command}
    except OSError as error:
        return {'ok': False, 'exit_code': None, 'command': command, 'error': str(error)}


def run_units() -> dict:
    return run_command([sys.executable, '-B', '-m', 'unittest', 'discover',
                        '-s', 'tools', '-p', 'test_*.py', '-v'])


def git_info(root: Path) -> dict:
    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                    text=True, timeout=5, check=False)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    revision = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain') if revision else None
    return {'revision': revision, 'dirty': bool(status) if status is not None else None}


def tool_versions() -> dict:
    versions = {}
    for name, arg in [('clang', '--version'), ('xcrun', '--version'),
                      ('git', '--version'), ('bash', '--version')]:
        binary = shutil.which(name)
        if not binary:
            versions[name] = {'found': False}
            continue
        try:
            result = subprocess.run([binary, arg], capture_output=True, text=True,
                                    timeout=5, check=False)
            line = (result.stdout or result.stderr).splitlines()
            versions[name] = {'found': True, 'version': line[0] if line else None}
        except (OSError, subprocess.TimeoutExpired) as error:
            versions[name] = {'found': True, 'error': str(error)}
    return versions


def version_map() -> dict:
    versions = {}
    for name in ('capstone', 'pefile', 'unicorn', 'ziglang'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def manifest(root: Path = ROOT) -> dict:
    """Record *observed* environment and immutable corpus hashes (no PE execution)."""
    from doctor import inspect_pe
    digest, file_count = source_digest(root)
    corpus = {}
    for name in CORPUS:
        path = root / 'work/corpus' / name
        valid, detail = inspect_pe(path)
        corpus[name] = {'valid_x86_64_pe': valid, 'detail': detail,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()
                        if path.is_file() else None}
    return {
        'format': 1,
        'captured_utc': datetime.now(timezone.utc).isoformat(),
        'system': platform.system(), 'machine': platform.machine(),
        'python': platform.python_version(), 'executable': sys.executable,
        'git': git_info(root),
        'source': {'sha256': digest, 'files': file_count},
        'corpus': corpus, 'packages': version_map(), 'tools': tool_versions(),
        'note': 'Records environment and static inputs; not evidence that lifted executables ran.',
    }


def native_platform() -> bool:
    return platform.system() == 'Darwin' and platform.machine() == 'arm64'


def python_for_native() -> str:
    override = os.environ.get('PYTHON')
    if override:
        return override
    venv = ROOT / 'work/venv/bin/python3'
    return str(venv) if venv.is_file() else sys.executable


def native_gate(full: bool = False) -> int:
    if not native_platform():
        print('ERROR: native gate needs macOS ARM64 (Apple Silicon).', file=sys.stderr)
        return 2
    python = python_for_native()
    preflight = [python, str(ROOT / 'tools/doctor.py'), '--mode', 'base', '--strict']
    print('>>', ' '.join(preflight), flush=True)
    if not run_command(preflight)['ok']:
        return 1
    test = (["bash", str(ROOT / 'recompiler/run.sh')]
            if full else ["bash", str(ROOT / 'recompiler/test_plink_startup.sh'),
                          str(ROOT / 'work/corpus/plink.exe')])
    print('>>', ' '.join(test), flush=True)
    outcome = run_command(test, env={**os.environ, 'PYTHON': python})
    return 0 if outcome['ok'] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='portable syntax + unit gate, no dependencies/network')
    commands.add_parser('unit', help='run portable unit tests')
    commands.add_parser('smoke', help='macOS ARM64 no-Wine Plink smoke test (strict preflight)')
    commands.add_parser('native-full', help='full native regression suite on Apple Silicon')
    p = commands.add_parser('snapshot', help='write observed environment and input hashes to JSON')
    p.add_argument('--output', type=Path, default=ROOT / 'work/reports/dev-baseline.json')
    args = parser.parse_args(argv)
    if args.command == 'check':
        scan = scan_sources(ROOT)
        print(f"Portable syntax: {scan['python_files']} Python, {scan['shell_files']} shell files", flush=True)
        for error in scan['errors']:
            print('ERROR:', error, file=sys.stderr)
        if not scan['ok']:
            return 1
        print('Portable unit tests:', flush=True)
        return 0 if run_units()['ok'] else 1
    if args.command == 'unit':
        return 0 if run_units()['ok'] else 1
    if args.command in ('smoke', 'native-full'):
        return native_gate(full=(args.command == 'native-full'))
    if args.command == 'snapshot':
        report = manifest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                               encoding='utf-8')
        print(f'Saved environment snapshot: {args.output}')
        return 0
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
