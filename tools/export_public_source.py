#!/usr/bin/env python3
"""Export an allowlisted, tracked source snapshot without Git history or local inputs."""

import argparse
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
EXACT = {
    ".gitignore", ".github/workflows/quality.yml", "AGENTS.md", "LICENSE",
    "docs/ARCHITECTURE_RU.md", "docs/DEV_WORKFLOW_RU.md", "docs/PUBLIC_RELEASE.md",
    "docs/PUBLIC_RELEASE_EN.md",
    "docs/ROADMAP_NO_WINE_RU.md", "docs/patches/MANIFEST.md", "docs/patches/v3.series",
    "docs/wbemprox-ipenabled.patch", "docs/MACOS_BUILD.md", "CONTRIBUTING.md",
    "docs/BENCHMARKS_RU.md", "docs/RELEASE-v0.2.0.md",
    "docs/benchmarks/operations.csv", "docs/benchmarks/startup.json",
    "README.ru.md", "docs/BENCHMARKS.md", "docs/DEVELOPMENT.md", "docs/GRAPHICS_PREVIEW.md",
    "docs/RELEASE-v0.3.0-preview.1.md", "docs/benchmarks/graphics-preview-benchmarks.json",
    "licenses/WineMetalGL-LGPL-3.0.txt", "licenses/WineMetalGL-GPL-3.0.txt",
    ".github/workflows/macos-package.yml",
    "docs/SOLIDWORKS_V3_APPKIT_TOOLBOX_RU.md", "docs/SOLIDWORKS_V3_ENGINEERING_AUDIT_RU.md",
    "docs/SOLIDWORKS_V3_FILE_FORMATS_AND_INPUT_RU.md", "docs/SOLIDWORKS_V3_NATIVE_FILES_RU.md",
    "docs/SOLIDWORKS_V3_PROPERTYMANAGER_FIX_RU.md", "docs/SOLIDWORKS_V3_QUICK_LOOK_TOOLBOX_RU.md",
    "docs/SOLIDWORKS_V3_TASK_PANE_RESIZE_RU.md",
    "licenses/Wine-LGPL-2.1.txt", "work/bench_suite.py",
}
CODE = {".c", ".cpp", ".def", ".h", ".json", ".m", ".md", ".patch", ".plist",
        ".py", ".s", ".sh", ".swift", ".txt"}
HOME_PATH = b"/" + b"Users/"
PRIVATE = re.compile(
    HOME_PATH + rb"|/var/" + rb"folders/|BEGIN [A-Z ]*PRIVATE KEY|"
    rb"github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}"
)
PNG_ASSETS = {
    PurePosixPath("docs/assets/solidworks-macos-icon.png"): 256 * 1024,
    PurePosixPath("docs/assets/toolbox-demo.png"): 768 * 1024,
}


def included(path: PurePosixPath) -> bool:
    if str(path) in EXACT or path in PNG_ASSETS:
        return True
    if path.parts[:2] in (("docs", "patches"), ("recompiler", "fixtures")):
        return path.suffix in CODE
    return (path.parts[0] in ("tools", "recompiler") and
            path.parts[:2] != ("recompiler", "docs") and path.suffix in CODE)


def content(path: PurePosixPath, raw: bytes) -> bytes:
    if path in PNG_ASSETS:
        if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > PNG_ASSETS[path]:
            raise ValueError(f"Invalid PNG asset: {path}")
        return raw
    if path.suffix == ".patch":
        # The ---/+++ paths are repository-relative. Drop local diff command lines.
        raw = b"".join(line for line in raw.splitlines(keepends=True)
                       if not (line.startswith(b"diff -") and HOME_PATH in line))
    if b"\0" in raw or PRIVATE.search(raw):
        raise ValueError(f"Review required for {path}")
    return raw


def readme_at_root(raw: bytes) -> bytes:
    def relocate(match: re.Match[bytes]) -> bytes:
        target = match[1]
        return b"](" + (target[3:] if target.startswith(b"../") else b"docs/" + target) + b")"

    return re.sub(rb"\]\((?![a-z]+:|#)([^\s)]+)\)", relocate, raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new destination outside the working tree")
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink() or output.is_relative_to(ROOT):
        parser.error("output must be a new path outside the working tree")

    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.revision}^{{tree}}"], cwd=ROOT, text=True
    ).strip()
    names = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--name-only", revision], cwd=ROOT)
    paths = [PurePosixPath(name.decode()) for name in names.split(b"\0") if name]
    selected = [path for path in paths if included(path)]
    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", revision, "--", *map(str, selected)], cwd=ROOT
    )
    snapshot = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        for member in files:
            if member.isdir():
                continue
            path = PurePosixPath(member.name)
            if not member.isfile() or not included(path) or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unexpected archive entry: {path}")
            payload = files.extractfile(member)
            assert payload is not None
            snapshot[path] = (content(path, payload.read()), member.mode & 0o755)

    readme, _ = snapshot[PurePosixPath("docs/PUBLIC_RELEASE_EN.md")]
    snapshot[PurePosixPath("README.md")] = (readme_at_root(readme), 0o644)
    output.mkdir()
    for path, (data, mode) in snapshot.items():
        target = output.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode)
    print(f"Exported {len(snapshot)} files to {output}")


if __name__ == "__main__":
    main()
