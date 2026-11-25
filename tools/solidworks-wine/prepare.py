#!/usr/bin/env python3
"""Prepare a clean Wine source tree for the SOLIDWORKS V3 compatibility build."""

import argparse
from hashlib import file_digest
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


BASELINE_SHA256 = "ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872"
PATCHES = Path(__file__).resolve().parents[2] / "docs" / "patches"


def prepare(archive: Path, output: Path) -> None:
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("Output must be a new path in an existing directory.")
    with archive.open("rb") as payload:
        digest = file_digest(payload, "sha256").hexdigest()
    if digest != BASELINE_SHA256:
        raise ValueError(f"Unexpected CrossOver 26.3.0 source archive SHA-256: {digest}")

    with TemporaryDirectory(prefix=".wine-source-", dir=output.parent) as staging:
        subprocess.run(["tar", "-xzf", str(archive), "-C", staging, "sources/wine"], check=True)
        source = Path(staging) / "sources" / "wine"
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        for entry in (PATCHES / "v3.series").read_text().splitlines():
            print(f"Applying {entry}", flush=True)
            subprocess.run(["git", "apply", "--whitespace=nowarn", str(PATCHES / entry)],
                           cwd=source, check=True)
        (source / ".git").rename(Path(staging) / "git-metadata")
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared while preparing the source tree.")
        source.rename(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="CodeWeavers CrossOver 26.3.0 FOSS source archive")
    parser.add_argument("output", type=Path, help="new directory for patched Wine sources")
    args = parser.parse_args()
    try:
        prepare(args.archive.absolute(), args.output.absolute())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
