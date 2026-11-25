"""Exercises registry relocation without starting Wine or SOLIDWORKS."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


module_path = Path(__file__).parent / "solidworks-macos" / "assemble-local.py"
spec = importlib.util.spec_from_file_location("assemble_local", module_path)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class FontRelocationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.runtime = root / "Previous App.app" / "Wine"
        self.seed = root / "prefix-seed"
        self.fonts = self.seed / "drive_c/windows/Fonts"
        self.fonts.mkdir(parents=True)
        self.copy = root / "new-runtime"
        (self.copy / "share/wine/fonts").mkdir(parents=True)
        (self.copy / "share/wine/fonts/a.ttf").write_bytes(b"font bytes")
        self.previous = (
            '"Font"="Z:' + str(self.runtime / "share/wine/fonts/a.ttf").replace("/", "\\\\") + '"\n'
        ).encode()
        self.registry = self.seed / "system.reg"

    def test_relocates_font_once_without_touching_other_entries(self):
        other = b'"Setting"="another value"\n'
        self.registry.write_bytes(self.previous + other)
        self.assertEqual(package.internalize_fonts(self.seed, self.runtime, self.copy), 1)
        self.assertEqual(self.registry.read_bytes(), b'"Font"="swv3-a.ttf"\n' + other)
        self.assertEqual((self.fonts / "swv3-a.ttf").read_bytes(), b"font bytes")
        self.assertEqual(package.internalize_fonts(self.seed, self.runtime, self.copy), 0)

    def test_keeps_conflicting_file_and_registry_intact(self):
        self.registry.write_bytes(self.previous)
        occupied = self.fonts / "swv3-a.ttf"
        occupied.write_bytes(b"another font")
        with self.assertRaisesRegex(ValueError, "already exists"):
            package.internalize_fonts(self.seed, self.runtime, self.copy)
        self.assertEqual(self.registry.read_bytes(), self.previous)
        self.assertEqual(occupied.read_bytes(), b"another font")


if __name__ == "__main__":
    unittest.main()
