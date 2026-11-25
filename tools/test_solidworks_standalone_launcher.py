"""Exercise the bundle launcher with a fake Wine loader and a separate HOME."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == "darwin", "requires macOS lockf")
class StandaloneLauncherTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="sw2025-launcher-")
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        contents = root / "Test Bundle.app" / "Contents"
        self.launcher = contents / "MacOS" / "SOLIDWORKS"
        self.launcher.parent.mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name("solidworks-standalone-launcher.sh"), self.launcher)
        self.launcher.chmod(0o755)

        resources = contents / "Resources"
        wine = resources / "runtime/CrossOver/lib/wine/x86_64-unix/wine"
        wine.parent.mkdir(parents=True)
        wine.write_text(
            '#!/bin/bash\n'
            'printf "%s\\n" "$@" > "$WINEPREFIX/args"\n'
            ': > "$WINEPREFIX/loader-ready"\n'
            'if [[ "${SW_TEST_WAIT:-0}" == 1 ]]; then read -r -t 10; fi\n'
        )
        wine.chmod(0o755)
        template = resources / "prefix-template"
        program = template / "drive_c/Program Files/SOLIDWORKS/SLDWORKS.exe"
        program.parent.mkdir(parents=True)
        program.touch()
        (template / "system.reg").touch()

        home = root / "Test Home"
        self.environment = dict(os.environ, HOME=str(home), SW_TEST_WAIT="0")
        self.prefix = home / "Library/Application Support/SOLIDWORKS 2025/prefix"

    def launch(self):
        return subprocess.run([self.launcher], env=self.environment, capture_output=True, timeout=5)

    def test_first_launch_rejects_duplicate_and_allows_restart_after_exit(self):
        document = r"C:\file with spaces.SLDPRT"
        environment = dict(self.environment, SW_TEST_WAIT="1")
        with subprocess.Popen(
            [self.launcher, "-psn_0", document], env=environment, stdin=subprocess.PIPE,
        ) as first:
            deadline = time.monotonic() + 3
            ready = self.prefix / "loader-ready"
            args = self.prefix / "args"
            while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(ready.is_file())
            self.assertEqual(args.read_text().splitlines(), [
                r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe", document,
            ])
            self.assertTrue((self.prefix / ".sw-ready").is_file())
            self.assertEqual(self.launch().returncode, 75)
            self.assertIsNone(first.poll())
            first.communicate(input=b"continue\n", timeout=5)
            self.assertEqual(first.returncode, 0)
        self.assertEqual(self.launch().returncode, 0)

    def test_existing_prefix_without_marker_is_preserved(self):
        self.prefix.mkdir(parents=True)
        document = self.prefix / "existing.SLDPRT"
        document.write_bytes(b"existing document")

        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"no .sw-ready marker", result.stderr)
        self.assertEqual(document.read_bytes(), b"existing document")
        self.assertFalse((self.prefix / ".sw-ready").exists())

    def test_launch_does_not_prepare_prefix_under_an_existing_setup_lock(self):
        import fcntl

        self.prefix.parent.mkdir(parents=True)
        with (self.prefix.parent / "launch.lock").open("wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.launch()
            self.assertEqual(result.returncode, 75)
            self.assertIn(b"preparing another launch", result.stderr)
            self.assertFalse(self.prefix.exists())


if __name__ == "__main__":
    unittest.main()
