#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 || ! -d "$1" || "$1" != *.app || ! -d "$2" ]]; then
    printf 'Usage: %s path/to/launcher.app existing-output-directory\n' "$0" >&2
    exit 2
fi

app=$(cd "$1" && pwd -P)
output=$(cd "$2" && pwd -P)
app_name="SOLIDWORKS V3 Launcher.app"
stem="SOLIDWORKS-V3-Launcher-macOS-arm64"
zip="$output/$stem.zip"
dmg="$output/$stem.dmg"
if [[ -e "$zip" || -L "$zip" || -e "$dmg" || -L "$dmg" ]]; then
    printf 'The output directory already contains release packages.\n' >&2
    exit 2
fi

test "$(plutil -extract CFBundleIdentifier raw "$app/Contents/Info.plist")" = org.swv3.launcher
codesign --verify --deep --strict "$app"
stage=$(mktemp -d "$output/.swv3-release.XXXXXXXX")
mount="$stage/mount"
mounted=false
cleanup() {
    if "$mounted" && ! hdiutil detach "$mount" -quiet; then
        printf 'Still mounted at %s\n' "$mount" >&2
        return
    fi
    rm -r -- "$stage"
}
trap cleanup EXIT

mkdir -p "$stage/payload" "$mount"
ditto --norsrc --noextattr --noqtn "$app" "$stage/payload/$app_name"
ditto -c -k --norsrc --noextattr --noqtn --keepParent \
    "$stage/payload/$app_name" "$stage/$stem.zip"
unzip -tq "$stage/$stem.zip"

ln -s /Applications "$stage/payload/Applications"
hdiutil create -quiet -fs HFS+ -volname "SOLIDWORKS V3 Launcher" \
    -format UDZO -srcfolder "$stage/payload" "$stage/$stem.dmg"
hdiutil verify -quiet "$stage/$stem.dmg"
hdiutil attach -quiet -readonly -nobrowse -noautoopen -mountpoint "$mount" "$stage/$stem.dmg"
mounted=true
test "$(readlink "$mount/Applications")" = /Applications
codesign --verify --deep --strict "$mount/$app_name"
hdiutil detach "$mount" -quiet
mounted=false

for package in "$stem.zip" "$stem.dmg"; do
    mv -n "$stage/$package" "$output/"
    if [[ -e "$stage/$package" ]]; then
        printf 'Output appeared during packaging: %s\n' "$output/$package" >&2
        exit 1
    fi
done
