"""Summarize Apple OpenGL swaps and host counters for a controlled orbit."""

import csv
import hashlib
import json
import math
import plistlib
import statistics
import struct
import subprocess
import threading
import time


class InterruptedOrbit(RuntimeError):
    """The verified middle-button drag lost its target before completion."""


FRAME = struct.Struct("<QQQ")


def clock_ns():
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)


def distribution(values):
    if not values:
        return None
    sorted_values = sorted(values)

    def percentile(p):
        position = (len(sorted_values) - 1) * p
        index = int(position)
        next_index = min(index + 1, len(sorted_values) - 1)
        return round(sorted_values[index] +
                     (sorted_values[next_index] - sorted_values[index]) * (position - index), 4)
    return {"count": len(values), "p50": percentile(0.50), "p95": percentile(0.95),
            "p99": percentile(0.99), "max": round(sorted_values[-1], 4)}

def frame_series(intervals):
    if not intervals or min(intervals) <= 0:
        raise RuntimeError("Positive frame intervals are required.")
    slow_count = math.ceil(len(intervals) / 100)
    slowest = sorted(intervals)[-slow_count:]
    return {"fps": round(1000 / statistics.mean(intervals), 3),
            "frame_time_ms": distribution(intervals),
            "one_percent_low_fps": round(1000 / statistics.mean(slowest), 3)}


def read_contexts(path):
    fields = ("context", "viewport_width", "viewport_height", "swap_interval", "accelerated",
              "cgl_profile", "renderer", "gl_version", "vendor")
    with path.with_name(path.name + ".contexts.tsv").open() as source:
        return {int(row[0]): {key: int(value) if index < 6 else value
                              for index, (key, value) in enumerate(zip(fields, row))}
                for row in csv.reader(source, delimiter="\t") if len(row) == len(fields)}


def frames_for(path, lower_ns, upper_ns, offset=0):
    with path.open("rb") as stream:
        stream.seek(offset)
        payload = stream.read()
    records = FRAME.iter_unpack(payload[:len(payload) // FRAME.size * FRAME.size])
    by_context = {}
    for context, before, after in records:
        if lower_ns <= before <= after <= upper_ns:
            by_context.setdefault(context, []).append((before, after))
    if not by_context:
        raise RuntimeError("No Apple OpenGL flushes in the orbit interval. Check the recorder and backend.")
    contexts = read_contexts(path)
    # An auxiliary window can also present. Prefer the largest observed viewport.
    def rank(context):
        meta = contexts.get(context, {})
        return (meta.get("viewport_width", 0) * meta.get("viewport_height", 0),
                len(by_context[context]))
    main = max(by_context, key=rank)
    selected = sorted({after: (before, after) for before, after in by_context[main]}.values(),
                      key=lambda frame: frame[1])
    if len(selected) < 2:
        raise RuntimeError("The main OpenGL viewport completed fewer than two flushes.")
    intervals = [(next_frame[1] - frame[1]) / 1e6
                 for frame, next_frame in zip(selected, selected[1:])]
    return {**frame_series(intervals),
            "flush_call_ms": distribution([(after - before) / 1e6 for before, after in selected]),
            "context": contexts.get(main), "observed_contexts": len(by_context),
            "frames": selected}


def gpu_stats():
    result = subprocess.run(["/usr/sbin/ioreg", "-a", "-r", "-d", "1", "-c", "IOAccelerator"],
                            capture_output=True, timeout=4, check=True)
    devices = plistlib.loads(result.stdout)
    for device in devices:
        stats = device.get("PerformanceStatistics", {})
        if "Device Utilization %" in stats:
            return {label: stats.get(key) for label, key in (
                ("device_utilization_pct", "Device Utilization %"),
                ("renderer_utilization_pct", "Renderer Utilization %"),
                ("tiler_utilization_pct", "Tiler Utilization %"),
                ("in_use_bytes", "In use system memory"))}
    return {}


def display_frames(path, lower_ns, upper_ns):
    with path.open() as stream:
        timestamps = (int(line) for line in stream if line.endswith("\n"))
        samples = sorted({value for value in timestamps if lower_ns <= value <= upper_ns})
    if len(samples) < 2:
        raise RuntimeError("Fewer than two changed window frames in the orbit interval.")
    intervals = [(end - start) / 1e6 for start, end in zip(samples, samples[1:])]
    return {**frame_series(intervals),
            "frames": [(sample,) for sample in samples]}

def wmgl_submissions(path, lower_ns, upper_ns):
    by_size = {}
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.startswith("swv3-frame ") or not line.endswith("\n"):
                continue
            _, _, ts, source, width, height, accepted = line.split()
            stamp = int(ts)
            size = int(width), int(height)
            if lower_ns <= stamp <= upper_ns and min(size) > 0:
                by_size.setdefault(size, []).append((stamp, source, int(accepted)))
    if not by_size:
        raise RuntimeError("No WineMetalGL presentation records in the orbit interval.")
    size, records = max(by_size.items(), key=lambda item: item[0][0] * item[0][1])
    stamps = sorted({stamp for stamp, _, accepted in records if accepted == 1})
    sources = {}
    for _, source, accepted in records:
        if accepted == 1:
            sources[source] = sources.get(source, 0) + 1
    intervals = [(b - a) / 1e6 for a, b in zip(stamps, stamps[1:])]
    return {"viewport_pixels": list(size), "attempted_submissions": len(records),
            "accepted_submissions_by_source": sources,
            "series": frame_series(intervals) if intervals else None}


def timed_counters(host_usage, processes):
    pids = {pid: label for label, pid in processes.items()}
    sample = subprocess.run([str(host_usage), *map(str, pids)], check=True,
                            capture_output=True, text=True, timeout=4)
    return {pids[int(pid)]: {"cpu_user_ns": int(user), "cpu_system_ns": int(system),
                            "footprint_bytes": int(footprint), "energy_nj": int(energy) or None}
            for pid, user, system, footprint, energy in csv.reader(sample.stdout.splitlines())}


def sample_orbit(require, args, host_usage, processes):
    samples = []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            row = {"time_ns": clock_ns()}
            for field, reader in (("processes", lambda: timed_counters(host_usage, processes)),
                                  ("gpu_system", gpu_stats)):
                try:
                    row[field] = reader()
                except (OSError, ValueError, subprocess.SubprocessError, plistlib.InvalidFileException) as error:
                    row[field + "_error"] = type(error).__name__
            samples.append(row)
            stop.wait(1)

    first = timed_counters(host_usage, processes)
    worker = threading.Thread(target=sample)
    worker.start()
    started = clock_ns()
    try:
        result = require(*args, timeout=300)
    finally:
        finished = clock_ns()
        stop.set()
        worker.join()
    last = timed_counters(host_usage, processes)
    delta = {}
    for label in first.keys() & last.keys():
        a, b = first[label], last[label]
        elapsed = finished - started
        cpu = sum(b[key] - a[key] for key in ("cpu_user_ns", "cpu_system_ns"))
        observed = [row["processes"][label]["footprint_bytes"] for row in samples
                    if label in row.get("processes", {})]
        delta[label] = {"average_cpu_pct_one_core": round(100 * cpu / elapsed, 2),
                        "peak_sampled_footprint_bytes": max([a["footprint_bytes"], b["footprint_bytes"], *observed]),
                        "estimated_process_watts": (round((b["energy_nj"] - a["energy_nj"]) / elapsed, 4)
                                                    if a["energy_nj"] and b["energy_nj"] and
                                                    b["energy_nj"] >= a["energy_nj"] else None)}
    return result, started, finished, samples, delta


def phase(payload, expected, start, finish, tail_ns=100_000_000):
    lines = payload.splitlines()
    if not lines or len(lines[0].split()) != 3:
        raise RuntimeError("Missing viewport probe timing.")
    first, *timings = lines
    marker, begin_ms, end_ms = first.split()
    begin, end = (round(float(value) * 1e6) for value in (begin_ms, end_ms))
    if marker != "phase" or len(timings) != expected:
        raise RuntimeError("Incomplete viewport probe response.")
    clock_aligned = start <= begin <= end <= finish
    # Compare host and guest clocks before using QPC boundaries.
    bounds = (begin, min(end + tail_ns, finish)) if clock_aligned else (start, finish)
    return (*bounds, "guest_qpc" if clock_aligned else "host_command_bounds",
            distribution([float(value) for value in timings]))


def cad_files(root, recursive):
    candidates = root.rglob("*") if recursive else root.iterdir()
    for source in sorted(candidates):
        if (source.name.startswith("~$") or
                source.suffix.lower() not in {".sldprt", ".sldasm", ".slddrw", ".step", ".stp", ".x_t", ".x_b"} or
                source.is_symlink() or not source.is_file()):
            continue
        yield source


def manifest(path, fixture_root=None):
    root = fixture_root or path.parent
    entries = {}
    for source in cad_files(root, fixture_root is not None):
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        entries[source.relative_to(root).as_posix()] = {"size": source.stat().st_size, "sha256": digest}
    return entries


def detail_settings(payload, required):
    fields = ("lod_target_fps", "large_assembly_mode", "lightweight_components",
              "large_assembly_preference", "large_assembly_threshold")
    tokens = payload.split()
    if len(tokens) != len(fields) + 1 or tokens[0] != "detail":
        raise RuntimeError("Invalid SOLIDWORKS detail settings response.")
    try:
        values = list(map(int, tokens[1:]))
    except ValueError as error:
        raise RuntimeError("Invalid SOLIDWORKS detail settings response.") from error
    settings = {key: None if value < 0 else value for key, value in zip(fields, values)}
    if required and any(settings[key] != 0 for key in fields[:3]):
        raise RuntimeError(f"Full-detail benchmark requires LOD target 0, Large Assembly Settings off "
                           f"and no lightweight components: {settings}")
    return settings


def benchmark(args, require, output, assembly, path_arg, prefix,
              host_usage, processes, runtime):
    scene, *release = require("scene", path_arg(assembly), timeout=300).splitlines()
    marker, open_ms, components, was_active = scene.split()
    if marker != "scene":
        raise RuntimeError("Missing assembly metrics.")
    if args.expected_components is not None and int(components) != args.expected_components:
        raise RuntimeError(f"Expected {args.expected_components} occurrences, found {components}.")
    detail = detail_settings(require("detail-state", path_arg(assembly)), args.require_full_detail)
    if args.without_display_effects:
        require("plain-view", path_arg(assembly))
    if args.shaded:
        require("shade-scene", path_arg(assembly))
        time.sleep(1)
    a = clock_ns()
    mode = "cached" if args.dispatch == "cached" else "timed"
    ipc = require(f"{mode}-ipc", path_arg(assembly), "120", "0")
    b = clock_ns()
    _, _, _, ipc_stats = phase(ipc, 120, a, b)
    report = {"schema": 1, "label": args.label, "scene": assembly.name, "components": int(components),
              "open_ms": None if was_active == "1" else float(open_ms),
              "solidworks_revision": release[0] if release else None,
              "host": subprocess.check_output(["/usr/bin/sw_vers", "-productVersion"], text=True).strip(),
              "manifest": manifest(assembly, args.fixture_root), "ipc_ms": ipc_stats, "settings": {},
              "steps": args.steps, "pace_ms": args.pace_ms, "dispatch": args.dispatch,
              "input": args.input_mode,
              "detail_settings": detail,
              "full_detail_required": args.require_full_detail,
              "display_style": "shaded" if args.shaded else "current",
              "frame_source": "apple_opengl_flush" if args.frame_trace else "changed_window_frames",
              "passes": []}
    if args.without_display_effects:
        report["display_effects"] = {"shadows": False, "ambient_occlusion": False, "realview": False}
    user_reg = (prefix / "user.reg").read_text(encoding="utf-8", errors="replace")
    for name in ("RetinaMode", "Use Performance Pipeline 2020", "Target Frame Rate", "Large Assy Target Frame Rate"):
        values = [line.split("=", 1)[1] for line in user_reg.splitlines() if line.startswith(f'"{name}"=')]
        report["settings"][name] = values[0] if len(values) == 1 else None
    for name in ("winemac.so", "win32u.so", "opengl32.so", "winemetalgl.so", "libwinemetalgl.dylib"):
        module = runtime / "lib/wine/x86_64-unix" / name
        if not module.is_file():
            continue
        with module.open("rb") as source:
            report.setdefault("modules", {})[name] = hashlib.file_digest(source, "sha256").hexdigest()
    print(f"{report['scene']}: {report['components']} component occurrences, open_ms={report['open_ms']}", flush=True)
    for index in range(1, args.operations + 1):
        mouse = args.input_mode == "mouse"
        operation = "mouse-view" if mouse else f"{mode}-view"
        command = (operation, path_arg(assembly), str(args.steps), str(args.pace_ms))
        offset = args.frame_trace.stat().st_size // FRAME.size * FRAME.size if args.frame_trace else 0
        try:
            payload, a, b, samples, delta = sample_orbit(require, command, host_usage, processes)
        except InterruptedOrbit:
            print(f"Pass {index}: interrupted drag, resetting the camera and retrying.", flush=True)
            time.sleep(1)
            payload, a, b, samples, delta = sample_orbit(require, command, host_usage, processes)
        begin, end, clock, timings = phase(payload, args.steps, a, b)
        if args.frame_trace:
            result = frames_for(args.frame_trace, begin, end, offset)
            columns = ("flush_start_ns", "flush_end_ns")
        else:
            result = display_frames(args.display_trace, begin, end)
            columns = ("display_ns",)
        if args.wmgl_frame_log:
            result["driver_submissions"] = wmgl_submissions(args.wmgl_frame_log, begin, end)
            result["viewport_pixels"] = result["driver_submissions"]["viewport_pixels"]
        elif args.frame_trace and result["context"]:
            context = result["context"]
            result["viewport_pixels"] = [context["viewport_width"], context["viewport_height"]]
        if args.expected_viewport and result.get("viewport_pixels") != args.expected_viewport:
            raise RuntimeError(f"Expected viewport {args.expected_viewport}, found {result.get('viewport_pixels')}.")
        frames = result.pop("frames")
        with (output / f"frames-{index:02}.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            writer.writerows(frames)
        with (output / f"host-{index:02}.json").open("w") as stream:
            json.dump(samples, stream, indent=2)
        gpu = [row.get("gpu_system", {}).get("device_utilization_pct") for row in samples]
        gpu = [value for value in gpu if value is not None]
        timings_key = "mouse_send_ms" if mouse else "orbit_com_ms"
        report["passes"].append({**result, "clock": clock, timings_key: timings, "host_usage": delta,
                                 "system_gpu_pct": round(statistics.mean(gpu), 2) if gpu else None})
        (output / "viewport.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Pass {index}: {result['fps']:.2f} FPS, P95 {result['frame_time_ms']['p95']:.2f} ms", flush=True)
    if args.rebuild_scene:
        marker, elapsed, rebuilt, status = require("rebuild-scene", path_arg(assembly), timeout=300).split()
        if marker != "rebuild" or rebuilt not in ("0", "1"):
            raise RuntimeError("Invalid rebuild response.")
        report["rebuild"] = {"ms": float(elapsed), "completed": rebuilt == "1", "hresult": status}
        (output / "viewport.json").write_text(json.dumps(report, indent=2) + "\n")
