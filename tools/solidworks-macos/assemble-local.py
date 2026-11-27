#!/usr/bin/env python3
"""Assemble a private macOS app from an existing licensed installation."""

import argparse
import filecmp
from pathlib import Path
import plistlib
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


def validate_vertex_span(runtime: Path, program: Path, source: Path) -> None:
    guest_module = runtime / "lib/wine/x86_64-windows/winemetalgl.dll"
    local_module = program.with_name("winemetalgl.dll")
    if not (guest_module.is_file() and local_module.is_file() and
            program.with_name("opengl32.dll").is_file()):
        raise ValueError("The graphics preview requires matching WineMetalGL PE modules and the app-local OpenGL forwarder.")
    if not filecmp.cmp(guest_module, local_module, shallow=False):
        raise ValueError("The runtime and app-local WineMetalGL PE modules differ.")
    host = runtime / "lib/wine/x86_64-unix"
    for name in ("winemetalgl.so", "libwinemetalgl.dylib"):
        module = host / name
        if not module.is_file() or b"wmgl_batch_vertex3fv_span\0" not in module.read_bytes():
            raise ValueError(f"{name} must be built with the Vertex Span patch.")
    if not (source / "LICENSE").is_file() or not (source / "LICENSES").is_dir():
        raise ValueError("Supply the WineMetalGL source directory with its license notices.")


def assemble(runtime: Path, prefix: Path, output: Path, graphics_lab: Path | None = None) -> None:
    if output.suffix != ".app" or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("Output must be a new .app path in an existing folder.")
    if not (runtime / RUNTIME_LOADER).is_file():
        raise ValueError("Supply the root of the compatible CrossOver-style runtime.")
    if not (prefix / "system.reg").is_file() or not any((prefix / exe).is_file() for exe in PROGRAMS):
        raise ValueError("Supply a closed Wine prefix with an existing SOLIDWORKS installation.")
    if output.is_relative_to(runtime) or output.is_relative_to(prefix):
        raise ValueError("The output must be outside both inputs.")
    if graphics_lab:
        program = next(prefix / program for program in PROGRAMS if (prefix / program).is_file())
        validate_vertex_span(runtime, program, graphics_lab)

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
        if graphics_lab:
            info_path = contents / "Info.plist"
            info = plistlib.loads(info_path.read_bytes())
            info.update(CFBundleIdentifier="local.solidworks2025.v3vertexspanpreview",
                        CFBundleName="SOLIDWORKS V3 Vertex Span Preview",
                        CFBundleDisplayName="SOLIDWORKS V3 Vertex Span Preview",
                        CFBundleShortVersionString="0.3.0", CFBundleVersion="1")
            for key in ("CFBundleDocumentTypes", "UTExportedTypeDeclarations", "UTImportedTypeDeclarations"):
                info.pop(key, None)
            info_path.write_bytes(plistlib.dumps(info))
            (resources / "graphics-lab").touch()
            (seed / ".swv3-graphics-lab").touch()
            notices = resources / "Notices" / "WineMetalGL"
            notices.mkdir(parents=True)
            shutil.copyfile(graphics_lab / "LICENSE", notices / "LICENSE")
            shutil.copytree(graphics_lab / "LICENSES", notices / "LICENSES")
        launcher = contents / "MacOS/SOLIDWORKS"
        shutil.copyfile(TOOLS.parent / "solidworks-v3-local-launcher.sh", launcher)
        launcher.chmod(0o755)
        subprocess.run(["/bin/bash", str(TOOLS / "build-icon.sh"), str(resources / "SOLIDWORKS.icns")],
                       check=True)
        if not graphics_lab:
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
    parser.add_argument("--graphics-lab", type=Path, metavar="WINEMETALGL_SOURCE",
                        help="package the private Vertex Span preview with an isolated profile and OpenGL fallback")
    args = parser.parse_args()
    try:
        assemble(args.runtime.resolve(), args.prefix.resolve(), args.output.absolute(),
                 args.graphics_lab.resolve() if args.graphics_lab else None)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
