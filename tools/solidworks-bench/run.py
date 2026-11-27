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

import viewport


def windows_path(path):
    return "Z:" + str(path.resolve()).replace("/", "\\")


def process_ids(runtime, launched_pid=None):
    processes = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True)
    cad = []
    servers = []
    for line in processes.splitlines():
        pid, command = line.strip().split(maxsplit=1)
        if command.lower().endswith(r"\sldworks.exe") and (launched_pid is None or int(pid) == launched_pid):
            cad.append(int(pid))
        if command.startswith(str(runtime) + "/") and command.endswith("/wineserver"):
            servers.append(int(pid))
    if len(cad) > 1:
        raise RuntimeError("More than one SOLIDWORKS process is running.")
    return cad, servers


def build_probe(output):
    probe = output / "probe.exe"
    subprocess.run(
        ["x86_64-w64-mingw32-gcc", "-municode", "-O2", str(Path(__file__).with_name("Probe.c")),
         "-o", str(probe), "-lole32", "-loleaut32", "-luuid"], check=True
    )
    return probe


def build_host_usage(output):
    binary = output / "host-usage"
    subprocess.run(["xcrun", "clang", "-O2", str(Path(__file__).with_name("HostUsage.c")),
                    "-o", str(binary)], check=True)
    return binary


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
    parser.add_argument("--app", type=Path)
    parser.add_argument("--runtime", type=Path, help="runtime for an isolated session")
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--part", type=Path)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path,
                        help="include nested CAD files under this test assembly tree in the manifest")
    parser.add_argument("--output", type=Path, required=True, help="new directory")
    parser.add_argument("--restarts", type=int, choices=range(0, 11), default=0)
    parser.add_argument("--operations", type=int, choices=range(1, 21), default=5)
    traces = parser.add_mutually_exclusive_group()
    traces.add_argument("--frame-trace", type=Path, help="measure Apple OpenGL swaps using this process trace")
    traces.add_argument("--display-trace", type=Path, help="measure changed window frames using ScreenCaptureKit")
    parser.add_argument("--wmgl-frame-log", type=Path,
                        help="also summarize WineMetalGL presentation submissions from a diagnostic build")
    parser.add_argument("--steps", type=int, default=180)
    parser.add_argument("--pace-ms", type=int, help="delay between samples (default: 0 for COM, 16 for mouse)")
    parser.add_argument("--input", dest="input_mode", choices=("com", "mouse"), default="com",
                        help="drive the view through COM or guest Win32 middle-button events")
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--dispatch", choices=("named", "cached"), default="cached",
                        help="resolve the COM method every time or cache its DISPID")
    parser.add_argument("--rebuild-scene", action="store_true", help="rebuild the disposable scene after rotation")
    parser.add_argument("--shaded", action="store_true", help="use Shaded display style for the disposable scene")
    parser.add_argument("--without-display-effects", action="store_true",
                        help="turn off shadows, ambient occlusion and RealView in the isolated session")
    parser.add_argument("--expected-viewport", nargs=2, metavar=("WIDTH", "HEIGHT"), type=int,
                        help="require these render dimensions in the active backend trace")
    parser.add_argument("--expected-components", type=int, help="require this assembly occurrence count")
    parser.add_argument("--require-full-detail", action="store_true",
                        help="require dynamic detail reduction and Large Assembly Settings to be off")
    args = parser.parse_args()

    if (not args.app and not args.runtime) or (args.restarts and (not args.app or args.runtime)):
        parser.error("Supply --app, or --runtime for an already running isolated session.")
    viewport_mode = args.frame_trace or args.display_trace
    if args.pace_ms is None:
        args.pace_ms = 16 if args.input_mode == "mouse" else 0
    if viewport_mode and (args.restarts or not 2 <= args.steps <= 2000 or
                          not 0 <= args.pace_ms <= 1000):
        parser.error("Viewport mode requires an existing session, 2–2000 steps, and 0–1000 ms pacing.")
    if not viewport_mode and (args.fixture_root or args.rebuild_scene or args.shaded or args.input_mode == "mouse"):
        parser.error("--fixture-root, --rebuild-scene, --shaded, and --input mouse require a viewport trace.")
    if args.require_full_detail and not viewport_mode:
        parser.error("--require-full-detail requires a viewport trace.")
    if args.without_display_effects and not viewport_mode:
        parser.error("--without-display-effects requires a viewport trace.")
    if (args.expected_viewport or args.expected_components is not None) and not viewport_mode:
        parser.error("Expected viewport dimensions and component count require a viewport trace.")
    if args.wmgl_frame_log and not args.display_trace:
        parser.error("--wmgl-frame-log requires --display-trace to report visible frames separately.")
    if args.expected_viewport and not (args.frame_trace or args.wmgl_frame_log):
        parser.error("--expected-viewport requires an Apple OpenGL or WineMetalGL driver trace.")
    if ((args.expected_viewport and min(args.expected_viewport) <= 0) or
            (args.expected_components is not None and args.expected_components <= 0)):
        parser.error("Expected viewport dimensions and component count must be positive.")
    if args.input_mode == "mouse" and not 0 < args.steps * args.pace_ms <= 120_000:
        parser.error("Mouse pacing must be positive and the planned drag must take no more than 120 seconds.")
    app = args.app.resolve() if args.app else None
    prefix, output = args.prefix.resolve(), args.output.resolve()
    runtime = args.runtime.resolve() if args.runtime else app / "Contents/Resources/runtime/CrossOver"
    loader = runtime / "lib/wine/x86_64-unix/wine"
    if not loader.is_file() or (prefix / "dosdevices/z:").resolve() != Path("/"):
        parser.error("The supported local V3 runtime and Z: mapping are required.")
    part = args.part.resolve() if args.part else None
    assembly = args.assembly.resolve()
    if (not assembly.is_file() or assembly.suffix.lower() != ".sldasm" or
        not viewport_mode and (not part or not part.is_file() or part.suffix.lower() != ".sldprt")):
        parser.error("Supply a SOLIDWORKS assembly with resolvable references and --part for the file benchmark.")
    if args.fixture_root:
        args.fixture_root = args.fixture_root.resolve()
        if not args.fixture_root.is_dir() or not assembly.is_relative_to(args.fixture_root):
            parser.error("--fixture-root must contain the test assembly.")
    if viewport_mode and not (prefix / ".swv3-graphics-lab").is_file():
        parser.error("Use a separate test prefix marked with .swv3-graphics-lab for viewport tests.")
    output.mkdir(mode=0o700)
    probe = build_probe(output)
    environment = dict(os.environ, WINEPREFIX=str(prefix), CX_ROOT=str(runtime), WINEDEBUG="-all")

    def run_probe(*argv, timeout=30):
        return subprocess.run([str(loader), windows_path(probe), *argv], cwd=prefix / "drive_c",
                              env=environment, text=True, timeout=timeout, capture_output=True)

    def require(*argv, timeout=30):
        result = run_probe(*argv, timeout=timeout)
        if result.returncode:
            detail = result.stdout.strip() or result.stderr.strip()
            raise RuntimeError(f"Probe {argv[0]} failed ({result.returncode}): {detail}")
        return result.stdout.strip()

    if viewport_mode:
        cad, servers = process_ids(runtime)
        if not cad or len(servers) != 1:
            raise RuntimeError("Viewport mode requires one SOLIDWORKS process and one matching Wine server.")
        host_usage = build_host_usage(output)
        viewport.benchmark(args, require, output, assembly, windows_path, prefix, host_usage,
                           {"solidworks": cad[0], "wineserver": servers[0]}, runtime)
        return

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
