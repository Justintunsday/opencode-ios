"""Regression tests for the packaging verification engine.

These tests exercise the pure-Python helpers that the CI validation suite relies
on: the .deb reader, the Mach-O metadata sniffing used for the desktop-native
asset audit, producer-manifest hash extraction and contents comparison.

They do not need macOS/Xcode; they run on any Python 3 with the standard library
and are executed by `python3 -m unittest discover -s tests -v` in both
package-rootless.yml and test-port.yml.
"""
import argparse
import io
import json
import re
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
                           patches="default", variant=None):
        if configure_flags is None:
            configure_flags = list(self.GOOD_FLAGS)
        if runtime_policy == "default":
            runtime_policy = dict(self.GOOD_POLICY)
        if patches == "default":
            patches = list(self.GOOD_PATCHES)
        if variant is None:
            variant = port_verify.VARIANT_NODE22
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
            port_verify._check_runtime_profile(checks, ctx, td, variant)
            return checks

    def test_accepts_full_icu_wasm_jit_profile(self):
        checks = self._run_profile_check()
        self.assertEqual(checks[0]["status"], "PASS")
        self.assertIn("WebAssembly enabled", checks[0]["evidence"])
        self.assertIn("W^X patch declared", checks[0]["evidence"])

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

    def test_accepts_v5_no_map_jit_wx_patch(self):
        checks = self._run_profile_check(patches=[
            {"file": "patches/nodejs-mobile/0004-ios-jit-write-protect.patch"},
            {"file": "patches/nodejs-mobile/0005-no-map-jit-on-ios.patch"},
        ])
        self.assertEqual(checks[0]["status"], "PASS")
        self.assertIn("W^X patch declared", checks[0]["evidence"])

    def test_accepts_no_map_jit_patch_alone(self):
        checks = self._run_profile_check(patches=[
            {"file": "patches/nodejs-mobile/0005-no-map-jit-on-ios.patch"},
        ])
        self.assertEqual(checks[0]["status"], "PASS")

    def test_node22_requires_configure_flags(self):
        checks = self._run_profile_check(configure_flags=[])
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("configure_flags", checks[0]["evidence"])

    def test_node18_accepts_profile_without_configure_flags(self):
        policy = {
            "intl": {"mode": "full-icu"},
            "webassembly": "enabled: V8 WebAssembly compiled in",
            "v8_jit": "enabled: JIT compiled in (V8 10.2)",
        }
        checks = self._run_profile_check(
            configure_flags=[],
            runtime_policy=policy,
            patches=[{"file": "patches/nodejs-mobile18/0001-x.patch"}],
            variant=port_verify.VARIANT_NODE18,
        )
        self.assertEqual(checks[0]["status"], "PASS")
        self.assertIn("Node 18 V8 10.2 memory model", checks[0]["evidence"])
        self.assertIn("variant=node18", checks[0]["evidence"])

    def test_node18_does_not_require_node22_wx_patch(self):
        checks = self._run_profile_check(
            patches=[{"file": "patches/nodejs-mobile18/0001-x.patch"}],
            variant=port_verify.VARIANT_NODE18,
        )
        self.assertEqual(checks[0]["status"], "PASS")

    def test_node18_rejects_jitless_configuration(self):
        checks = self._run_profile_check(
            configure_flags=self.GOOD_FLAGS + ["--v8-options=--jitless"],
            variant=port_verify.VARIANT_NODE18,
        )
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("jitless", checks[0]["evidence"])

    def test_node18_rejects_missing_wasm_declaration(self):
        policy = {
            "intl": {"mode": "full-icu", "icu_version": "74.2"},
            "v8_jit": "enabled: JIT",
        }
        checks = self._run_profile_check(
            runtime_policy=policy, variant=port_verify.VARIANT_NODE18
        )
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("does not declare runtime_policy.webassembly", checks[0]["evidence"])

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

    def test_node22_without_configure_flags_fails(self):
        checks = self._run_profile_check(configure_flags=[])
        self.assertEqual(checks[0]["status"], "FAIL")


class JitShimTest(unittest.TestCase):
    def _make_tree(self, td, shim_bytes):
        root = Path(td)
        runtime = root / "var/jb/usr/lib/opencode/runtime"
        runtime.mkdir(parents=True)
        if shim_bytes is not None:
            (runtime / "libjitshim.dylib").write_bytes(shim_bytes)
        launcher = root / "var/jb/usr/bin"
        launcher.mkdir(parents=True)
        (launcher / "opencode").write_text(
            "#!/var/jb/bin/sh\n"
            "JITSHIM=\"$LIB/runtime/libjitshim.dylib\"\n"
            "if [ -f \"$JITSHIM\" ]; then\n"
            "    DYLD_INSERT_LIBRARIES=\"$JITSHIM\"\n"
            "    export DYLD_INSERT_LIBRARIES\n"
            "fi\n"
        )
        return root

    def test_valid_ios_dylib_shim_passes_static_checks(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_tree(td, macho_bytes(platform=2, minos=(14, 0, 0), filetype=6))
            checks = []
            ctx = {"metrics": {}}
            # skip_native -> native dylib audit skipped (SKIP), but static
            # Mach-O/filetype/arch and launcher-injection checks must pass.
            port_verify._check_optional_jitshim(checks, ctx, td, skip_native=True)
            self.assertEqual(checks[0]["status"], "SKIP")
            self.assertIn("native dylib audit skipped", checks[0]["evidence"])
            self.assertTrue(ctx["metrics"]["jitshim"]["included"])
            self.assertEqual(ctx["metrics"]["jitshim"]["platform"], "iOS")
            self.assertEqual(ctx["metrics"]["jitshim"]["filetype"], 6)

    def test_missing_shim_skips(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_tree(td, None)
            checks = []
            ctx = {"metrics": {}}
            port_verify._check_optional_jitshim(checks, ctx, td, skip_native=True)
            self.assertEqual(checks[0]["status"], "SKIP")
            self.assertFalse(ctx["metrics"]["jitshim"]["included"])

    def test_macos_dylib_shim_fails(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_tree(td, macho_bytes(platform=1, minos=(14, 0, 0), filetype=6))
            checks = []
            ctx = {"metrics": {}}
            port_verify._check_optional_jitshim(checks, ctx, td, skip_native=True)
            self.assertEqual(checks[0]["status"], "FAIL")
            self.assertIn("platform", checks[0]["evidence"])

    def test_shim_is_optional_package_data(self):
        self.assertIn("var/jb/usr/lib/opencode/runtime/libjitshim.dylib",
                      port_verify.OPTIONAL_DATA)
        self.assertIn("var/jb/usr/lib/opencode/runtime/libjitshim.dylib",
                      port_verify.EXECUTABLE_DATA)


class LauncherVariantTest(unittest.TestCase):
    REPO = Path(__file__).resolve().parent.parent

    def _launcher(self, name):
        return (self.REPO / "packaging/rootless/usr/bin" / name).read_text(
            encoding="utf-8"
        )

    def _code(self, text):
        return "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )

    def test_node22_launcher_passes_single_threaded(self):
        code = self._code(self._launcher("opencode"))
        self.assertIn("--single-threaded", code)
        self.assertIn("--experimental-sqlite", code)
        self.assertIn("--disable-warning=ExperimentalWarning", code)
        self.assertIn('"$@"', code)

    def test_node22_launcher_comment_explains_single_threaded(self):
        text = self._launcher("opencode")
        self.assertIn("device-verified", text.lower())
        self.assertIn("mprotect", text.lower())

    def test_node18_launcher_has_no_node22_only_flags_in_code(self):
        code = self._code(self._launcher("opencode-node18"))
        self.assertNotIn("--experimental-sqlite", code)
        self.assertNotIn("--disable-warning", code)
        self.assertNotIn("--use-system-ca", code)
        self.assertIn("--no-warnings", code)
        self.assertIn("TMPDIR", code)
        self.assertIn("OPENCODE_IOS_NODE_FLAGS", code)

    def test_launchers_share_tmpdir_and_assets_contract(self):
        for name in ("opencode", "opencode-node18"):
            code = self._code(self._launcher(name))
            self.assertIn("TMPDIR", code, name)
            self.assertIn("OPENCODE_NODE_ASSETS_DIR", code, name)
            self.assertIn("OPENCODE_IOS=1", code, name)
            self.assertIn("PATH=", code, name)


class VariantInferenceTest(unittest.TestCase):
    def test_normalize_variant(self):
        self.assertEqual(port_verify.normalize_variant("node18"), port_verify.VARIANT_NODE18)
        self.assertEqual(port_verify.normalize_variant("node18-fallback"), port_verify.VARIANT_NODE18)
        self.assertEqual(port_verify.normalize_variant("node22"), port_verify.VARIANT_NODE22)
        self.assertEqual(port_verify.normalize_variant(""), "")
        self.assertEqual(port_verify.normalize_variant("garbage"), "")

    def test_infer_variant_from_sources(self):
        self.assertEqual(
            port_verify.infer_variant({}, {"variant": "node18"}, None, ""),
            port_verify.VARIANT_NODE18,
        )
        self.assertEqual(
            port_verify.infer_variant({}, {"runtime_kind": "node22"}, None, ""),
            port_verify.VARIANT_NODE22,
        )

    def test_infer_variant_from_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "var/jb/usr/lib/opencode/runtime"
            runtime.mkdir(parents=True)
            (runtime / "runtime-manifest.json").write_text(
                json.dumps({"node_version": "18.20.4"})
            )
            ctx = {"extract_dir": Path(td)}
            self.assertEqual(
                port_verify.infer_variant(ctx, None, None, ""),
                port_verify.VARIANT_NODE18,
            )

    def test_explicit_variant_wins(self):
        self.assertEqual(
            port_verify.infer_variant({}, {"variant": "node18"}, None, "node22"),
            port_verify.VARIANT_NODE22,
        )

    def test_render_control_node18(self):
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "control.in"
            template.write_text(
                "Package: opencode\nVersion: @VERSION@\nMaintainer: @MAINTAINER@\n"
                "Installed-Size: @INSTALLED_SIZE@\nDescription: test\n"
                " running on Node.js @NODE_VERSION@.\n @VARIANT_DESCRIPTION@\n"
            )
            out = Path(td) / "control"
            rc = port_verify.cmd_render_control(
                argparse.Namespace(
                    template=str(template), out=str(out), version="2.2.5-1",
                    maintainer="Test <test@example.com>", installed_size=123,
                    variant="node18", node_version="",
                )
            )
            self.assertEqual(rc, 0)
            text = out.read_text()
            self.assertIn("Node.js 18.20.4", text)
            self.assertIn("sql.js", text)
            self.assertIn("Node 22", text)
            self.assertIsNone(re.search(r"@[A-Z_]+@", text))


    def test_render_control_node22_primary(self):
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "control.in"
            template.write_text(
                "Package: opencode\nVersion: @VERSION@\nMaintainer: @MAINTAINER@\n"
                "Installed-Size: @INSTALLED_SIZE@\nDescription: test\n"
                " running on Node.js @NODE_VERSION@.\n @VARIANT_DESCRIPTION@\n"
            )
            out = Path(td) / "control"
            rc = port_verify.cmd_render_control(
                argparse.Namespace(
                    template=str(template), out=str(out), version="2.2.5-1",
                    maintainer="Test <test@example.com>", installed_size=123,
                    variant="node22", node_version="",
                )
            )
            self.assertEqual(rc, 0)
            text = out.read_text()
            self.assertIn("Node.js 22.9.0", text)
            self.assertIn("primary", text)
            self.assertIn("--single-threaded", text)
            self.assertNotIn("experimental Node.js", text)


class VerifyCliTest(unittest.TestCase):
    def test_verify_mode_is_accepted_by_the_cli(self):
        parser = port_verify.build_parser()
        args = parser.parse_args([
            "verify", "--deb", "x.deb", "--mode", "verify", "--out-dir", "out",
        ])
        self.assertEqual(args.mode, "verify")

    def test_macho_info_subcommand_parses(self):
        parser = port_verify.build_parser()
        args = parser.parse_args([
            "macho-info", "--path", "x.dylib", "--expect-platform", "iOS",
        ])
        self.assertEqual(args.expect_platform, "iOS")


class ReportDeviceStatusTest(unittest.TestCase):
    def test_device_status_is_never_passed(self):
        self.assertEqual(port_verify.DEVICE_STATUS, "UNVERIFIED ON DEVICE")
        for test in port_verify.DEVICE_TESTS:
            self.assertNotIn("status", test)
        summary = port_verify.summarize_checks([])
        self.assertEqual(summary["device_status"], "UNVERIFIED ON DEVICE")


if __name__ == "__main__":
    unittest.main()
