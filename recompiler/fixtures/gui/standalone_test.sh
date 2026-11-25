#!/bin/bash
# Standalone Win32 GUI fixture: no Wine install, no prefix, no wineserver,
# no lifted Wine DLLs. The AppKit backend runs alongside a lifted PE DLL.
set -euo pipefail
fixture="$(cd "$(dirname "$0")" && pwd)"
repository="$(cd "$fixture/../../.." && pwd)"
dependency="$fixture/../dynamic_dll"
python="${PYTHON:-python3}"
if [[ -n "${GUI_FIXTURE_BUILD:-}" ]]; then
    mkdir -p "$GUI_FIXTURE_BUILD"
    build="$(cd "$GUI_FIXTURE_BUILD" && pwd)"
else
    build="$(mktemp -d)"
    trap 'rm -rf "$build"' EXIT
fi

for dll in kernel32 user32 gdi32; do
    "$python" -m ziglang dlltool -m i386:x86-64 -d "$fixture/$dll.def" -l "$build/$dll.lib"
done
clang -target x86_64-w64-windows-gnu -O2 -ffreestanding -c "$dependency/dependency.c" -o "$build/dependency.obj"
"$python" -m ziglang cc -target x86_64-windows-gnu -nostdlib -shared "$build/dependency.obj" \
    -Wl,--entry,DllMain,--out-implib,"$build/dependency.lib" -o "$build/fixture_dependency.dll"
clang -target x86_64-w64-windows-gnu -O2 -ffreestanding -fno-builtin -DSTANDALONE_ABI_FIXTURE \
    -c "$fixture/main.c" -o "$build/main.obj"
"$python" -m ziglang cc -target x86_64-windows-gnu -nostdlib "$build/main.obj" \
    "$build/kernel32.lib" "$build/user32.lib" "$build/gdi32.lib" "$build/dependency.lib" \
    -Wl,--entry,entry -o "$build/gui.exe"

"$python" "$repository/tools/port.py" "$build/gui.exe" -o "$build/gui" \
    --standalone-gui --dll "$build/fixture_dependency.dll" --no-cache \
    --mode "${GUI_FIXTURE_AOT_MODE:-monolithic}"

result=0
(cd "$build" && "$python" -c 'import subprocess; raise SystemExit(subprocess.run(["./gui"], timeout=15).returncode)' \
    > stdout 2> stderr) || result=$?
if [[ "$result" != 0 ]]; then
    tail -30 "$build/stderr" >&2
    echo "FAIL standalone GUI fixture exited $result" >&2
    exit 1
fi
tr -d '\r' < "$build/stdout" > "$build/stdout.txt"
grep -qx 'created window' "$build/stdout.txt"
grep -qx 'standalone GUI ABI and DLL passed' "$build/stdout.txt"
grep -qE '^paints [1-9]' "$build/stdout.txt"
grep -qE '^client width [1-9][0-9]+$' "$build/stdout.txt"
grep -qE '^client height [1-9][0-9]+$' "$build/stdout.txt"
echo "PASS standalone Win32 GUI, Win64 stack arguments, MSG canary and lifted DLL"
