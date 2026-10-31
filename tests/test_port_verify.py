"""Regression tests for the packaging verification engine.

These tests exercise the pure-Python helpers that the CI validation suite relies
on: the .deb reader, the Mach-O metadata sniffing used for the desktop-native
asset audit, producer-manifest hash extraction and contents comparison.

They do not need macOS/Xcode; they run on any Python 3 with the standard library
and are executed by `python3 -m unittest discover -s tests -v` in both
package-rootless.yml and test-port.yml.
"""
import io
import json
import struct
import tarfile
import tempfile
import unittest
from pathlib import Path

from packaging.verify import deb_reader, port_verify


def macho_bytes(platform=2, minos=(15, 0, 0), cpu=0x0100000C, filetype=2):
    """Build a minimal thin 64-bit little-endian Mach-O with LC_BUILD_VERSION."""
    min_version = (minos[0] << 16) | (minos[1] << 8) | minos[2]
    sdk = (18 << 16) | (0 << 8) | 0
    command = struct.pack("<6I", 0x32, 24, platform, min_version, sdk, 0)
    header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, filetype, 1, len(command), 0, 0)
    return header + command


def ar_member(name, data):
    header = (name + "/").ljust(16).encode("ascii")
    header += b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6)
    header += b"100644".ljust(8) + str(len(data)).ljust(10).encode("ascii") + b"`\n"
    assert len(header) == 60
    body = header + data
    if len(data) % 2:
        body += b"\n"
    return body


def tar_xz(entries):
    """entries: list of (path, bytes, mode); directories inferred."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as handle:
        for path, data, mode in entries:
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = mode
            handle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_deb(control_text, maintainer_scripts=None, data_files=None):
    control_entries = [("control", control_text.encode(), 0o644)]
    for name, text in (maintainer_scripts or {}).items():
        control_entries.append((name, text.encode(), 0o755))
    data_entries = []
    for path, data, mode in (data_files or []):
        data_entries.append((path, data, mode))
    deb = b"!<arch>\n"
    deb += ar_member("debian-binary", b"2.0\n")
    deb += ar_member("control.tar.xz", tar_xz(control_entries))
    deb += ar_member("data.tar.xz", tar_xz(data_entries))
    return deb


class MachoInfoTest(unittest.TestCase):
    def test_ios_thin_binary(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "node"
            path.write_bytes(macho_bytes(platform=2, minos=(15, 0, 0)))
            info = port_verify._macho_info(path)
            self.assertIsNotNone(info)
            self.assertEqual(info["platform"], "iOS")
            self.assertEqual(info["minos"], "15.0.0")
            self.assertEqual(info["arch"], hex(0x0100000C))

    def test_macos_native_asset_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pty.node"
            path.write_bytes(macho_bytes(platform=1, minos=(14, 0, 0), filetype=8))
            info = port_verify._macho_info(path)
            self.assertIsNotNone(info)
            self.assertEqual(info["platform"], "macOS")

    def test_non_macho_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "data.bin"
            path.write_bytes(b"not a mach-o binary at all" * 4)
            self.assertIsNone(port_verify._macho_info(path))

    def test_version_tuple_normalisation(self):
        self.assertEqual(port_verify._version_tuple("15.0"), (15,))
        self.assertEqual(port_verify._version_tuple("16.1.1"), (16, 1, 1))
        self.assertEqual(port_verify._version_tuple((16, 1, 1)), (16, 1, 1))


class DebReaderTest(unittest.TestCase):
    def test_parse_control_and_extract(self):
        control = (
            "Package: opencode\n"
            "Version: 2.2.5-1\n"
            "Architecture: iphoneos-arm64\n"
            "Description: test package\n"
            " continuation line one\n"
            " continuation line two\n"
        )
        data = [("var/jb/usr/bin/opencode", b"#!/bin/sh\nexit 0\n", 0o755)]
        with tempfile.TemporaryDirectory() as td:
            deb_path = Path(td) / "test.deb"
            deb_path.write_bytes(
                build_deb(control, {"postinst": "#!/bin/sh\nset -e\nexit 0\n"}, data)
            )
            package = deb_reader.DebPackage(deb_path)
            fields = package.parse_control()
            self.assertEqual(fields["Package"], "opencode")
            self.assertIn("continuation line one", fields["Description"])
            entries = package.data_entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["path"], "var/jb/usr/bin/opencode")
            self.assertEqual(entries[0]["mode"], 0o755)
            self.assertTrue(entries[0]["sha256"])
            control_files = package.control_files()
            self.assertIn("postinst", control_files)
            self.assertEqual(control_files["postinst"]["mode"], 0o755)

    def test_rejects_unsafe_path(self):
        with tempfile.TemporaryDirectory() as td:
            deb_path = Path(td) / "evil.deb"
            deb_path.write_bytes(
                build_deb("Package: x\n", {}, [("../escape", b"data", 0o644)])
            )
            package = deb_reader.DebPackage(deb_path)
            with self.assertRaises(deb_reader.DebError):
                package.data_entries()

    def test_rejects_non_deb(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "not-a.deb"
            path.write_bytes(b"hello world")
            with self.assertRaises(deb_reader.DebError):
                deb_reader.DebPackage(path)

    def test_parse_sha256sums(self):
        digest = "a" * 64
        parsed = deb_reader.parse_sha256sums(f"{digest}  OpenCode-iOS-rootless.deb\n")
        self.assertEqual(parsed, {"OpenCode-iOS-rootless.deb": digest})


class ManifestHashTest(unittest.TestCase):
    def test_collects_producer_bundle_manifest_entries(self):
        manifest = {
            "bundle": {
                "opencode_mjs": {"path": "opencode.mjs", "bytes": 10, "sha256": "a" * 64},
                "assets": {
                    "files": [
                        {"path": "app-archive.bin", "bytes": 3, "sha256": "b" * 64},
                        {"path": "nested/x.wasm", "bytes": 4, "sha256": "c" * 64},
                    ]
                },
            }
        }
        entries = dict(port_verify._collect_hash_entries(manifest))
        self.assertEqual(entries["opencode.mjs"], "a" * 64)
        self.assertEqual(entries["app-archive.bin"], "b" * 64)
        self.assertEqual(entries["nested/x.wasm"], "c" * 64)

    def test_collects_runtime_manifest_binary_hash(self):
        manifest = {"binary": {"file": "node", "sha256": "d" * 64}}
        entries = dict(port_verify._collect_hash_entries(manifest))
        self.assertEqual(entries["node"], "d" * 64)


class CompareTreeTest(unittest.TestCase):
    def test_debian_entries_are_ignored(self):
        expected = [
            {"path": "DEBIAN", "type": "dir", "mode": 0o755, "size": 0},
            {"path": "DEBIAN/control", "type": "file", "mode": 0o644, "size": 5,
             "sha256": "e" * 64},
            {"path": "var/jb/usr/bin/opencode", "type": "file", "mode": 0o755,
             "size": 2, "sha256": "f" * 64},
        ]
        actual = [
            {"path": "var/jb/usr/bin/opencode", "type": "file", "mode": 0o755,
             "size": 2, "sha256": "f" * 64},
        ]
        missing, extra, mismatched = port_verify._compare_tree(expected, actual)
        self.assertEqual(missing, [])
        self.assertEqual(extra, [])
        self.assertEqual(mismatched, [])

    def test_detects_hash_and_mode_mismatch(self):
        expected = [
            {"path": "var/jb/usr/lib/opencode/cli/opencode.mjs", "type": "file",
             "mode": 0o644, "size": 2, "sha256": "1" * 64},
        ]
        actual = [
            {"path": "var/jb/usr/lib/opencode/cli/opencode.mjs", "type": "file",
             "mode": 0o600, "size": 2, "sha256": "2" * 64},
        ]
        _, _, mismatched = port_verify._compare_tree(expected, actual)
        self.assertEqual(len(mismatched), 2)


class CheckSummaryTest(unittest.TestCase):
    def test_summary_marks_ci_fail_on_any_failure(self):
        checks = [
            {"id": "a", "section": "x", "title": "a", "status": "PASS", "evidence": ""},
            {"id": "b", "section": "x", "title": "b", "status": "SKIP", "evidence": ""},
        ]
        summary = port_verify.summarize_checks(checks)
        self.assertEqual(summary["ci_status"], "PASS")
        self.assertEqual(summary["skipped"], 1)
        checks.append(
            {"id": "c", "section": "x", "title": "c", "status": "FAIL", "evidence": ""}
        )
        self.assertEqual(port_verify.summarize_checks(checks)["ci_status"], "FAIL")


class CapabilityEnabledTest(unittest.TestCase):
    def test_enabled_forms(self):
        self.assertTrue(port_verify._capability_enabled("enabled: WebAssembly supported"))
        self.assertTrue(port_verify._capability_enabled("Enabled: default V8 JIT"))
        self.assertTrue(port_verify._capability_enabled("enabled"))
        self.assertTrue(port_verify._capability_enabled(True))

    def test_disabled_forms(self):
        self.assertFalse(port_verify._capability_enabled("disabled: no wasm"))
        self.assertFalse(port_verify._capability_enabled("not enabled"))
        self.assertFalse(port_verify._capability_enabled(False))
        self.assertFalse(port_verify._capability_enabled(None))
        self.assertFalse(port_verify._capability_enabled(""))

    def test_v3_style_explanation_mentioning_jitless_is_enabled(self):
        # Producer evidence text may mention the removed flag; the declared state
        # segment ("enabled:") is what matters.
        value = (
            "enabled: default V8 JIT (the build no longer passes "
            "--v8-options=--jitless). Device-verified on the target iPhone."
        )
        self.assertTrue(port_verify._capability_enabled(value))


class RuntimeBuildProfileTest(unittest.TestCase):
    GOOD_FLAGS = [
        "--dest-os=ios", "--dest-cpu=arm64", "--with-intl=full-icu",
    ]
    GOOD_POLICY = {
        "intl": {"mode": "full-icu", "icu_version": "75"},
        "webassembly": (
            "enabled: patches/nodejs-mobile/0003 restores upstream "
            "v8_enable_webassembly; Node fetch()/undici instantiates a wasm llhttp "
            "parser (the earlier no-wasm runtime died with 'ReferenceError: "
            "WebAssembly is not defined' on device)."
        ),
        "v8_jit": (
            "enabled: default V8 JIT (the build no longer passes "
            "--v8-options=--jitless). Device-verified with the 2-key entitlements."
        ),
    }

    WX_PATCH = "patches/nodejs-mobile/0004-ios-jit-write-protect.patch"
    GOOD_PATCHES = [
        {"file": "patches/nodejs-mobile/0001-ios-build-fixes.patch", "sha256": "a" * 64},
        {"file": WX_PATCH, "sha256": "b" * 64},
    ]

    def _run_profile_check(self, configure_flags=None, runtime_policy="default",
                           patches="default"):
        if configure_flags is None:
            configure_flags = list(self.GOOD_FLAGS)
        if runtime_policy == "default":
            runtime_policy = dict(self.GOOD_POLICY)
        if patches == "default":
            patches = list(self.GOOD_PATCHES)
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "var/jb/usr/lib/opencode/runtime"
            runtime.mkdir(parents=True)
            manifest = {"build": {"configure_flags": configure_flags}}
            if runtime_policy is not None:
                manifest["runtime_policy"] = runtime_policy
            if patches is not None:
                manifest["source"] = {"patches": patches}
            (runtime / "runtime-manifest.json").write_text(json.dumps(manifest))
            checks = []
            ctx = {"metrics": {}}
            port_verify._check_runtime_profile(checks, ctx, td)
            return checks

    def test_accepts_full_icu_wasm_jit_profile(self):
        checks = self._run_profile_check()
        self.assertEqual(checks[0]["status"], "PASS")
        self.assertIn("WebAssembly enabled", checks[0]["evidence"])
        self.assertIn("W^X patch (0004) declared", checks[0]["evidence"])

    def test_rejects_jit_runtime_without_wx_patch(self):
        checks = self._run_profile_check(
            patches=[{"file": "patches/nodejs-mobile/0001-ios-build-fixes.patch"}]
        )
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("W^X patch", checks[0]["evidence"])

    def test_without_patch_list_is_tolerated_but_unverified(self):
        checks = self._run_profile_check(patches=None)
        self.assertEqual(checks[0]["status"], "PASS")
        self.assertIn("unverified", checks[0]["evidence"])

    def test_rejects_with_intl_none(self):
        checks = self._run_profile_check([
            "--dest-os=ios", "--dest-cpu=arm64", "--with-intl=none",
        ])
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("with-intl=none", checks[0]["evidence"])

    def test_rejects_jitless_flag(self):
        checks = self._run_profile_check(self.GOOD_FLAGS + ["--v8-options=--jitless"])
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("jitless", checks[0]["evidence"])

    def test_rejects_disabled_webassembly(self):
        policy = dict(self.GOOD_POLICY)
        policy["webassembly"] = "disabled: jitless build has no wasm"
        checks = self._run_profile_check(runtime_policy=policy)
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("WebAssembly must be enabled", checks[0]["evidence"])

    def test_rejects_missing_webassembly_declaration(self):
        policy = {
            "intl": {"mode": "full-icu", "icu_version": "75"},
            "v8_jit": "enabled: default V8 JIT",
        }
        checks = self._run_profile_check(runtime_policy=policy)
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("does not declare runtime_policy.webassembly", checks[0]["evidence"])

    def test_skips_without_configure_flags(self):
        checks = self._run_profile_check(configure_flags=[])
        self.assertEqual(checks[0]["status"], "SKIP")


class VerifyCliTest(unittest.TestCase):
    def test_verify_mode_is_accepted_by_the_cli(self):
        parser = port_verify.build_parser()
        args = parser.parse_args([
            "verify", "--deb", "x.deb", "--mode", "verify", "--out-dir", "out",
        ])
        self.assertEqual(args.mode, "verify")


class ReportDeviceStatusTest(unittest.TestCase):
    def test_device_status_is_never_passed(self):
        self.assertEqual(port_verify.DEVICE_STATUS, "UNVERIFIED ON DEVICE")
        for test in port_verify.DEVICE_TESTS:
            self.assertNotIn("status", test)
        summary = port_verify.summarize_checks([])
        self.assertEqual(summary["device_status"], "UNVERIFIED ON DEVICE")


if __name__ == "__main__":
    unittest.main()
