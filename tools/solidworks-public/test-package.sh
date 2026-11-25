#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 || ! -d "$1/Contents/Resources/DesktopTemplate" ]]; then
    printf 'Usage: %s path/to/launcher.app\n' "$0" >&2
    exit 2
fi
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/swv3-package-check.XXXXXXXX")
trap 'rm -r -- "$scratch"' EXIT
xcrun --sdk macosx swiftc -O "$here/DesktopPackage.swift" "$here/PackageChecks.swift" -o "$scratch/check"
"$scratch/check" "$1/Contents/Resources"
