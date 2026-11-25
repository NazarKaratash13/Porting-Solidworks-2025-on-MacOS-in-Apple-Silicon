#!/bin/bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: %s output-directory [parent-bundle-id]\n' "$0" >&2
    exit 2
fi
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
output=$1
mkdir -p "$output"

python3 - "$output" "${2:-local.solidworks2025.v3resize}" <<'PY'
from pathlib import Path
import plistlib
import sys

output = Path(sys.argv[1])
bundle = sys.argv[2]
types = [f"{prefix}.{suffix}"
         for prefix in (bundle, "com.shapr3d.solidworks", "com.solidworks")
         for suffix in ("sldprt", "sldasm", "slddrw")]

for name, point, provider in (("Preview", "preview", "SWPreviewProvider"),
                              ("Thumbnail", "thumbnail", "SWThumbnailProvider")):
    executable = f"SOLIDWORKS{name}"
    contents = output / f"{executable}.appex" / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    attributes = {"QLSupportedContentTypes": types}
    if point == "preview":
        attributes["QLIsDataBasedPreview"] = True
    info = {
        "CFBundleIdentifier": f"{bundle}.quicklook.{point}",
        "CFBundleExecutable": executable,
        "CFBundleName": executable,
        "CFBundleDisplayName": f"SOLIDWORKS {name}",
        "CFBundlePackageType": "XPC!",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleSupportedPlatforms": ["MacOSX"],
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "14.0",
        "NSExtension": {
            "NSExtensionPointIdentifier": f"com.apple.quicklook.{point}",
            "NSExtensionPrincipalClass": provider,
            "NSExtensionAttributes": attributes,
        },
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))

(output / "QuickLook.entitlements").write_bytes(plistlib.dumps({
    "com.apple.security.app-sandbox": True,
    "com.apple.security.files.user-selected.read-only": True,
}))
PY

for type in Preview Thumbnail; do
    extension="$output/SOLIDWORKS$type.appex"
    if [[ "$type" = Thumbnail ]]; then
        definition=1
        framework=QuickLookThumbnailing
    else
        definition=0
        framework=QuickLookUI
    fi
    xcrun --sdk macosx clang -arch arm64 -mmacosx-version-min=14.0 -fobjc-arc \
        -fapplication-extension -O2 -Wall -Wextra -Werror -Wno-unused-parameter \
        -DSW_THUMBNAIL="$definition" "$source_dir/StoredPreview.m" "$source_dir/Provider.m" \
        -framework Foundation -framework CoreGraphics -framework ImageIO -framework "$framework" -lz \
        -o "$extension/Contents/MacOS/SOLIDWORKS$type"
    codesign --force --sign - --entitlements "$output/QuickLook.entitlements" "$extension"
    codesign --verify --strict "$extension"
done
