#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 || ! -x "$1/configure" || -e "$2" || -L "$2" ]]; then
    printf 'Usage: %s patched-wine-source new-build-directory\n' "$0" >&2
    exit 2
fi

source_dir=$(cd "$1" && pwd -P)
mkdir "$2"
cd "$2"

# Build the x86-64 modules for the CrossOver 26.3 macOS runtime.
arch -x86_64 /bin/bash "$source_dir/configure" --enable-win64 --without-x \
    --without-freetype --disable-tests CC='clang -arch x86_64' CXX='clang++ -arch x86_64' \
    CFLAGS='-g -O2 -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0'

# This CrossOver source uses a runtime-loaded Vulkan library even when configure
# finds no development headers or libraries.
if ! grep -q '^#define SONAME_LIBVULKAN ' include/config.h; then
    printf '\n#define SONAME_LIBVULKAN "libMoltenVK.dylib"\n' >> include/config.h
fi

arch -x86_64 make -j "${BUILD_JOBS:-4}" 'APPKIT_LIBS=-framework AppKit -framework CoreFoundation' \
    dlls/win32u/win32u.so dlls/winemac.drv/winemac.so dlls/wbemprox/x86_64-windows/wbemprox.dll
