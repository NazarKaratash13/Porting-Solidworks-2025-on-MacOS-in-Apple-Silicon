#!/bin/bash
# Stage the ARM64/ARM64X graphics bridge in a new MetalSharp Wine lab runtime.
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 WINEMETALGL_SOURCE ARM64_CORE_DYLIB METALSHARP_WINE NEW_LAB_RUNTIME" >&2
    exit 2
fi

source_dir=$(cd "$1" && pwd -P)
core=$(realpath "$2")
upstream=$(cd "$3" && pwd -P)
destination="$(cd "$(dirname "$4")" && pwd -P)/$(basename "$4")"
case "$destination" in
    /Applications/*|"$HOME"/Applications/*)
        echo "Use a laboratory directory outside Applications." >&2
        exit 2
        ;;
esac
if [[ -e "$destination" || -L "$destination" ]]; then
    echo "The laboratory runtime path must be new." >&2
    exit 2
fi

builder=build-wine-module-arm64.sh
test -f "$source_dir/scripts/$builder"
test -x "$upstream/bin/wine-launcher"
test -f "$upstream/lib/wine-opengl/aarch64-windows/opengl32.dll"
xcrun lipo -verify_arch arm64 "$core"
command -v arm64ec-w64-mingw32-clang >/dev/null
command -v i686-w64-mingw32-clang >/dev/null

scratch=$(mktemp -d "${TMPDIR:-/tmp}/swv3-arm64x.XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
# The upstream builder's compiler argument lists require paths without spaces.
ln -s "$source_dir" "$scratch/source"
ln -s "$upstream" "$scratch/runtime"
sh "$scratch/source/scripts/$builder" "$scratch/runtime" "$scratch/bridge"

# MetalSharp's builtin loader checks the DOS stub tag before mapping the PE.
forwarder=aarch64-windows/opengl32.dll
python3 - "$scratch/bridge/$forwarder" <<'PY'
import struct
import sys

with open(sys.argv[1], "r+b") as stream:
    header = stream.read(64)
    if header[:2] != b"MZ" or struct.unpack_from("<I", header, 60)[0] < 96:
        raise SystemExit("The forwarder has no room for the Wine builtin signature.")
    stream.write(b"Wine builtin DLL".ljust(32, b"\0"))
PY

mkdir "$destination"
/bin/cp -cR "$upstream/." "$destination/"
wine="$destination/lib/wine"
for file in "$forwarder" aarch64-windows/winemetalgl.dll aarch64-unix/winemetalgl.so; do
    cp "$scratch/bridge/$file" "$wine/$file"
done
cp "$core" "$wine/aarch64-unix/libwinemetalgl.dylib"
for file in aarch64-unix/winemetalgl.so aarch64-unix/libwinemetalgl.dylib; do
    codesign --force --sign - "$wine/$file"
    codesign --verify --strict "$wine/$file"
done
echo "$destination"
