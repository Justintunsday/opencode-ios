import os
import struct
import tempfile
import unittest
from pathlib import Path
from scripts.check_macho import MH_DYLIB, MH_EXECUTE, audit


def vers(major, minor, patch):
    return major << 16 | minor << 8 | patch


def binary(platform=2, minos=vers(16, 0, 0), cpu=0x0100000c, filetype=MH_EXECUTE):
    cmd = struct.pack("<6I", 0x32, 24, platform, minos, vers(18, 0, 0), 0)
    hdr = struct.pack("<8I", 0xFEEDFACF, cpu, 0, filetype, 1, len(cmd), 0, 0)
    return hdr + cmd


class MachoTest(unittest.TestCase):
    def check_bytes(self, value, filetypes=(MH_EXECUTE,)):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "binary"
            p.write_bytes(value)
            return audit(p, filetypes=filetypes)

    def test_ios(self):
        self.assertEqual(self.check_bytes(binary()), (16, 0, 0))

    def test_ios_dylib(self):
        self.assertEqual(self.check_bytes(binary(filetype=MH_DYLIB), (MH_DYLIB,)), (16, 0, 0))

    def test_reject_executable_when_dylib_expected(self):
        with self.assertRaisesRegex(ValueError, "file type"):
            self.check_bytes(binary(), (MH_DYLIB,))

    def test_reject_macos(self):
        with self.assertRaisesRegex(ValueError, "platform"):
            self.check_bytes(binary(platform=1))

    def test_reject_wrong_arch(self):
        with self.assertRaisesRegex(ValueError, "arm64"):
            self.check_bytes(binary(cpu=0x01000007))

    def test_reject_newer_ios(self):
        with self.assertRaisesRegex(ValueError, "newer"):
            self.check_bytes(binary(minos=vers(17, 0, 0)))

    def test_reject_truncated(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.check_bytes(binary()[:25])


if __name__ == "__main__":
    unittest.main()
