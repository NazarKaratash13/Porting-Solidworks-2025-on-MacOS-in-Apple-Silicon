#!/usr/bin/env python3
"""Launch a disposable SOLIDWORKS V3 session and benchmark one CAD fixture."""

import argparse
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import time

import run
import viewport


def copy_fixtures(root, dest):
    for source in viewport.cad_files(root, recursive=True):
        path = dest / source.relative_to(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)


def model_metrics(metrics):
    marker, *tokens = metrics.splitlines()[-1].split()
    values = dict((key, float(value)) for key, value in (token.split("=") for token in tokens))
    if marker != "model" or any(not math.isfinite(values[k]) or values[k] <= 0
                                for k in ("mass_kg", "volume_m3")):
        raise RuntimeError("Invalid mass or volume reported by SOLIDWORKS.")
    return values


def check_model(metrics, step, stl):
    values = model_metrics(metrics)
    geometry = collections.Counter(re.findall(rb"^\s*#\d+\s*=\s*(\w+)\s*\(",
                                              step.read_bytes(), re.MULTILINE))
    if not geometry[b"MANIFOLD_SOLID_BREP"] or not geometry[b"ADVANCED_FACE"]:
        raise RuntimeError("The STEP export contains no solid with faces.")
    with stl.open("rb") as stream:
        header = stream.read(84)
        triangles = struct.unpack_from("<I", header, 80)[0] if len(header) == 84 else 0
        if not triangles or stl.stat().st_size != 84 + 50 * triangles:
            raise RuntimeError("The STL export is not a complete binary mesh.")
        mesh = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(values, stl_triangles=triangles, stl_mesh_sha256=mesh,
                step_entities={key.decode("ascii"): count for key, count in sorted(geometry.items())})


def wait_for(process, check, seconds, description):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{description}: process exited with {process.returncode}.")
        if check():
            return
        time.sleep(0.5)
    raise RuntimeError(f"{description}: timed out after {seconds} seconds.")


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def compare(baseline, result):
    if baseline["frame"] != result["frame"]:
        raise RuntimeError("Window size differs from baseline.")
    before, after = (series["viewport"] for series in (baseline, result))
    if len(before["passes"]) != len(after["passes"]):
        raise RuntimeError("Pass count differs from baseline.")
    for key in ("components", "manifest", "steps", "pace_ms", "detail_settings", "display_effects",
                "input", "display_style", "frame_source", "capture_width"):
        if before[key] != after[key]:
            raise RuntimeError(f"Viewport test differs from baseline: {key}")
    check_mass(baseline["engineering"], result["engineering"])
    for key in ("step_entities", "stl_mesh_sha256"):
        if baseline["engineering"][key] != result["engineering"][key]:
            raise RuntimeError(f"Engineering result differs from baseline: {key}")
    throughput = [statistics.median(p["fps"] for p in series["passes"]) for series in (before, after)]
    return {"geometry_matches": True, "median_fps_before": throughput[0], "median_fps_after": throughput[1],
            "fps_ratio": round(throughput[1] / throughput[0], 4)}


def check_mass(expected, actual):
    for key in ("mass_kg", "volume_m3"):
        # Parallel CAD reductions may differ in their last floating point digits.
        if not math.isclose(expected[key], actual[key], rel_tol=1e-10, abs_tol=0):
            raise RuntimeError(f"Engineering result differs from baseline: {key}, "
                               f"{expected[key]:.15g} vs {actual[key]:.15g}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True, help="packaged Graphics Lab, never installed V3")
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--part", type=Path, required=True, help="relative to the fixture root")
    parser.add_argument("--assembly", type=Path, required=True, help="relative to the fixture root")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-components", type=int, default=733)
    parser.add_argument("--frame", type=int, nargs=2, default=(3606, 2158))
    parser.add_argument("--steps", type=int, choices=range(60, 1201), default=480, metavar="60..1200")
    parser.add_argument("--operations", type=int, choices=range(1, 7), default=3)
    parser.add_argument("--input", choices=("mouse", "com"), default="mouse")
    parser.add_argument("--backend", choices=("metal", "opengl"), default="metal")
    parser.add_argument("--compare", type=Path, help="compare the CAD result against a previous suite.json")
    parser.add_argument("--evidence", action="store_true", help="save timestamped screenshots during rotation")
    parser.add_argument("--sample", action="store_true", help="record a separate sampled stack trace during rotation")
    parser.add_argument("--driver-stats", action="store_true", help="enable instrumentation in a diagnostic runtime")
    args = parser.parse_args()
    if args.compare and (args.sample or args.driver_stats):
        parser.error("Compare only production measurements, with profiling disabled.")
    app, root, output = (path.resolve() for path in (args.app, args.fixture_root, args.output))
    resources = app / "Contents/Resources"
    seed = resources / "prefix-seed"
    runtime = (resources / "runtime/CrossOver").resolve()
    loader = runtime / "lib/wine/x86_64-unix/wine"
    if not ((resources / "graphics-lab").is_file() and (seed / ".swv3-graphics-lab").is_file() and
            loader.is_file() and not runtime.is_relative_to(Path("/Applications"))):
        parser.error("An isolated Graphics Lab bundle with its own packaged runtime is required.")
    if output.is_relative_to(root):
        parser.error("The output directory must be outside the fixture tree.")
    for path, extension in ((args.part, ".sldprt"), (args.assembly, ".sldasm")):
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() != extension or not (root / path).is_file():
            parser.error(f"Invalid {extension} fixture path: {path}")
    output.mkdir(mode=0o700)
    probe = run.build_probe(output)
    host = run.build_host_usage(output)
    capture = output / "DisplayTrace"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", "-O",
                    str(Path(__file__).with_name("DisplayTrace.swift")), "-o", str(capture)], check=True)
    fixtures = output / "fixtures"
    copy_fixtures(root, fixtures)
    control, assembly = (run.windows_path(fixtures / path) for path in (args.part, args.assembly))
    result = {"schema": 1, "diagnostic": args.sample or args.driver_stats}
    with tempfile.TemporaryDirectory(prefix="swv3-bench-", dir=output) as disposable:
        prefix = Path(disposable) / "prefix"
        subprocess.run(["/bin/cp", "-cR", str(seed), str(prefix)], check=True)
        win_disk = prefix / "drive_c"
        host_drive = prefix / "dosdevices/z:"
        if not host_drive.exists() and not host_drive.is_symlink():
            host_drive.symlink_to("/", target_is_directory=True)
        env = dict(os.environ, WINEPREFIX=str(prefix), CX_ROOT=str(runtime), WINEDEBUG="-all,err+all",
                   WINEMAC_GL_CLIP_V3="1", WINEMAC_GL_CLIP_WINDOW_RGN="0", WINEMAC_DISABLE_DOCK_SNAPSHOT="1",
                   WIN32U_SW_PM_TOPMOST="1", WIN32U_SW_TASKPANE_LAYOUT="1", WINEMAC_SW_BORDERLESS_RESIZE="1",
                   LANG="ru_RU.UTF-8", LC_ALL="ru_RU.UTF-8")
        env["WINEDLLOVERRIDES"] = "concrt140=n,b;winedbg.exe=d"
        if args.backend == "metal":
            env["WINEDLLOVERRIDES"] = "opengl32=n,b;winemetalgl=b;" + env["WINEDLLOVERRIDES"]
            env.update(SWV3_WMGL_WINEMAC_SURFACE="1", SWV3_WMGL_ZORDER_CLIP="0",
                       WINEMETALGL_X87="0")
            for name in ("SWV3_WMGL_BATCH_VERTEX3FV", "SWV3_WMGL_COMPACT_IMMEDIATE",
                         "SWV3_WMGL_CONTEXT_LOCAL_VERTICES", "SWV3_WMGL_VERTEX_SPANS"):
                env.setdefault(name, "0")
        else:
            env["WINEDLLOVERRIDES"] = "opengl32=b;winemetalgl=d;" + env["WINEDLLOVERRIDES"]
        if args.driver_stats:
            env.update(WINEMETALGL_STATS="1", WINEMETALGL_LOG="wine:trace", WINEMETALGL_LOG_FILE="0")
        program = win_disk / "Program Files/SOLIDWORKS/SLDWORKS.exe"
        if not program.is_file() or host_drive.resolve() != Path("/"):
            raise RuntimeError("The cloned seed lacks SOLIDWORKS or its Z: mapping.")
        if args.backend == "metal":
            pe_module = program.with_name("winemetalgl.dll")
            with pe_module.open("rb") as stream:
                result["winemetalgl_pe_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            with (runtime / "lib/wine/x86_64-windows/winemetalgl.dll").open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != result["winemetalgl_pe_sha256"]:
                    raise RuntimeError("The packaged and application-local PE modules differ.")
            unix_modules = runtime / "lib/wine/x86_64-unix"
            result["winemetalgl_host_sha256"] = {}
            for name in ("winemetalgl.so", "libwinemetalgl.dylib"):
                with (unix_modules / name).open("rb") as stream:
                    result["winemetalgl_host_sha256"][name] = hashlib.file_digest(stream, "sha256").hexdigest()
            result["winemetalgl_options"] = {
                name: env[name] for name in (
                    "SWV3_WMGL_BATCH_VERTEX3FV",
                    "SWV3_WMGL_COMPACT_IMMEDIATE",
                    "SWV3_WMGL_CONTEXT_LOCAL_VERTICES",
                    "SWV3_WMGL_CLIENT_UPLOAD_CACHE",
                    "SWV3_WMGL_VERTEX_SPANS",
                    "WINEMETALGL_BATCH",
                ) if name in env
            }

        def probe_command(*arguments, timeout=30, verify=True):
            job = subprocess.run([str(loader), run.windows_path(probe), *arguments], cwd=win_disk, env=env,
                                 text=True, capture_output=True, timeout=timeout)
            if verify and job.returncode:
                if arguments[0] == "mouse-view" and (job.returncode == 7 or
                        job.returncode == 6 and "target capture=1" in job.stdout):
                    raise viewport.InterruptedOrbit((job.stdout + job.stderr).strip())
                raise RuntimeError(f"{arguments[0]} failed: {job.returncode} {job.stdout} {job.stderr}")
            return job.stdout.strip() if verify else job.returncode == 0

        def probe_ready():
            try:
                return probe_command("ready", control, timeout=3, verify=False)
            except subprocess.TimeoutExpired:
                return False

        cad = observer = sampler = None
        with (output / "wine.log").open("w") as log:
            try:
                started = time.monotonic()
                cad = subprocess.Popen([str(loader), r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe", control],
                                       cwd=win_disk, env=env, stdout=log, stderr=log)
                wait_for(cad, probe_ready, 150, "Opening the control part")
                result["startup_to_part_seconds"] = round(time.monotonic() - started, 3)
                print(f"Control part ready in {result['startup_to_part_seconds']} s (PID {cad.pid}).", flush=True)
                native, step, stl = (output / f"export.{suffix}" for suffix in ("SLDPRT", "step", "stl"))
                result["engineering"] = check_model(
                    probe_command("verify-model", control, *map(run.windows_path, (native, step, stl)), timeout=90),
                    step, stl)
                native_path = run.windows_path(native)
                reopened = model_metrics(probe_command("verify-model", native_path, timeout=60))
                check_mass(result["engineering"], reopened)
                result["engineering"]["reopened"] = reopened
                probe_command("prepare-detail", native_path)
                scene = probe_command("scene", assembly, timeout=240)
                result["assembly_open_ms"] = float(scene.split()[1])
                expected_size = f"size {args.frame[0]} {args.frame[1]}"
                if probe_command("frame-size", assembly) != expected_size:
                    probe_command("frame-size", assembly, *map(str, args.frame))
                    time.sleep(1.5)
                if probe_command("frame-size", assembly) != expected_size:
                    raise RuntimeError(f"CAD did not reach the expected frame size: {expected_size}.")
                processes, servers = run.process_ids(runtime, cad.pid)
                if len(processes) != 1 or len(servers) != 1:
                    raise RuntimeError("Could not identify the laboratory CAD process and Wine server.")
                args.display_trace = output / "display.txt"
                args.wmgl_frame_log = output / "wine.log" if args.driver_stats else None
                args.expected_viewport = None
                args.frame_trace = None
                args.without_display_effects = args.rebuild_scene = args.require_full_detail = True
                args.shaded = False
                args.dispatch, args.input_mode, args.pace_ms = "cached", args.input, 16
                args.label = f"suite-{args.backend}"
                args.fixture_root = fixtures
                command = [str(capture), str(cad.pid), "260", str(args.display_trace)]
                if args.evidence:
                    command += ["--evidence", str(output / "images")]
                observer = subprocess.Popen(command, stdout=log, stderr=log)
                wait_for(observer, lambda: args.display_trace.is_file() and args.display_trace.stat().st_size,
                         20, "ScreenCaptureKit capture")
                if args.sample:
                    sample = output / "sample.txt"
                    delay = 3
                    duration = max(12, int(args.steps * .023 * args.operations))
                    sampler = subprocess.Popen(["/bin/sh", "-c", 'sleep "$1"; shift; exec "$@"',
                                                 "sample", str(delay), "/usr/bin/sample", str(cad.pid),
                                                 str(duration), "1", "-file", str(sample)], stdout=log, stderr=log)
                viewport.benchmark(args, probe_command, output, fixtures / args.assembly, run.windows_path,
                                   prefix, host, {"solidworks": cad.pid, "wineserver": servers[0]}, runtime)
                try:
                    detail_payload = probe_command("detail-state", assembly)
                except subprocess.TimeoutExpired:
                    print("Final read-only detail check timed out. Retrying once.", file=log, flush=True)
                    detail_payload = probe_command("detail-state", assembly)
                detail = viewport.detail_settings(detail_payload, required=True)
                if detail["large_assembly_preference"] != 0:
                    raise RuntimeError("Automatic Large Assembly Settings were re-enabled.")
                view = json.loads((output / "viewport.json").read_text())
                view["capture_width"] = 1280 if args.evidence else 640
                if not view["rebuild"]["completed"]:
                    raise RuntimeError("Assembly rebuild failed.")
                fps_values = [sample["fps"] for sample in view["passes"]]
                result.update(frame=list(args.frame), backend=args.backend, viewport=view,
                              target_fps=30, fps_target_met=not result["diagnostic"] and args.input == "mouse" and
                              len(fps_values) >= 3 and min(fps_values) >= 30)
                if args.compare:
                    baseline = json.loads(args.compare.read_text())
                    if baseline.get("diagnostic"):
                        raise RuntimeError("The baseline was recorded with profiling enabled.")
                    result["comparison"] = compare(baseline, result)
                (output / "suite.json").write_text(json.dumps(result, indent=2) + "\n")
            finally:
                stop(observer)
                stop(sampler)
                server = str(runtime / "bin/wineserver")
                try:
                    subprocess.run([server, "-k"], env=env, timeout=10, stdout=log, stderr=log, check=False)
                    subprocess.run([server, "-w"], env=env, timeout=15, stdout=log, stderr=log, check=False)
                finally:
                    stop(cad)
    print(f"Results: {output / 'suite.json'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
