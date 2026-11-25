#!/usr/bin/env python3
"""Assemble a private macOS app from an existing licensed installation."""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory


TOOLS = Path(__file__).resolve().parent
RUNTIME_LOADER = Path("lib/wine/x86_64-unix/wine")
PROGRAMS = (
    Path("drive_c/Program Files/SOLIDWORKS/SLDWORKS.exe"),
    Path("drive_c/Program Files/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe"),
)


def copy_tree(original: Path, destination: Path) -> None:
    clone = subprocess.run(["/bin/cp", "-cR", str(original), str(destination)], capture_output=True)
    if clone.returncode != 0:
        if destination.exists():
            shutil.rmtree(destination)
        subprocess.run(["/bin/cp", "-R", str(original), str(destination)], check=True)


def internalize_fonts(seed: Path, runtime: Path, runtime_copy: Path) -> int:
    fonts = Path("share/wine/fonts")
    host_path = "Z:" + str(runtime / fonts).replace("/", "\\\\") + "\\\\"
    entry = re.compile(rb'(?m)^("[^\r\n]+"=")' + re.escape(host_path.encode()) +
                       rb'([A-Za-z0-9_@.-]+)"$')
    guest_fonts = seed / "drive_c/windows/Fonts"
    changes = 0

    def copy_font(match: re.Match[bytes]) -> bytes:
        name = match[2].decode("ascii")
        source = runtime_copy / fonts / name
        if name in {".", ".."} or not source.is_file():
            raise ValueError(f"Wine font missing: {name}")
        target = guest_fonts / f"swv3-{name}"
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or target.read_bytes() != source.read_bytes():
                raise ValueError(f"Wine font destination already exists: {target.name}")
        else:
            shutil.copyfile(source, target)
        return match[1] + target.name.encode("ascii") + b'"'

    for name in ("system.reg", "user.reg"):
        registry = seed / name
        if not registry.exists():
            continue
        updated, count = entry.subn(copy_font, registry.read_bytes())
        if count:
            registry.write_bytes(updated)
            changes += count
    return changes


def assemble(runtime: Path, prefix: Path, output: Path) -> None:
    if output.suffix != ".app" or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("Output must be a new .app path in an existing folder.")
    if not (runtime / RUNTIME_LOADER).is_file():
        raise ValueError("Supply the root of the compatible CrossOver-style runtime.")
    if not (prefix / "system.reg").is_file() or not any((prefix / exe).is_file() for exe in PROGRAMS):
        raise ValueError("Supply a closed Wine prefix with an existing SOLIDWORKS installation.")
    if output.is_relative_to(runtime) or output.is_relative_to(prefix):
        raise ValueError("The output must be outside both inputs.")

    with TemporaryDirectory(prefix=".swv3-bundle-", dir=output.parent) as staging:
        stage = Path(staging)
        app = stage / output.name
        contents = app / "Contents"
        resources = contents / "Resources"
        seed = resources / "prefix-seed"
        runtime_copy = resources / "runtime/CrossOver"
        (contents / "MacOS").mkdir(parents=True)
        runtime_copy.parent.mkdir(parents=True)
        copy_tree(prefix, seed)
        copy_tree(runtime, runtime_copy)

        host_drive = seed / "dosdevices/z:"
        if host_drive.is_symlink() and host_drive.readlink() == Path("/"):
            host_drive.unlink()
        print(f"Moved {internalize_fonts(seed, runtime, runtime_copy)} Wine font registrations into C:", flush=True)
        for link in resources.rglob("*"):
            if link.is_symlink() and (link.readlink().is_absolute() or
                                      not link.resolve().is_relative_to(resources)):
                raise ValueError(f"External bundle symlink: {link.relative_to(resources)}")

        shutil.copyfile(TOOLS / "Info.plist", contents / "Info.plist")
        launcher = contents / "MacOS/SOLIDWORKS"
        shutil.copyfile(TOOLS.parent / "solidworks-v3-local-launcher.sh", launcher)
        launcher.chmod(0o755)
        subprocess.run(["/bin/bash", str(TOOLS / "build-icon.sh"), str(resources / "SOLIDWORKS.icns")],
                       check=True)
        quicklook = stage / "quicklook"
        subprocess.run(["/bin/bash", str(TOOLS.parent / "solidworks-quicklook/build.sh"), str(quicklook)],
                       check=True)
        (contents / "PlugIns").mkdir()
        for extension in quicklook.glob("*.appex"):
            extension.rename(contents / "PlugIns" / extension.name)

        bridge = seed / "drive_c/sw-v3/file-bridge.exe"
        bridge.parent.mkdir(exist_ok=True)
        subprocess.run(["x86_64-w64-mingw32-gcc", "-municode", "-O2",
                        str(TOOLS.parent / "solidworks-v3-file-bridge.c"), "-o", str(bridge),
                        "-lole32", "-loleaut32", "-luuid"], check=True)

        subprocess.run(["/usr/bin/codesign", "--sign", "-", str(app)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)], check=True)
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared while packaging.")
        app.rename(output)
        print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        assemble(args.runtime.resolve(), args.prefix.resolve(), args.output.absolute())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
