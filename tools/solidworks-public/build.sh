#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 || "$1" != *.app || -e "$1" || -L "$1" ]]; then
    printf 'Usage: %s path/to/new.app\n' "$0" >&2
    exit 2
fi
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
parent=$(cd "$(dirname "$1")" && pwd -P)
output="$parent/$(basename "$1")"
stage=$(mktemp -d "$parent/.sw-v3-launcher.XXXXXXXX")
trap 'rm -r -- "$stage"' EXIT
app="$stage/SOLIDWORKS V3 Launcher.app"
resources="$app/Contents/Resources"
template="$resources/DesktopTemplate/Contents"
mkdir -p "$app/Contents/MacOS" "$template/MacOS" "$template/Resources" "$template/PlugIns"
xcrun --sdk macosx swiftc -O -target arm64-apple-macos14.0 \
    "$source_dir/Launcher.swift" "$source_dir/DesktopPackage.swift" -o "$app/Contents/MacOS/Launcher"
cp "$source_dir/Info.plist" "$app/Contents/Info.plist"
bash "$source_dir/../solidworks-macos/build-icon.sh" "$resources/SOLIDWORKS.icns"
cp "$resources/SOLIDWORKS.icns" "$template/Resources/SOLIDWORKS.icns"
sed 's/local\.solidworks2025\.v3resize/org.swv3.desktop/g' \
    "$source_dir/../solidworks-macos/Info.plist" > "$template/Info.plist"
plutil -replace CFBundleShortVersionString -string 0.3.0 "$template/Info.plist"
plutil -replace CFBundleVersion -string 7 "$template/Info.plist"
install -m 755 "$source_dir/../solidworks-v3-local-launcher.sh" "$template/MacOS/SOLIDWORKS"
bash "$source_dir/../solidworks-quicklook/build.sh" "$stage/quicklook" org.swv3.desktop
mv "$stage/quicklook/"*.appex "$template/PlugIns/"
x86_64-w64-mingw32-gcc -municode -O2 "$source_dir/../solidworks-v3-file-bridge.c" \
    -o "$resources/file-bridge.exe" -lole32 -loleaut32 -luuid
plutil -lint "$app/Contents/Info.plist"
plutil -lint "$template/Info.plist"
codesign --sign - "$app"
codesign --verify --strict "$app"
mv -n "$app" "$output"
if [[ -e "$app" ]]; then
    printf 'Output appeared during the build: %s\n' "$output" >&2
    exit 1
fi
printf '%s\n' "$output"
