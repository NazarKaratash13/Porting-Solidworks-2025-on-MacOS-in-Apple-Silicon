#!/bin/bash
# Standalone, Wine-free setup and first verification on native Apple Silicon.
# No root access, no Wine downloads, no modification of the system Python.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
cd "$root"

usage() {
    cat <<'EOF'
Usage: bash tools/bootstrap_macos.sh [--check | --setup-only | --full-tests]
  (default)     prepare venv, install pinned dependencies, run Plink -V smoke test
  --check       inspect prerequisites without installation or code execution
  --setup-only  install Python dependencies, then preflight; skip smoke test
  --full-tests  set up and run the full regression suite (may take time)
Wine is deliberately NOT installed; hosted GUI setup is a separate opt-in step.
EOF
}
mode="smoke"
case "${1:-}" in
    '') ;;
    --check) mode="check" ;;
    --setup-only) mode="setup" ;;
    --full-tests) mode="full" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then usage >&2; exit 2; fi

# Check platform before downloading or installing anything.
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo 'Requires native Apple Silicon macOS (arm64), not Rosetta or Linux.' >&2
    exit 1
fi
if [[ "$mode" == check ]]; then
    if [[ -x work/venv/bin/python3 ]]; then
        exec work/venv/bin/python3 tools/doctor.py --mode base --strict
    fi
    exec python3 tools/doctor.py --mode base --strict
fi

if ! command -v xcrun >/dev/null 2>&1 || ! xcrun --find clang >/dev/null 2>&1; then
    echo 'Xcode Command Line Tools missing. Run: xcode-select --install' >&2
    exit 1
fi
python3 - <<'PY'
import platform,sys
if sys.version_info < (3, 10) or platform.machine() != 'arm64':
    raise SystemExit('Need Python >=3.10 running natively as arm64 (not under Rosetta)')
PY
mkdir -p work
if [[ ! -x work/venv/bin/python3 ]]; then python3 -m venv work/venv; fi
PYTHON="$root/work/venv/bin/python3"
"$PYTHON" -m pip install -r recompiler/requirements.txt
"$PYTHON" tools/doctor.py --mode base --strict
if [[ "$mode" == setup ]]; then
    echo 'Environment prepared; smoke test skipped.'
    exit 0
fi
if [[ "$mode" == full ]]; then
    echo 'Running repository regression suite...'
    PYTHON="$PYTHON" bash recompiler/run.sh
else
    echo 'Running Wine-free Plink -V native recompiler smoke test...'
    PYTHON="$PYTHON" bash recompiler/test_plink_startup.sh "$root/work/corpus/plink.exe"
fi
echo 'PASS: selected native ARM64 verification completed.'
