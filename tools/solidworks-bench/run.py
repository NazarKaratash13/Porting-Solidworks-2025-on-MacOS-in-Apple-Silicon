#!/usr/bin/env python3
"""Measure a local SOLIDWORKS V3 installation with disposable document copies."""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def windows_path(path):
    return "Z:" + str(path.resolve()).replace("/", "\\")


def process_ids(runtime):
    processes = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True)
    cad = []
    servers = []
    for line in processes.splitlines():
        pid, command = line.strip().split(maxsplit=1)
        if command.lower().endswith(r"\sldworks.exe"):
            cad.append(int(pid))
        if command.startswith(str(runtime) + "/") and command.endswith("/wineserver"):
            servers.append(int(pid))
    if len(cad) > 1:
        raise RuntimeError("More than one SOLIDWORKS process is running.")
    return cad, servers


def footprint(pid):
    report = subprocess.check_output(
        ["/usr/bin/footprint", "--noCategories", "-f", "bytes", "-p", str(pid)], text=True, timeout=15
    )
    match = re.search(r"^\s*phys_footprint:\s*(\d+) B", report, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Physical footprint unavailable for PID {pid}.")
    return int(match[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--part", type=Path, required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory")
    parser.add_argument("--restarts", type=int, choices=range(0, 11), default=0)
    parser.add_argument("--operations", type=int, choices=range(1, 21), default=5)
    args = parser.parse_args()

    app, prefix, output = args.app.resolve(), args.prefix.resolve(), args.output.resolve()
    runtime = app / "Contents/Resources/runtime/CrossOver"
    loader = runtime / "lib/wine/x86_64-unix/wine"
    if not loader.is_file() or (prefix / "dosdevices/z:").resolve() != Path("/"):
        parser.error("The supported local V3 runtime and Z: mapping are required.")
    part, assembly = args.part.resolve(), args.assembly.resolve()
    if part.suffix.lower() != ".sldprt" or assembly.suffix.lower() != ".sldasm":
        parser.error("Supply a SOLIDWORKS part and a small assembly with resolvable file references.")
    output.mkdir(mode=0o700)
    probe = output / "probe.exe"
    subprocess.run(
        ["x86_64-w64-mingw32-gcc", "-municode", "-O2", str(Path(__file__).with_name("Probe.c")),
         "-o", str(probe), "-lole32", "-loleaut32", "-luuid"], check=True
    )
    environment = dict(os.environ, WINEPREFIX=str(prefix), CX_ROOT=str(runtime), WINEDEBUG="-all")

    def run_probe(*argv, timeout=30):
        return subprocess.run([str(loader), windows_path(probe), *argv], cwd=prefix / "drive_c",
                              env=environment, text=True, timeout=timeout, capture_output=True)

    def require(*argv):
        result = run_probe(*argv)
        if result.returncode:
            raise RuntimeError(f"Probe {argv[0]} failed ({result.returncode}): {result.stdout.strip()}")
        return result.stdout.strip()

    startup = []
    for attempt in range(1, args.restarts + 1):
        cad, servers = process_ids(runtime)
        if cad:
            require("can-exit", "")
            # ExitApp may return after Wine has already disconnected the COM client.
            run_probe("exit", "")
        deadline = time.monotonic() + 45
        while any(process_ids(runtime)):
            if time.monotonic() >= deadline:
                raise RuntimeError("The previous session did not close. A second instance was not started.")
            time.sleep(0.25)
        fixture = output / f"Startup {attempt:02d}.SLDASM"
        shutil.copyfile(assembly, fixture)
        started = time.monotonic()
        subprocess.run(["/usr/bin/open", "-a", str(app), str(fixture)], check=True)
        for _ in range(360):
            if time.monotonic() - started > 180:
                raise RuntimeError("SOLIDWORKS did not open the startup fixture within 180 seconds.")
            if process_ids(runtime)[0]:
                try:
                    if run_probe("ready", windows_path(fixture), timeout=2).returncode == 0:
                        break
                except subprocess.TimeoutExpired:
                    pass
            time.sleep(0.5)
        else:
            raise RuntimeError("SOLIDWORKS startup probe did not become ready.")
        elapsed = round(time.monotonic() - started, 3)
        startup.append({"run": attempt, "seconds": elapsed})
        print(f"Startup {attempt}: {elapsed:.3f} s", flush=True)
        (output / "startup.json").write_text(json.dumps(startup, indent=2) + "\n")

    if not process_ids(runtime)[0]:
        raise RuntimeError("Open the local installation before measuring document operations.")

    rows = []
    for attempt in range(1, args.operations + 1):
        for label, source in (("part", part), ("assembly", assembly)):
            fixture = output / f"{label.title()} {attempt:02d}{source.suffix.upper()}"
            copy = output / f"{label.title()} saved {attempt:02d}{source.suffix.upper()}"
            shutil.copyfile(source, fixture)
            metrics = require("measure", windows_path(fixture), windows_path(copy)).splitlines()[-1]
            elapsed = [float(value) for value in metrics.split()]
            time.sleep(1)
            cad, servers = process_ids(runtime)
            row = [label, attempt, *elapsed, footprint(cad[0]), sum(footprint(pid) for pid in servers)]
            rows.append(row)
            print(label, attempt, metrics, flush=True)
            with (output / "operations.csv").open("w", newline="") as destination:
                writer = csv.writer(destination, lineterminator="\n")
                writer.writerow(["document", "run", "open_ms", "rebuild_ms", "save_copy_ms",
                                 "solidworks_footprint_bytes", "wineserver_footprint_bytes"])
                writer.writerows(rows)
    print("Results:", output)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
