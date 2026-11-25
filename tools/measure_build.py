#!/usr/bin/env python3
"""Sample the complete process tree RSS during a command (RSS can double-count shared pages)."""
import argparse
import json
import subprocess
import time
from pathlib import Path


def parse_processes(text):
    rows = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) != 3: continue
        try: pid, parent, rss = map(int, cols)
        except ValueError: continue
        rows[pid] = (parent, rss * 1024)
    return rows


def tree_rss(rows, root):
    children = {}
    for pid, (parent, _) in rows.items(): children.setdefault(parent, []).append(pid)
    seen, queue = set(), [root]
    while queue:
        pid = queue.pop()
        if pid in seen: continue
        seen.add(pid)
        queue.extend(children.get(pid, ()))
    return sum(rows[pid][1] for pid in seen if pid in rows), sum(pid in rows for pid in seen)


def snapshot():
    return parse_processes(subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss='], text=True))


def measure(command, interval):
    start = time.monotonic()
    proc = subprocess.Popen(command)
    peak = peak_count = samples = errors = 0
    try:
        while proc.poll() is None:
            try:
                rss, count = tree_rss(snapshot(), proc.pid)
                peak, peak_count = max(peak, rss), max(peak_count, count)
                samples += 1
            except (OSError, subprocess.SubprocessError): errors += 1
            time.sleep(interval)
    except BaseException:
        proc.terminate()
        proc.wait()
        raise
    return {'returncode': proc.wait(), 'elapsed_seconds': time.monotonic()-start,
            'peak_sampled_tree_rss_bytes': peak if samples else None,
            'peak_process_count': peak_count, 'sample_count': samples, 'sample_errors': errors,
            'interval_seconds': interval, 'warning': 'Sampled sum of RSS, not footprint; shared pages may be counted twice; short peaks may be missed.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--interval', type=float, default=.2)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command or a.interval <= 0: p.error('command and positive interval required')
    r = measure(command, a.interval)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(r, indent=2)+'\n')
    print(json.dumps(r, indent=2))
    return r['returncode'] if r['returncode'] >= 0 else 128-r['returncode']

if __name__ == '__main__': raise SystemExit(main())
