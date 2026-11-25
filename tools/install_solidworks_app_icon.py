#!/usr/bin/env python3
"""Install the Windows application icon in a local standalone macOS bundle."""

import argparse
from pathlib import Path
import plistlib
import struct
import subprocess
from tempfile import TemporaryDirectory

import pefile


def icon_images(executable: Path) -> dict[int, bytes]:
    # RT_GROUP_ICON 11 is the application icon in SOLIDWORKS 2025 SP05.
    # Its 128 and 256 pixel entries contain complete PNG files.
    with pefile.PE(str(executable), fast_load=True) as image:
        image.parse_data_directories(
            [pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )
        resources = {entry.id: entry.directory for entry in image.DIRECTORY_ENTRY_RESOURCE.entries}
        group = next(entry for entry in resources[14].entries if entry.id == 11)
        descriptor = group.directory.entries[0].data.struct
        table = image.get_data(descriptor.OffsetToData, descriptor.Size)
        reserved, kind, count = struct.unpack_from("<HHH", table)
        if reserved != 0 or kind != 1 or len(table) != 6 + 14 * count:
            raise ValueError("Invalid SOLIDWORKS icon group")

        entries = {entry.id: entry.directory.entries[0].data.struct for entry in resources[3].entries}
        images = {}
        for width, height, _, _, _, depth, size, resource_id in struct.iter_unpack(
            "<BBBBHHIH", table[6:]
        ):
            pixels = width or 256
            if (height or 256) != pixels or pixels not in (128, 256) or depth != 32:
                continue
            entry = entries[resource_id]
            png = image.get_data(entry.OffsetToData, entry.Size)
            if (
                len(png) == size
                and png.startswith(b"\x89PNG\r\n\x1a\n")
                and struct.unpack_from(">II", png, 16) == (pixels, pixels)
            ):
                images[pixels] = png
        if images.keys() != {128, 256}:
            raise ValueError("The application icon lacks its expected PNG resources")
        return images


def install_icon(app: Path) -> Path:
    contents = app / "Contents"
    resources = contents / "Resources"
    plist = contents / "Info.plist"
    data = plistlib.loads(plist.read_bytes())
    if data.get("CFBundleIdentifier") != "local.solidworks2025.standalone":
        raise ValueError(f"Unexpected bundle identifier in {plist}")

    executable = resources / "prefix-template/drive_c/Program Files/SOLIDWORKS/SLDWORKS.exe"
    images = icon_images(executable)
    icon = resources / "SOLIDWORKS.icns"
    data["CFBundleIconFile"] = icon.name
    with TemporaryDirectory(prefix=".sw-icon-", dir=contents) as temp_dir:
        temp = Path(temp_dir)
        iconset = temp / "SOLIDWORKS.iconset"
        iconset.mkdir()
        original = temp / "original.png"
        original.write_bytes(images[256])
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                suffix = "@2x" if scale == 2 else ""
                output = iconset / f"icon_{size}x{size}{suffix}.png"
                if pixels in images:
                    output.write_bytes(images[pixels])
                else:
                    subprocess.run(
                        ["/usr/bin/sips", "-z", str(pixels), str(pixels), str(original),
                         "--out", str(output)],
                        check=True, stdout=subprocess.DEVNULL,
                    )
        staged_icon = temp / icon.name
        subprocess.run(
            ["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(staged_icon)], check=True
        )
        staged_plist = temp / plist.name
        staged_plist.write_bytes(plistlib.dumps(data, sort_keys=False))
        staged_plist.chmod(plist.stat().st_mode & 0o777)
        staged_icon.replace(icon)
        staged_plist.replace(plist)
    app.touch()
    return icon


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, nargs="?", default=Path.home() / "Applications/SOLIDWORKS 2025.app")
    args = parser.parse_args()
    print(install_icon(args.app.expanduser()))
