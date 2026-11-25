#!/bin/bash
set -euo pipefail

fixture="$(cd "$(dirname "$0")" && pwd)"
tool="$(cd "$fixture/../.." && pwd)"
python="${PYTHON:-python3}"
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT

"$fixture/build.sh" "$build"
for name in fixture fixture-main-thread; do
    "$python" "$tool/build_console_modules.py" "$build/$name.exe" \
        "$build/$name-arm64" "$build/fixture_plugin.dll" "$build/fixture_dependency.dll"
done
cd "$build"

run_case() {
    local binary="$1" name="$2" expected="$3" result=0
    "./$binary-arm64" || result=$?
    if [[ "$result" != "$expected" ]]; then
        echo "FAIL $name (expected $expected, got $result)" >&2
        exit 1
    fi
    echo "PASS $name"
}

printf 'not a PE file' > unrelated.dll
for name in fixture fixture-main-thread; do
    "$python" "$tool/run_exe.py" "$build/$name.exe" 2> launch.stderr
    if [[ -s launch.stderr ]]; then
        cat launch.stderr >&2
        exit 1
    fi
    echo "PASS on-demand DLL translation for $name"
done
rm unrelated.dll

run_case fixture-main-thread "main-thread DLL export, TLS, callback, and unload" 0
run_case fixture "worker-thread DLL export, isolated TLS, callback, and unload" 0

# A diagnostic artifact with a trap in an unused export must never satisfy a
# strict build, even when the DLL's machine code is already cached.
strict="$build/strict"
mkdir -p "$strict"
clang -target x86_64-w64-windows-gnu -O2 -ffreestanding -DFIXTURE_UNSUPPORTED_EXPORT \
    -c "$fixture/dependency.c" -o "$strict/dependency.obj"
"$python" -m ziglang cc -target x86_64-windows-gnu -nostdlib -shared \
    "$strict/dependency.obj" -Wl,--entry,DllMain -o "$strict/fixture_dependency.dll"
port="$tool/../tools/port.py"
inputs=("$build/fixture-main-thread.exe" --dll "$strict/fixture_dependency.dll")
(
    export ARM64_RECOMPILER_MODULE_STORE="$strict/module-store"
    "$python" "$port" "${inputs[@]}" -o "$strict/diagnostic" --allow-traps
    for mode in cached static; do
        command=("$python" "$port" "${inputs[@]}" -o "$strict/$mode")
        if [[ "$mode" == static ]]; then command+=(--no-cache); fi
        if "${command[@]}" >"$strict/$mode.log" 2>&1; then
            echo "FAIL strict $mode build accepted an unsupported DLL export" >&2
            exit 1
        fi
        grep -E 'fixture_dependency\.dll:.*pabsb.*unsupported' "$strict/$mode.log"
    done
)
echo "PASS strict static and cached builds reject unsupported DLL instructions"

mv fixture_plugin.dll original.dll
run_case fixture-main-thread "missing DLL" 10
result=0
"$python" "$tool/run_exe.py" "$build/fixture-main-thread.exe" || result=$?
[[ "$result" == 10 ]]
echo "PASS missing DLL with on-demand translation"
cp original.dll fixture_plugin.dll
printf 'changed' >> fixture_plugin.dll
run_case fixture "changed DLL" 10

mv fixture_dependency.dll original-dependency.dll
mv original.dll fixture_plugin.dll
result=0
"$python" "$tool/run_exe.py" "$build/fixture-main-thread.exe" || result=$?
[[ "$result" == 10 ]]
echo "PASS missing transitive dependency"
