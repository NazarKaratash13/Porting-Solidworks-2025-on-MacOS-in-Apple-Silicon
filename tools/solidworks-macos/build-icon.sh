#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 || "$1" != *.icns || -e "$1" || -L "$1" ]]; then
    printf 'Usage: %s path/to/new.icns\n' "$0" >&2
    exit 2
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
stage=$(mktemp -d "${TMPDIR:-/tmp}/swv3-icon.XXXXXXXX")
trap 'rm -r -- "$stage"' EXIT
iconset="$stage/SOLIDWORKS.iconset"
mkdir "$iconset"
xcrun --sdk macosx swiftc -O "$script_dir/Icon.swift" -o "$stage/render"
"$stage/render" "$iconset/icon_512x512@2x.png"

for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$iconset/icon_512x512@2x.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    if [[ "$size" != 512 ]]; then
        scaled=$((size * 2))
        sips -z "$scaled" "$scaled" "$iconset/icon_512x512@2x.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
    fi
done
iconutil -c icns "$iconset" -o "$1"
