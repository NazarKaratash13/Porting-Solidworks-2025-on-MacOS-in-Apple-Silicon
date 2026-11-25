"""Best-effort macOS memory pressure admission control, not a hard RSS quota."""
from contextlib import contextmanager
import re
import subprocess
import sys
import threading
import time


def pressure_free_percent():
    if sys.platform != 'darwin': return None
    try:
        result = subprocess.run(['/usr/bin/memory_pressure', '-Q'], capture_output=True,
                                text=True, timeout=2, check=True)
        match = re.search(r'System-wide memory free percentage:\s*(\d+)%', result.stdout)
        return int(match[1]) if match else None
    except (OSError, subprocess.SubprocessError):
        return None


class PressureGate:
    def __init__(self, threshold=15, recover=25, interval=2):
        self.threshold, self.recover, self.interval = threshold, recover, interval
        self.condition = threading.Condition()
        self.active = 0
        self.last = float('-inf')
        self.reduced = False

    def refresh(self):
        now = time.monotonic()
        if now - self.last >= self.interval:
            free = pressure_free_percent()
            if free is not None:
                if free <= self.threshold: self.reduced = True
                elif free >= self.recover: self.reduced = False
            self.last = now

    @contextmanager
    def admit(self):
        with self.condition:
            while True:
                self.refresh()
                if not self.reduced or not self.active: break
                self.condition.wait(timeout=self.interval)
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()
