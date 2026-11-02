#!/usr/bin/env python3
"""OpenCode iOS port: contents manifests, .deb inspection and CI verification.

This module is the single source of truth for the checks that both
``scripts/package-ios.sh`` (build-time package report) and
``scripts/validate-port.sh`` (CI validation suite / verification report) run.
It only uses the Python standard library, so it works on the GitHub macOS
runners, on Linux and on the Windows development host.

Subcommands
-----------
manifest   Build a contents manifest (path/mode/size/sha256) of a staged tree.
sources    Build the provenance JSON (upstream pins + artifact file hashes).
extract    Safely extract a .deb with the pure-Python reader.
verify     Run the CI-runnable verification suite and write the reports.
fixture    Create synthetic placeholder inputs for the scripts self-test.

Every check gets a stable id, a section, a status (PASS/FAIL/SKIP) and
human-readable evidence. Device-only checks are never reported as passing:
they are listed separately with the status ``UNVERIFIED ON DEVICE``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from deb_reader import (  # noqa: E402
    DebError,
    DebPackage,
    parse_sha256sums,
    sha256_file,
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
DEVICE_BANNER = (
    "UNVERIFIED ON DEVICE — requires real iPhone SE 2 "
    "(iOS 16.1.1, Dopamine rootless)"
)
DEVICE_HEADING = "DEVICE TESTS: NOT PERFORMED (requires real iPhone)"
DEVICE_STATUS = "UNVERIFIED ON DEVICE"

EXPECTED_PACKAGE = "opencode"
EXPECTED_ARCH = "iphoneos-arm64"
EXPECTED_DEPENDS = "firmware (>= 15.0)"
EXPECTED_SECTION = "Development"
EXPECTED_PRIORITY = "optional"
EXPECTED_HOMEPAGE_PREFIX = "https://github.com/"

# Runtime variants: node22 v6 (mprotect W^X, device-verified with the mandatory
# --single-threaded launcher flag) is the primary shipping line; node18 is the
# documented alternative fallback (V8 10.2 memory model, sql.js sqlite shim);
# node26 is the EXPERIMENTAL Phase D line (real OpenTUI TUI via node:ffi).
VARIANT_NODE22 = "node22"
VARIANT_NODE18 = "node18"
VARIANT_NODE26 = "node26"
VARIANT_LABELS = {
    VARIANT_NODE22: "node22",
    VARIANT_NODE18: "node18",
    VARIANT_NODE26: "node26",
}
EXPECTED_RUNTIME_NODE_VERSION = {
    VARIANT_NODE22: "22.9.0",
    VARIANT_NODE18: "18.20.4",
    VARIANT_NODE26: "26.13.0",
}
RUNTIME_KIND = {
    VARIANT_NODE22: "node22",
    VARIANT_NODE18: "node18",
    VARIANT_NODE26: "node26",
}
# The experimental node26 build is clearly labelled (artifact, package report and
# control description) so it can never be confused with the stable node22 release.
EXPERIMENTAL_VARIANTS = {VARIANT_NODE26: True}
EXPERIMENTAL_RELEASE_LABELS = {
    VARIANT_NODE26: "v2.2.5-ios.5-node26test.1",
}
OPENTUI_REL_PATH = "var/jb/usr/lib/opencode/cli/assets/@opentui/core-ios-arm64/libopentui.dylib"
# iOS renderer execution model (device finding, iOS 16.1.1):
#  * the packaged /var/jb/usr/lib/opencode/cli/assets tree is the ONLY usable
#    runtime asset root — /var/mobile paths are refused by the file-system
#    sandbox for dylib mmap;
#  * dyld maps ldid-signed dylibs non-executable (calling a renderer function
#    SIGBUSes with __TEXT r--/rw-), so the shipped renderer must be
#    Apple `codesign`-signed (ad-hoc) while the node executable keeps the ldid
#    2-key signature.
NODE26_ASSET_ROOT = "/var/jb/usr/lib/opencode/cli/assets"
NODE26_RUNTIME_ASSETS_OVERRIDE = "OPENCODE_IOS_RUNTIME_ASSETS"
NODE26_ASSET_DYLIB_REL = "@opentui/core-ios-arm64/libopentui.dylib"
VARIANT_CONTROL_DESCRIPTION = {
    VARIANT_NODE22: (
        "This build ships the primary Node.js 22.9.0 runtime variant with the\n"
        " v6 mprotect-based W^X memory model (2-key entitlements; device-verified\n"
        " on the target iPhone with the launcher's mandatory --single-threaded\n"
        " flag). The Node 18 runtime is the alternative fallback variant."
    ),
    VARIANT_NODE18: (
        "This build ships the Node.js 18.20.4 fallback runtime (V8 10.2\n"
        " memory model, device-proven JIT/WebAssembly/full-ICU on the target\n"
        " iPhone) with the bundled sql.js WebAssembly sqlite shim; the primary\n"
        " variant is Node 22.9 (v6 mprotect W^X, --single-threaded launcher)."
    ),
    VARIANT_NODE26: (
        "EXPERIMENTAL Phase D build (v2.2.5-ios.5-node26test.1): Node.js 26.13\n"
        " runtime with node:ffi and the iPhoneOS OpenTUI renderer, so the real\n"
        " interactive TUI is expected to work (device verification pending).\n"
        " The launcher passes --single-threaded (mandatory on iOS mprotect W^X).\n"
        " The stable, device-verified variant remains Node 22.9 (v2.2.5-ios.5).\n"
        " Do not install this experimental build on a device you rely on."
    ),
}

REAL_NODE_MIN_BYTES = 1_000_000
REAL_MJS_MIN_BYTES = 50_000
MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_DEB_BYTES = 400 * 1024 * 1024

REQUIRED_DATA = {
    "var/jb/usr/bin/opencode": {"type": "file", "mode": 0o755},
    "var/jb/usr/lib/opencode/runtime/node": {"type": "file", "mode": 0o755},
    "var/jb/usr/lib/opencode/runtime/entitlements.xml": {"type": "file", "mode": 0o644},
    "var/jb/usr/lib/opencode/runtime/runtime-manifest.json": {"type": "file", "mode": 0o644},
    "var/jb/usr/lib/opencode/cli/opencode.mjs": {"type": "file", "mode": 0o644},
    "var/jb/usr/lib/opencode/cli/assets": {"type": "dir", "mode": 0o755},
    "var/jb/usr/share/doc/opencode/README.md": {"type": "file", "mode": 0o644},
    "var/jb/usr/share/doc/opencode/LICENSE": {"type": "file", "mode": 0o644},
    "var/jb/usr/share/doc/opencode/copyright": {"type": "file", "mode": 0o644},
    "var/jb/usr/share/doc/opencode/VERIFICATION.md": {"type": "file", "mode": 0o644},
    "var/jb/usr/share/doc/opencode/INSTALL.md": {"type": "file", "mode": 0o644},
}
OPTIONAL_DATA = {
    "var/jb/usr/lib/opencode/cli/bundle-manifest.json": {"type": "file", "mode": 0o644},
    "var/jb/usr/share/doc/opencode/device-smoke.sh": {"type": "file", "mode": 0o755},
    "var/jb/usr/share/doc/opencode/KNOWN_LIMITATIONS.md": {"type": "file", "mode": 0o644},
    "var/jb/usr/bin/rg": {"type": "file", "mode": 0o755},
    # Optional jailbreak JIT interposer (ios-jit-shim artifact). Injected by the
    # launcher through DYLD_INSERT_LIBRARIES only when shipped.
    "var/jb/usr/lib/opencode/runtime/libjitshim.dylib": {"type": "file", "mode": 0o755},
    # Optional OpenTUI iOS renderer for the experimental node26 variant (loaded
    # through node:ffi from this /var/jb path; dlopen sandbox requires /var/jb).
    "var/jb/usr/lib/opencode/cli/assets/@opentui/core-ios-arm64/libopentui.dylib":
        {"type": "file", "mode": 0o755},
}
ALLOWED_DATA_PREFIXES = (
    "var/jb/usr/bin/",
    "var/jb/usr/lib/opencode/",
    "var/jb/usr/share/doc/opencode/",
)
EXECUTABLE_DATA = {
    "var/jb/usr/bin/opencode",
    "var/jb/usr/bin/rg",
    "var/jb/usr/share/doc/opencode/device-smoke.sh",
    "var/jb/usr/lib/opencode/runtime/node",
    "var/jb/usr/lib/opencode/runtime/libjitshim.dylib",
    "var/jb/usr/lib/opencode/cli/assets/@opentui/core-ios-arm64/libopentui.dylib",
}

CONTROL_REQUIRED_FIELDS = (
    "Package",
    "Version",
    "Architecture",
    "Maintainer",
    "Installed-Size",
    "Section",
    "Priority",
    "Depends",
    "Homepage",
    "Description",
)
MAINTAINER_SCRIPTS = ("postinst", "prerm", "postrm")

ALLOWED_DEP_PREFIXES = ("/usr/lib/", "/System/Library/", "/System/iOSSupport/")
FORBIDDEN_DEP_SUBSTRINGS = (
    "/opt/homebrew",
    "/usr/local/",
    "/Users/",
    "@rpath",
    "@loader_path",
    "@executable_path",
    ".framework/Versions/",
)
FORBIDDEN_FRAMEWORKS = (
    "AppKit.framework",
    "Carbon.framework",
    "Cocoa.framework",
    "ScriptingBridge.framework",
    "OSAKit.framework",
    "Automator.framework",
    "IOBluetooth.framework",
)
FORBIDDEN_PACKAGE_FILENAMES = (
    ".env",
    ".npmrc",
    ".netrc",
    "auth.json",
    "id_rsa",
    "id_ed25519",
)
JUNK_NAMES = (".DS_Store", "Thumbs.db", ".git", "node_modules", "__MACOSX")

# Built from fragments so this scanner does not flag itself when it scans the
# repository (the literal strings never appear in this file).
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile("gh" + r"p_[A-Za-z0-9]{36,}"),
    re.compile("github" + r"_pat_[A-Za-z0-9_]{30,}"),
    re.compile("A" + r"KIA[0-9A-Z]{16}"),
    re.compile("xox" + r"[abp]-[A-Za-z0-9-]{10,}"),
]

DEVICE_TESTS = [
    {
        "id": "device.install",
        "title": "Install the .deb rootless with dpkg",
        "commands": [
            "sha256sum -c SHA256SUMS",
            "sudo dpkg -i OpenCode-iOS-rootless.deb",
            "dpkg -s opencode",
        ],
        "expected": "dpkg reports status 'install ok installed'; no dependency errors.",
    },
    {
        "id": "device.version",
        "title": "CLI starts on the device and reports its version",
        "commands": ["opencode --version"],
        "expected": "Exit 0 and the upstream OpenCode version (2.2.5) is printed.",
    },
    {
        "id": "device.help",
        "title": "CLI help renders",
        "commands": ["opencode --help"],
        "expected": "Exit 0 and a usage/commands block is printed.",
    },
    {
        "id": "device.paths",
        "title": "iOS path defaults are under the jailbreak user home",
        "commands": ["opencode debug paths"],
        "expected": "Config/data paths under /var/mobile (e.g. ~/.config/opencode).",
    },
    {
        "id": "device.auth",
        "title": "Provider authentication works (no embedded keys)",
        "commands": ["opencode auth list", "opencode auth login"],
        "expected": "Login flow completes; credentials stored in the user's home only.",
    },
    {
        "id": "device.no-network",
        "title": "Offline CLI commands run without a provider",
        "commands": [
            "opencode --version",
            "opencode models",
            "opencode debug paths",
        ],
        "expected": "Offline commands exit 0 (Node 18 sql.js shim: `opencode session "
                    "list` also works and persists the database file; no SIGKILL/"
                    "SIGBUS).",
    },
    {
        "id": "device.sqlite",
        "title": "sqlite persistence works (Node 18 sql.js shim or Node 22 node:sqlite)",
        "commands": [
            "opencode session list",
            "ls -l \"$HOME/.local/share/opencode\"/*.db 2>/dev/null || true",
        ],
        "expected": "`session list` exits 0 and creates/persists the sqlite database "
                    "file. Node 18 uses the bundled sql.js WebAssembly shim (whole-file "
                    "persistence, no WAL; see KNOWN_LIMITATIONS.md).",
    },
    {
        "id": "device.jitless",
        "title": "Runtime provides WebAssembly + JIT with the 2-key entitlements",
        "commands": [
            "/var/jb/usr/lib/opencode/runtime/node -e "
            "\"console.log(typeof WebAssembly, process.config.variables.v8_enable_webassembly)\"",
            "/var/jb/usr/lib/opencode/runtime/node -e "
            "\"new WebAssembly.Module(Buffer.from('0061736d01000000','hex'));"
            "console.log('wasm-ok')\"",
        ],
        "expected": "typeof WebAssembly is 'object', v8_enable_webassembly=1, "
                    "'wasm-ok' prints (JIT/exec-memory works with the shipped 2-key "
                    "entitlements; a wasm-disabled runtime makes the CLI fail with "
                    "'ReferenceError: WebAssembly is not defined').",
    },
    {
        "id": "device.wasm",
        "title": "WebAssembly + fetch stack initialise (required by Node fetch/undici)",
        "commands": [
            "/var/jb/usr/lib/opencode/runtime/node -e "
            "\"console.log(typeof WebAssembly, typeof fetch)\"",
            "/var/jb/usr/lib/opencode/runtime/node -e "
            "\"new WebAssembly.Module(Buffer.from('0061736d01000000','hex'));"
            "console.log('wasm-ok')\"",
        ],
        "expected": "WebAssembly=object, fetch=function, 'wasm-ok' printed. Without "
                    "this, every CLI command fails with 'ReferenceError: WebAssembly "
                    "is not defined' (device-verified on the wasm-disabled build).",
    },
    {
        "id": "device.tui",
        "title": "Interactive TUI session in NewTerm 3 (node22 line REPL / node26 real TUI)",
        "commands": ["cd /var/mobile/Documents && opencode"],
        "expected": "node22 package: line-based REPL (full TUI unavailable). "
                    "Experimental node26 package: real OpenTUI TUI via node:ffi + "
                    "cli/assets/@opentui/core-ios-arm64/libopentui.dylib; the dylib "
                    "must load from /var/jb and the TUI must render.",
    },
    {
        "id": "device.node26-tui",
        "title": "Experimental node26 real TUI loads the OpenTUI dylib through node:ffi",
        "commands": [
            "cd /var/mobile/Documents && opencode   # real PTY: expect OpenTUI TUI, not line REPL",
            "ls -l /var/jb/usr/lib/opencode/cli/assets/@opentui/core-ios-arm64/libopentui.dylib",
            "opencode < /dev/null; echo rc=$?",
        ],
        "expected": "TUI renders in a real PTY; the renderer dylib is present under "
                    "/var/jb with mode 0755 and dlopens via node:ffi; non-TTY exits 1 "
                    "with clean usage guidance. UNVERIFIED ON DEVICE until the "
                    "maintainer runs the Phase D acceptance.",
    },
    {
        "id": "device.uninstall",
        "title": "Uninstall / purge leaves user data intact",
        "commands": ["sudo dpkg -r opencode", "ls ~/.config/opencode", "sudo dpkg -P opencode"],
        "expected": "Package files gone; config and sessions still present after purge.",
    },
    {
        "id": "device.ldid",
        "title": "Signature repair path if the runtime is killed",
        "commands": [
            "sudo ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.xml "
            "/var/jb/usr/lib/opencode/runtime/node",
            "opencode --version",
        ],
        "expected": "Re-signed runtime starts; see docs/INSTALL.md troubleshooting.",
    },
]


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------
def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(checks, check_id, section, title, status, evidence=""):
    assert status in ("PASS", "FAIL", "SKIP"), status
    checks.append(
        {
            "id": check_id,
            "section": section,
            "title": title,
            "status": status,
            "evidence": evidence,
        }
    )


def json_write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(obj, indent=2, sort_keys=False) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_text(path, limit=4 * 1024 * 1024):
    data = Path(path).read_bytes()
    if len(data) > limit:
        data = data[:limit]
    return data.decode("utf-8", "replace")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def mode_octal(mode):
    return f"{mode & 0o7777:04o}"


def truncate(text, limit=600):
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _parse_lock_file(lock_path):
    """Parse an UPSTREAM.lock KEY=VALUE file into a dict."""
    lock_path = Path(lock_path)
    values = {}
    if not lock_path.is_file():
        return values
    for line in read_text(lock_path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def read_lock(repo_root):
    """Parse <repo_root>/UPSTREAM.lock pins into a dict."""
    return _parse_lock_file(Path(repo_root) / "UPSTREAM.lock")


def expected_deb_version(repo_root):
    lock = read_lock(repo_root)
    version = lock.get("OPENCODE_VERSION", "").strip()
    if not version:
        return ""
    return f"{version}-1"


def environment_info(extra=None):
    info = {
        "runner_os": os.environ.get("RUNNER_OS", platform.system()),
        "runner_arch": os.environ.get("RUNNER_ARCH", platform.machine()),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "generated_at": utc_now(),
        "github_repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "github_server_url": os.environ.get("GITHUB_SERVER_URL", ""),
    }
    if extra:
        info.update(extra)
    return info


def run_command(cmd, cwd=None, timeout=300):
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, "", f"command timed out after {timeout}s: {' '.join(cmd)}"


def tree_files(root):
    root = Path(root)
    result = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        result.append(rel)
    return result


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------
def build_manifest(root, label=""):
    root = Path(root)
    files = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        entry = {
            "path": rel,
            "mode": st.st_mode & 0o7777,
            "mode_octal": mode_octal(st.st_mode),
            "size": 0,
        }
        if path.is_symlink():
            entry["type"] = "symlink"
            entry["linkname"] = os.readlink(path)
        elif path.is_dir():
            entry["type"] = "dir"
        elif path.is_file():
            entry["type"] = "file"
            entry["size"] = st.st_size
            entry["sha256"] = sha256_file(path)
            total_bytes += st.st_size
        else:
            entry["type"] = "other"
            entry["size"] = st.st_size
        files.append(entry)
    return {
        "schema": 1,
        "kind": "contents-manifest",
        "generated_at": utc_now(),
        "label": label or root.name,
        "root": str(root),
        "totals": {
            "entries": len(files),
            "files": sum(1 for f in files if f["type"] == "file"),
            "bytes": total_bytes,
        },
        "files": files,
    }


def cmd_manifest(args):
    manifest = build_manifest(args.root, args.label)
    json_write(args.out, manifest)
    print(
        f"manifest: {manifest['totals']['files']} files, "
        f"{manifest['totals']['bytes']} bytes -> {args.out}"
    )
    return 0


# --------------------------------------------------------------------------
# Sources / provenance
# --------------------------------------------------------------------------
def artifact_summary(directory, artifact_name):
    directory = Path(directory)
    if not directory.is_dir():
        raise SystemExit(f"sources: artifact directory not found: {directory}")
    files = []
    total_bytes = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        size = path.stat().st_size
        files.append({"path": rel, "size": size, "sha256": sha256_file(path)})
        total_bytes += size
    sums_info = {"present": False}
    sums_candidates = sorted(directory.rglob("SHA256SUMS"))
    if sums_candidates:
        sums_path = sums_candidates[0]
        base = sums_path.parent
        try:
            entries = parse_sha256sums(read_text(sums_path))
        except DebError as exc:
            sums_info = {"present": True, "verified": False, "error": str(exc)}
        else:
            missing = [p for p in entries if not (base / p).is_file()]
            mismatched = [
                p for p in entries
                if (base / p).is_file() and sha256_file(base / p) != entries[p]
            ]
            sums_info = {
                "present": True,
                "path": sums_path.relative_to(directory).as_posix(),
                "entries": len(entries),
                "missing": missing,
                "mismatched": mismatched,
                "verified": not missing and not mismatched,
            }
    return {
        "artifact": artifact_name,
        "directory": str(directory),
        "files": files,
        "totals": {"files": len(files), "bytes": total_bytes},
        "sha256sums": sums_info,
    }


def cmd_sources(args):
    variant = normalize_variant(getattr(args, "variant", "")) or VARIANT_NODE22
    variant_label = VARIANT_LABELS[variant]
    runtime_artifact = {
        VARIANT_NODE22: "ios-node-runtime",
        VARIANT_NODE18: "ios-node18-runtime",
        VARIANT_NODE26: "ios-node26-runtime",
    }.get(variant, "ios-node-runtime")
    if getattr(args, "runtime_artifact_name", ""):
        runtime_artifact = args.runtime_artifact_name
    runtime = artifact_summary(args.runtime_dir, runtime_artifact)
    runtime.update(
        run_id=args.runtime_run_id or "",
        run_url=args.runtime_run_url or "",
    )
    opencode = artifact_summary(args.opencode_dir, "opencode-cli-node-ios")
    opencode.update(
        run_id=args.opencode_run_id or "",
        run_url=args.opencode_run_url or "",
    )
    ripgrep = {
        "artifact": "ios-ripgrep",
        "included": False,
        "reason": "optional ios-ripgrep artifact not available; component skipped",
    }
    if args.ripgrep_dir:
        ripgrep = artifact_summary(args.ripgrep_dir, "ios-ripgrep")
        ripgrep.update(
            included=True,
            optional=True,
            run_id=args.ripgrep_run_id or "",
            run_url=args.ripgrep_run_url or "",
        )
    jitshim = {
        "artifact": "ios-jit-shim",
        "included": False,
        "reason": "optional ios-jit-shim artifact not available; component skipped",
    }
    if getattr(args, "jitshim_dir", ""):
        jitshim = artifact_summary(args.jitshim_dir, "ios-jit-shim")
        jitshim.update(
            included=True,
            optional=True,
            run_id=getattr(args, "jitshim_run_id", "") or "",
            run_url=getattr(args, "jitshim_run_url", "") or "",
        )
    opentui = {
        "artifact": "opentui-ios-renderer",
        "included": False,
        "reason": "not part of the node22/node18 variants (line REPL instead of TUI)",
    }
    if variant == VARIANT_NODE26:
        expected_sha = getattr(args, "opentui_sha256", "") or ""
        rel_path = getattr(args, "opentui_relative_path", "") or OPENTUI_REL_PATH
        opentui = {
            "artifact": "opentui-ios-renderer",
            "included": True,
            "optional": False,
            "path": rel_path,
            "expected_sha256": expected_sha,
            "run_id": getattr(args, "opentui_run_id", "") or "",
            "run_url": getattr(args, "opentui_run_url", "") or "",
        }
        opentui_dir = getattr(args, "opentui_dir", "") or ""
        if opentui_dir:
            summary = artifact_summary(opentui_dir, "opentui-ios-renderer")
            opentui["files"] = summary.get("files", [])
            opentui["totals"] = summary.get("totals", {})
    lock = _parse_lock_file(args.lock)
    experimental = bool(EXPERIMENTAL_VARIANTS.get(variant))
    bootstrap_prep = bool(getattr(args, "allow_non_ffi_runtime", False))
    release_label = (
        getattr(args, "experimental_label", "") if experimental else ""
    ) or (EXPERIMENTAL_RELEASE_LABELS.get(variant) if experimental else "")
    sources = {
        "schema": 1,
        "kind": "package-sources",
        "generated_at": utc_now(),
        "self_test": bool(args.self_test),
        "variant": variant_label,
        "runtime_kind": RUNTIME_KIND[variant],
        "experimental": experimental,
        "bootstrap_prep": bootstrap_prep,
        "release_label": release_label,
        "expected_node_sha256": getattr(args, "expected_node_sha256", "") or "",
        "repository": args.repository or os.environ.get("GITHUB_REPOSITORY", ""),
        "commit": args.commit or "",
        "workflow": {
            "run_id": args.run_id or os.environ.get("GITHUB_RUN_ID", ""),
            "run_url": args.run_url or "",
        },
        "upstream": lock,
        "inputs": {
            "runtime": runtime,
            "opencode_cli": opencode,
            "ripgrep": ripgrep,
            "jitshim": jitshim,
            "opentui": opentui,
        },
    }
    json_write(args.out, sources)
    print(
        "sources: variant={}, runtime files={}, cli files={}, ripgrep={}, "
        "jitshim={}, opentui={} -> {}".format(
            variant_label,
            runtime["totals"]["files"],
            opencode["totals"]["files"],
            "included" if ripgrep.get("included") else "skipped",
            "included" if jitshim.get("included") else "skipped",
            "included" if opentui.get("included") else "skipped",
            args.out,
        )
    )
    return 0


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
def cmd_extract(args):
    deb = DebPackage(args.deb)
    dest = Path(args.dest)
    if dest.exists():
        shutil.rmtree(dest)
    entries = deb.extract_data(dest)
    extracted = {
        "schema": 1,
        "kind": "deb-extract",
        "generated_at": utc_now(),
        "deb": str(args.deb),
        "deb_sha256": sha256_file(args.deb),
        "deb_size": Path(args.deb).stat().st_size,
        "members": sorted(deb.members),
        "control_member": deb.control_member,
        "data_member": deb.data_member,
        "control": deb.parse_control(),
        "data_entries": entries,
        "totals": {
            "entries": len(entries),
            "bytes": sum(e["size"] for e in entries if e["type"] == "file"),
        },
    }
    json_write(args.out, extracted)
    print(f"extract: {len(entries)} entries -> {dest} (manifest {args.out})")
    return 0


# --------------------------------------------------------------------------
# Mach-O metadata probe (for optional component preflight checks)
# --------------------------------------------------------------------------
def cmd_macho_info(args):
    path = Path(args.path)
    if not path.is_file():
        print(json.dumps({"path": str(path), "is_macho": False,
                          "error": "not a file"}))
        return 1
    info = _macho_info(path)
    if info is None:
        print(json.dumps({"path": str(path), "is_macho": False,
                          "error": "not a Mach-O binary"}))
        return 1
    info = dict(info)
    info.update(path=str(path), is_macho=True)
    print(json.dumps(info, indent=2))
    problems = []
    if args.expect_platform and info.get("platform") != args.expect_platform:
        problems.append(
            f"platform {info.get('platform')!r} != expected {args.expect_platform!r}"
        )
    if args.expect_arch:
        expected_cpu = {"arm64": hex(0x0100000C), "arm64e": hex(0x0100000C)}.get(
            args.expect_arch.lower()
        )
        if expected_cpu and info.get("arch") != expected_cpu:
            problems.append(f"arch {info.get('arch')!r} != expected arm64")
    if problems:
        print("ERROR: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------
# Check helpers
# --------------------------------------------------------------------------
def _check_unittest(checks, repo_root, log_path):
    tests_dir = Path(repo_root) / "tests"
    if not tests_dir.is_dir():
        check(checks, "repo.unit-tests", "repository", "Bootstrap unit tests",
              "SKIP", f"no tests/ directory in {repo_root}")
        return
    rc, out, err = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=repo_root,
        timeout=300,
    )
    combined = (out or "") + (err or "")
    Path(log_path).write_text(combined, encoding="utf-8")
    tail = [line for line in combined.splitlines() if line.strip()][-6:]
    if rc == 0:
        check(checks, "repo.unit-tests", "repository",
              "Bootstrap unit tests (python -m unittest discover -s tests -v)",
              "PASS", "exit 0; " + truncate(" | ".join(tail), 500))
    else:
        check(checks, "repo.unit-tests", "repository",
              "Bootstrap unit tests (python -m unittest discover -s tests -v)",
              "FAIL", f"exit {rc}; " + truncate(" | ".join(tail), 800))


def _iter_repo_text_files(repo_root):
    rc, out, _ = run_command(["git", "-C", str(repo_root), "ls-files", "-z"])
    paths = []
    if rc == 0 and out:
        for raw in out.split("\0"):
            raw = raw.strip()
            if raw:
                paths.append(Path(repo_root) / raw)
    else:
        for path in Path(repo_root).rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root)
            if any(part in (".git", "node_modules", "dist", "build") for part in rel.parts):
                continue
            paths.append(path)
    for path in paths:
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 5 * 1024 * 1024:
                continue
            head = path.open("rb").read(8192)
        except OSError:
            continue
        if b"\0" in head:
            continue
        yield path


def _check_repo_checks(checks, repo_root, mode, out_dir):
    repo_root = Path(repo_root)
    if not (repo_root / ".git").exists() and not (repo_root / "README.md").exists():
        check(checks, "repo.checkout", "repository", "Repository checkout present",
              "SKIP", f"repository root not found: {repo_root}")
        return

    # ---- line endings -----------------------------------------------------
    crlf = []
    scanned = 0
    for path in _iter_repo_text_files(repo_root):
        scanned += 1
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\r\n" in data:
            crlf.append(path.relative_to(repo_root).as_posix())
    if crlf:
        check(checks, "repo.line-endings", "repository",
              "Text files use LF line endings (.gitattributes eol=lf)", "FAIL",
              f"{len(crlf)} file(s) contain CRLF: " + truncate(", ".join(crlf[:15]), 500))
    else:
        check(checks, "repo.line-endings", "repository",
              "Text files use LF line endings (.gitattributes eol=lf)", "PASS",
              f"{scanned} text files scanned; no CRLF found")

    # ---- shell syntax -----------------------------------------------------
    shell_targets = []
    for pattern in ("scripts/*.sh", "packaging/**/*.sh"):
        shell_targets.extend(sorted(repo_root.glob(pattern)))
    shell_targets.extend(
        path for path in (
            repo_root / "packaging/rootless/postinst",
            repo_root / "packaging/rootless/prerm",
            repo_root / "packaging/rootless/postrm",
            repo_root / "packaging/rootless/usr/bin/opencode",
            repo_root / "packaging/rootless/usr/bin/opencode-node18",
            repo_root / "packaging/rootless/usr/share/doc/opencode/device-smoke.sh",
        ) if path.is_file()
    )
    syntax_failures = []
    checked_scripts = []
    for path in sorted(set(shell_targets)):
        rel = path.relative_to(repo_root).as_posix()
        first_line = read_text(path, limit=200).splitlines()[0] if path.stat().st_size else ""
        interpreter = "bash" if "bash" in first_line else "sh"
        rc, _, err = run_command([interpreter, "-n", str(path)])
        checked_scripts.append(rel)
        if rc != 0:
            syntax_failures.append(f"{rel} ({interpreter}): {truncate(err.strip(), 300)}")
    if syntax_failures:
        check(checks, "repo.shell-syntax", "repository",
              "Repository shell scripts pass syntax checks", "FAIL",
              " | ".join(syntax_failures[:10]))
    else:
        check(checks, "repo.shell-syntax", "repository",
              "Repository shell scripts pass syntax checks", "PASS",
              f"{len(checked_scripts)} scripts checked with sh -n / bash -n")

    # ---- secrets in tracked text files -----------------------------------
    hits = []
    for path in _iter_repo_text_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in _SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                hits.append(f"{path.relative_to(repo_root).as_posix()}: {pattern.pattern}")
                break
    if hits:
        check(checks, "repo.no-secrets", "repository",
              "No credentials/private keys committed to the repository", "FAIL",
              truncate("; ".join(hits[:10]), 600))
    else:
        check(checks, "repo.no-secrets", "repository",
              "No credentials/private keys committed to the repository", "PASS",
              "scanned tracked text files; no secret patterns found")

    # ---- packaging layout -------------------------------------------------
    required_paths = [
        "packaging/rootless/control.in",
        "packaging/rootless/postinst",
        "packaging/rootless/prerm",
        "packaging/rootless/postrm",
        "packaging/rootless/usr/bin/opencode",
        "packaging/rootless/usr/bin/opencode-node18",
        "packaging/rootless/usr/share/doc/opencode/copyright",
        "packaging/rootless/usr/share/doc/opencode/device-smoke.sh",
        "packaging/verify/deb_reader.py",
        "packaging/verify/port_verify.py",
        "scripts/package-ios.sh",
        "scripts/validate-port.sh",
        "scripts/smoke-bundle-host.sh",
        ".github/workflows/package-rootless.yml",
        ".github/workflows/test-port.yml",
    ]
    missing = [rel for rel in required_paths if not (repo_root / rel).is_file()]
    if missing:
        check(checks, "repo.packaging-layout", "repository",
              "Packaging/launcher/workflow files present", "FAIL",
              "missing: " + ", ".join(missing))
    else:
        check(checks, "repo.packaging-layout", "repository",
              "Packaging/launcher/workflow files present", "PASS",
              f"{len(required_paths)} required packaging files present")

    # ---- workflow contract ------------------------------------------------
    workflow_requirements = {
        ".github/workflows/package-rootless.yml": [
            "workflow_dispatch", "timeout-minutes: 60", "if-no-files-found: error",
            "GITHUB_STEP_SUMMARY", "OpenCode-iOS-rootless", "ios-node-runtime",
            "opencode-cli-node-ios",
        ],
        ".github/workflows/test-port.yml": [
            "workflow_dispatch", "timeout-minutes: 60", "if-no-files-found: error",
            "GITHUB_STEP_SUMMARY", "port-verification", "OpenCode-iOS-rootless",
        ],
    }
    workflow_problems = []
    for rel, needles in workflow_requirements.items():
        path = repo_root / rel
        if not path.is_file():
            workflow_problems.append(f"{rel}: missing")
            continue
        text = read_text(path)
        for needle in needles:
            if needle not in text:
                workflow_problems.append(f"{rel}: missing {needle!r}")
    if workflow_problems:
        check(checks, "repo.workflow-contract", "repository",
              "Workflows implement the required CI contract", "FAIL",
              truncate("; ".join(workflow_problems), 800))
    else:
        check(checks, "repo.workflow-contract", "repository",
              "Workflows implement the required CI contract", "PASS",
              "dispatch/push triggers, 60-minute timeout, artifact upload guards, "
              "step summaries and expected artifact names present")

    # ---- workflow YAML parses (optional tool) ----------------------------
    yaml_files = sorted((repo_root / ".github/workflows").glob("*.yml"))
    yaml_tool = None
    try:
        import yaml  # type: ignore[import-untyped]

        yaml_tool = "pyyaml"
    except ImportError:
        if shutil.which("ruby"):
            rc, _, _ = run_command(["ruby", "-ryaml", "-e", "exit 0"])
            yaml_tool = "ruby-yaml" if rc == 0 else None
    if yaml_tool is None or not yaml_files:
        check(checks, "repo.workflow-yaml", "repository",
              "Workflow YAML parses", "SKIP",
              "no YAML parser available (PyYAML/ruby-psych) or no workflow files")
    else:
        failures = []
        for path in yaml_files:
            if yaml_tool == "pyyaml":
                try:
                    yaml.safe_load(path.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001 - report parse error
                    failures.append(f"{path.name}: {exc}")
            else:
                rc, _, err = run_command(
                    ["ruby", "-ryaml", "-e",
                     "YAML.load_file(ARGV[0])", str(path)]
                )
                if rc != 0:
                    failures.append(f"{path.name}: {truncate(err.strip(), 200)}")
        if failures:
            check(checks, "repo.workflow-yaml", "repository",
                  "Workflow YAML parses", "FAIL", " | ".join(failures[:5]))
        else:
            check(checks, "repo.workflow-yaml", "repository",
                  "Workflow YAML parses", "PASS",
                  f"{len(yaml_files)} workflow file(s) parsed with {yaml_tool}")

    # ---- required docs in repository -------------------------------------
    docs_required = [
        "docs/INSTALL.md",
        "docs/VERIFICATION.md",
        "docs/KNOWN_LIMITATIONS.md",
        "LICENSE",
        "NOTICE",
    ]
    docs_missing = [rel for rel in docs_required if not (repo_root / rel).is_file()]
    if docs_missing:
        check(checks, "repo.docs", "repository",
              "Install/verification/limitations/licence docs present", "FAIL",
              "missing: " + ", ".join(docs_missing))
    else:
        check(checks, "repo.docs", "repository",
              "Install/verification/limitations/licence docs present", "PASS",
              ", ".join(docs_required))

    # ---- unit tests (validation mode only) -------------------------------
    if mode in ("test", "verify"):
        _check_unittest(checks, repo_root, Path(out_dir) / "unittest.log")


# --------------------------------------------------------------------------
# Package checks
# --------------------------------------------------------------------------
def _parse_control_continuation_count(control_text):
    count = 0
    for line in control_text.replace("\r\n", "\n").split("\n"):
        if line.startswith(" ") or line.startswith("\t"):
            count += 1
    return count


def _check_control(checks, ctx, expected_version, variant=VARIANT_NODE22):
    control = ctx["control"]
    control_text = ctx["control_text"]
    problems = []
    description = control.get("Description", "")
    for field in CONTROL_REQUIRED_FIELDS:
        if not control.get(field, "").strip():
            problems.append(f"missing/empty field {field}")
    if control.get("Package") != EXPECTED_PACKAGE:
        problems.append(f"Package={control.get('Package')!r} (expected {EXPECTED_PACKAGE!r})")
    if control.get("Architecture") != EXPECTED_ARCH:
        problems.append(f"Architecture={control.get('Architecture')!r} (expected {EXPECTED_ARCH!r})")
    if expected_version:
        if control.get("Version") != expected_version:
            problems.append(f"Version={control.get('Version')!r} (expected {expected_version!r})")
    elif not re.fullmatch(r"[0-9][0-9A-Za-z.+:~-]*-[0-9]+", control.get("Version", "")):
        problems.append(f"Version={control.get('Version')!r} is not <upstream>-<debian-revision>")
    if control.get("Section") != EXPECTED_SECTION:
        problems.append(f"Section={control.get('Section')!r} (expected {EXPECTED_SECTION!r})")
    if control.get("Priority") != EXPECTED_PRIORITY:
        problems.append(f"Priority={control.get('Priority')!r} (expected {EXPECTED_PRIORITY!r})")
    depends = re.sub(r"\s+", " ", control.get("Depends", "")).strip()
    if depends != EXPECTED_DEPENDS:
        problems.append(f"Depends={depends!r} (expected {EXPECTED_DEPENDS!r})")
    for token in ("node", "nodejs", "zsh", "ldid", "npm", "bun"):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", depends):
            problems.append(f"Depends must not reference {token!r} (runtime is shipped in this package)")
    maintainer = control.get("Maintainer", "")
    if not re.fullmatch(r".+\s+<[^<>@\s]+@[^<>\s]+>", maintainer.strip()):
        problems.append(f"Maintainer={maintainer!r} is not 'Name <email>'")
    if not control.get("Homepage", "").startswith(EXPECTED_HOMEPAGE_PREFIX):
        problems.append(f"Homepage={control.get('Homepage')!r} is not a GitHub URL")
    if _parse_control_continuation_count(control_text) < 2:
        problems.append("Description must be multi-line (at least 2 continuation lines)")
    # The package description must state which runtime variant the build ships.
    if variant == VARIANT_NODE18:
        if not re.search(r"Node(?:\.js)?\s*18", description):
            problems.append("Description must state that this build ships the Node 18 runtime")
        if "sql.js" not in description and "sqlite shim" not in description.lower():
            problems.append("Description must mention the bundled sql.js sqlite shim")
    elif variant == VARIANT_NODE26:
        if not re.search(r"Node(?:\.js)?\s*26", description):
            problems.append("Description must state that this build ships the Node 26 runtime")
        if not re.search(r"experimental|phase\s*d", description, re.IGNORECASE):
            problems.append(
                "Description must mark the Node 26 build as EXPERIMENTAL (Phase D)"
            )
        if not re.search(r"OpenTUI|TUI", description):
            problems.append(
                "Description must mention the OpenTUI renderer / interactive TUI"
            )
        if "--single-threaded" not in description:
            problems.append(
                "Description must state the mandatory --single-threaded launcher flag"
            )
    else:
        if not re.search(r"Node(?:\.js)?\s*22", description):
            problems.append("Description must state that this build ships the Node 22 runtime")

    installed = control.get("Installed-Size", "").strip()
    if not installed.isdigit() or int(installed) <= 0:
        problems.append(f"Installed-Size={installed!r} is not a positive integer")

    if problems:
        check(checks, "pkg.control-fields", "package",
              "DEBIAN/control fields are valid for iphoneos-arm64 rootless",
              "FAIL", truncate("; ".join(problems), 1200))
    else:
        check(checks, "pkg.control-fields", "package",
              "DEBIAN/control fields are valid for iphoneos-arm64 rootless",
              "PASS",
              f"Package={control['Package']} Version={control['Version']} "
              f"Architecture={control['Architecture']} Installed-Size={control['Installed-Size']} "
              f"Depends={depends}")

    # Installed-Size sanity relative to the actual tree (du -sk tolerance).
    # Self-test packages are tiny, so the tolerance is wider there.
    total_bytes = ctx["metrics"].get("data_bytes", 0)
    if installed.isdigit() and total_bytes:
        total_kib = max(1, (total_bytes + 1023) // 1024)
        value = int(installed)
        self_test = ctx.get("mode") == "self-test"
        low = max(1, int(total_kib * (0.2 if self_test else 0.4)))
        high = max(64, int(total_kib * (10 if self_test else 3)) + 256 if self_test else
                  int(total_kib * 3) + 64)
        if low <= value <= high:
            check(checks, "pkg.installed-size", "package",
                  "Installed-Size approximates the installed tree", "PASS",
                  f"Installed-Size={value} KiB, file bytes={total_bytes} "
                  f"({total_kib} KiB apparent; accepted range {low}-{high} KiB)")
        else:
            check(checks, "pkg.installed-size", "package",
                  "Installed-Size approximates the installed tree", "FAIL",
                  f"Installed-Size={value} KiB outside accepted range {low}-{high} KiB "
                  f"for {total_bytes} file bytes")


def _check_paths(checks, ctx, mode):
    entries = ctx["data_entries"]
    by_path = {e["path"]: e for e in entries}

    # Rootless confinement: every file/symlink under var/jb/; only the plain
    # ancestor directory entries (var, var/jb) may exist above it.
    outside = []
    for entry in entries:
        rel = entry["path"]
        if rel.startswith("var/jb/"):
            continue
        if entry["type"] == "dir" and rel in ("var", "var/jb"):
            continue
        outside.append(rel)
    if outside:
        check(checks, "pkg.rootless-paths", "package",
              "All package files live under the rootless /var/jb prefix", "FAIL",
              truncate("outside var/jb: " + ", ".join(outside[:20]), 800))
    else:
        check(checks, "pkg.rootless-paths", "package",
              "All package files live under the rootless /var/jb prefix", "PASS",
              f"{len(entries)} data members; all files/symlinks under var/jb/ "
              "(only ancestor dirs 'var'/'var/jb' allowed above it)")

    # Required layout and modes.
    problems = []
    for rel, spec in REQUIRED_DATA.items():
        entry = by_path.get(rel)
        if entry is None:
            problems.append(f"missing {rel}")
            continue
        if spec["type"] == "dir" and entry["type"] != "dir":
            problems.append(f"{rel} is {entry['type']}, expected directory")
        if spec["type"] == "file" and entry["type"] != "file":
            problems.append(f"{rel} is {entry['type']}, expected file")
        if entry["mode"] != spec["mode"]:
            problems.append(f"{rel} mode {mode_octal(entry['mode'])}, expected {mode_octal(spec['mode'])}")
    if problems:
        check(checks, "pkg.required-layout", "package",
              "Required rootless package layout present with correct modes", "FAIL",
              truncate("; ".join(problems), 1500))
    else:
        check(checks, "pkg.required-layout", "package",
              "Required rootless package layout present with correct modes", "PASS",
              f"{len(REQUIRED_DATA)} required paths present with expected modes")

    # Unexpected files (allow the documented optional components).
    allowed = set(REQUIRED_DATA) | set(OPTIONAL_DATA)
    unexpected = []
    for entry in entries:
        rel = entry["path"]
        if rel in allowed:
            continue
        if entry["type"] == "dir":
            continue
        if not rel.startswith(ALLOWED_DATA_PREFIXES):
            unexpected.append(rel)
    if unexpected:
        check(checks, "pkg.unexpected-paths", "package",
              "No unexpected files outside the documented package layout", "FAIL",
              truncate(", ".join(sorted(unexpected)[:20]), 800))
    else:
        check(checks, "pkg.unexpected-paths", "package",
              "No unexpected files outside the documented package layout", "PASS",
              "all files match the documented layout or documented optional components")

    # Permission policy.
    violations = []
    for entry in entries:
        mode = entry["mode"]
        rel = entry["path"]
        if mode & 0o7000:
            violations.append(f"{rel}: setuid/setgid/sticky bits ({mode_octal(mode)})")
        if mode & 0o002:
            violations.append(f"{rel}: world-writable ({mode_octal(mode)})")
        if entry["type"] == "dir":
            if mode != 0o755:
                violations.append(f"{rel}: directory mode {mode_octal(mode)} (expected 0755)")
        elif entry["type"] == "file":
            expected = 0o755 if rel in EXECUTABLE_DATA else 0o644
            if mode != expected:
                violations.append(
                    f"{rel}: file mode {mode_octal(mode)} (expected {mode_octal(expected)})"
                )
    if violations:
        check(checks, "pkg.permissions", "package",
              "File permissions follow the rootless package policy", "FAIL",
              truncate("; ".join(violations[:25]), 1500))
    else:
        check(checks, "pkg.permissions", "package",
              "File permissions follow the rootless package policy", "PASS",
              "executables 0755, data/docs 0644, directories 0755; "
              "no setuid/setgid/sticky/world-writable entries")

    # Optional components documented.
    included = [rel for rel in OPTIONAL_DATA if rel in by_path]
    check(checks, "pkg.optional-components", "package",
          "Optional packaged components are accounted for", "PASS",
          ("present: " + ", ".join(included)) if included
          else "optional components absent (ripgrep stretch artifact / bundle-manifest / docs extras)")


def _check_maintainer_scripts(checks, ctx, extract_dir, variant=VARIANT_NODE22):
    control_files = ctx["control_files"]
    problems = []
    contents = {}
    for name in MAINTAINER_SCRIPTS:
        entry = control_files.get(name)
        if entry is None:
            problems.append(f"missing DEBIAN/{name}")
            continue
        contents[name] = entry["data"]
        if entry["mode"] != 0o755:
            problems.append(f"DEBIAN/{name} mode {mode_octal(entry['mode'])} (expected 0755)")
        text = entry["data"].decode("utf-8", "replace")
        if not text.startswith("#!/bin/sh\n"):
            problems.append(f"DEBIAN/{name} must start with '#!/bin/sh'")
        if not re.search(r"(?m)^set -e\s*$", text):
            problems.append(f"DEBIAN/{name} must contain 'set -e'")
        body = "\n".join(text.splitlines()[1:])
        # Policy checks look at executable lines only: comments legitimately name
        # forbidden tools (e.g. "ldid-signed dylibs map non-executable on iOS").
        body_code = "\n".join(
            line for line in body.splitlines() if not line.lstrip().startswith("#")
        )
        forbidden_cmds = re.search(
            r"(?<![A-Za-z0-9_])(curl|wget|nc|netcat|ssh|scp|apt-get|apt|npm|pip|pip3|ldid)"
            r"(?![A-Za-z0-9_])",
            body_code,
        )
        if forbidden_cmds:
            problems.append(f"DEBIAN/{name} calls forbidden command {forbidden_cmds.group(1)!r}")
        dangerous = re.search(
            r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(?:\s|$)", body_code
        )
        if dangerous:
            problems.append(f"DEBIAN/{name} contains a destructive rm of /")
        outside = re.search(
            r"(?<![A-Za-z0-9_$}])/(?:usr|etc|bin)/", body_code
        )
        if outside:
            problems.append(
                f"DEBIAN/{name} references paths outside /var/jb: {outside.group(0)!r}"
            )
    if problems:
        check(checks, "pkg.maintainer-scripts", "package",
              "Maintainer scripts are POSIX sh, idempotent-safe and offline", "FAIL",
              truncate("; ".join(problems), 1500))
    else:
        check(checks, "pkg.maintainer-scripts", "package",
              "Maintainer scripts are POSIX sh, idempotent-safe and offline", "PASS",
              "postinst/prerm/postrm: #!/bin/sh, set -e, no network, rootless paths, mode 0755")

    # sh -n each maintainer script + execute idempotency against a rewritten root.
    if problems:
        return
    with tempfile.TemporaryDirectory(prefix="opencode-maintscripts-") as td:
        td = Path(td)
        syntax_problems = []
        for name in MAINTAINER_SCRIPTS:
            script = td / name
            script.write_bytes(contents[name])
            rc, _, err = run_command(["sh", "-n", str(script)])
            if rc != 0:
                syntax_problems.append(f"{name}: {truncate(err.strip(), 200)}")
        if syntax_problems:
            check(checks, "pkg.maintainer-scripts-syntax", "package",
                  "Maintainer scripts pass sh -n", "FAIL", " | ".join(syntax_problems))
            return
        check(checks, "pkg.maintainer-scripts-syntax", "package",
              "Maintainer scripts pass sh -n", "PASS", "postinst/prerm/postrm parsed by sh -n")

        # Execute the scripts twice against a copy of the extracted tree whose
        # /var/jb prefix points at the temporary root. This proves idempotency
        # and that the permission fixes succeed without a device.
        root = td / "root"
        root.mkdir()
        source_tree = Path(extract_dir) / "var/jb"
        shutil.copytree(source_tree, root / "var/jb")
        rc_problems = []
        for name, action in (
            ("postinst", "configure"),
            ("postinst", "configure"),
            ("prerm", "remove"),
            ("postrm", "remove"),
            ("postrm", "purge"),
        ):
            rewritten = (td / f"{name}-{action}.sh")
            script_text = contents[name].decode("utf-8", "replace")
            script_text = script_text.replace("/var/jb", str(root / "var/jb"))
            # host test root: never touch the real /var/mobile path
            script_text = script_text.replace("/var/mobile", str(root / "var/mobile"))
            rewritten.write_text(script_text, encoding="utf-8")
            rc, out, err = run_command(["sh", str(rewritten), action])
            if rc != 0:
                rc_problems.append(
                    f"{name} {action} exit {rc}: {truncate((err or out).strip(), 300)}"
                )
        if rc_problems:
            check(checks, "pkg.maintainer-scripts-idempotent", "package",
                  "Maintainer scripts execute idempotently on the extracted tree",
                  "FAIL", truncate("; ".join(rc_problems), 1200))
        else:
            check(checks, "pkg.maintainer-scripts-idempotent", "package",
                  "Maintainer scripts execute idempotently on the extracted tree",
                  "PASS",
                  "postinst x2, prerm, postrm remove/purge all exit 0 against rewritten root")


def _check_launcher(checks, ctx, extract_dir, variant=VARIANT_NODE22):
    launcher = Path(extract_dir) / "var/jb/usr/bin/opencode"
    if not launcher.is_file():
        check(checks, "pkg.launcher", "package", "Launcher script contract", "FAIL",
              "var/jb/usr/bin/opencode missing")
        return
    text = read_text(launcher)
    # Flag checks look at executable lines only: comments legitimately mention
    # invalid flags (e.g. "Node 18 rejects --experimental-sqlite").
    code_text = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    problems = []
    if not text.startswith("#!/var/jb/bin/sh\n"):
        problems.append(
            "launcher must start with '#!/var/jb/bin/sh' — rootless iOS has no "
            "/bin/sh and the kernel execs the launcher directly"
        )
    if "PATH=" not in code_text or "/bin" not in code_text:
        problems.append(
            "launcher must prepend /var/jb/bin:/var/jb/usr/bin to PATH before exec"
        )
    if re.search(r"(?m)^\s*exec\s", code_text) is None:
        problems.append("launcher must exec the runtime (no fork)")
    if '"$@"' not in code_text:
        problems.append('launcher must forward arguments with "$@"')
    if "--no-warnings" not in code_text:
        problems.append("--no-warnings missing")
    if "OPENCODE_NODE_ASSETS_DIR" not in code_text:
        problems.append("OPENCODE_NODE_ASSETS_DIR not exported")
    if "OPENCODE_IOS=1" not in code_text:
        problems.append("OPENCODE_IOS=1 not exported")
    if "TMPDIR" not in code_text:
        problems.append(
            "launcher must provide the TMPDIR fallback required by the CLI/Node "
            "tooling in sessions that do not export TMPDIR"
        )
    if "OPENCODE_IOS_NODE_FLAGS" not in code_text:
        problems.append("OPENCODE_IOS_NODE_FLAGS escape hatch missing")
    if "OPENCODE_IOS_MAX_OLD_SPACE_MB" not in code_text:
        problems.append("OPENCODE_IOS_MAX_OLD_SPACE_MB escape hatch missing")
    if variant == VARIANT_NODE22:
        if "--single-threaded" not in code_text:
            problems.append(
                "--single-threaded missing: required on iOS because the V8 W^X "
                "mprotect toggle is process-wide and background V8 threads race it "
                "(device-verified SIGBUS without the flag)"
            )
        if "--experimental-sqlite" not in code_text:
            problems.append(
                "--experimental-sqlite missing (required for node:sqlite on Node 22)"
            )
        if "--disable-warning=ExperimentalWarning" not in code_text:
            problems.append("--disable-warning=ExperimentalWarning missing")
        if "OPENCODE_IOS_JITLESS" not in code_text:
            problems.append("OPENCODE_IOS_JITLESS escape hatch not documented")
        if "DYLD_INSERT_LIBRARIES" not in code_text or "libjitshim.dylib" not in code_text:
            problems.append(
                "launcher must conditionally inject the optional libjitshim.dylib via "
                "DYLD_INSERT_LIBRARIES when it is shipped"
            )
        if re.search(r"(?m)^\s*if\s+\[\s+-f\s+\"\$JITSHIM\"\s+\]", code_text) is None:
            problems.append(
                "launcher's JIT shim injection must be presence-based "
                "(if [ -f \"$JITSHIM\" ]) so packages without the shim launch normally"
            )
    elif variant == VARIANT_NODE26:
        if "--single-threaded" not in code_text:
            problems.append(
                "node26 launcher must pass --single-threaded: the V8 14.6 iOS W^X "
                "model toggles W^X process-wide with mprotect and background V8 "
                "threads race it (SIGBUS without the flag)"
            )
        if "OTUI_ASSET_ROOT" not in code_text:
            problems.append(
                "node26 launcher must export OTUI_ASSET_ROOT so the OpenTUI loader "
                "resolves @opentui/core-ios-arm64/libopentui.dylib"
            )
        # Device finding (iOS 16.1.1): the runtime asset root MUST be the packaged
        # /var/jb CLI asset tree; /var/mobile paths are refused by the file-system
        # sandbox for dylib mmap, and the renderer dylib is codesign-signed so dyld
        # maps it executable there.
        if re.search(
            r'RUNTIME_ASSETS="\$\{OPENCODE_IOS_RUNTIME_ASSETS:-\$ASSETS\}"', code_text
        ) is None:
            problems.append(
                'node26 launcher must default the runtime asset root to the packaged '
                '/var/jb CLI assets: RUNTIME_ASSETS="${OPENCODE_IOS_RUNTIME_ASSETS:-$ASSETS}"'
            )
        if NODE26_RUNTIME_ASSETS_OVERRIDE not in code_text:
            problems.append(
                f"node26 launcher must allow {NODE26_RUNTIME_ASSETS_OVERRIDE} to "
                "override the asset root (diagnostics only)"
            )
        if not re.search(
            r'OPENCODE_NODE_ASSETS_DIR="\$RUNTIME_ASSETS"', code_text
        ):
            problems.append(
                "node26 launcher must set OPENCODE_NODE_ASSETS_DIR to the runtime "
                "asset root ($RUNTIME_ASSETS, /var/jb/cli/assets by default)"
            )
        if not re.search(r'OTUI_ASSET_ROOT="\$RUNTIME_ASSETS"', code_text):
            problems.append(
                "node26 launcher must set OTUI_ASSET_ROOT to the runtime asset root "
                "($RUNTIME_ASSETS, /var/jb/cli/assets by default)"
            )
        if "/var/mobile" in code_text:
            problems.append(
                "node26 launcher must not use a /var/mobile asset root: the iOS "
                "file-system sandbox refuses dylib mmap there (device-verified); the "
                "renderer must be codesign-signed and loaded from /var/jb"
            )
        if "OPENCODE_IOS_JITLESS" in code_text:
            problems.append(
                "node26 launcher must not offer a --jitless escape hatch: it would "
                "break node:ffi/OpenTUI and the WASM/JIT paths"
            )
        for banned, why in (
            ("--experimental-sqlite", "not valid on the Node 26 runtime"),
            ("--disable-warning", "not valid on the Node 26 runtime"),
        ):
            if banned in code_text:
                problems.append(
                    f"{banned} must not be passed on the node26 variant ({why})"
                )
    else:
        # Node 18 (18.20.4) rejects flags that only exist on newer Node lines.
        for banned, why in (
            ("--experimental-sqlite", "not a valid Node 18 option"),
            ("--disable-warning", "not a valid Node 18 option"),
        ):
            if banned in code_text:
                problems.append(f"{banned} must not be passed on the Node 18 variant ({why})")
    for banned, why in (
        ("--use-system-ca", "invalid option on Node 18/22.9"),
    ):
        if banned in code_text:
            problems.append(f"{banned} must not be passed ({why})")
    if variant != VARIANT_NODE26 and "--experimental-ffi" in code_text:
        problems.append(
            "--experimental-ffi must not be passed on Node 18/22.9 (invalid option); "
            "node:ffi is default-on in Node 26.13 so the node26 launcher does not "
            "need it either"
        )
    if "uname" in code_text:
        problems.append("launcher must not depend on uname (iOS identifies as ios)")
    secret = next((p for p in _SECRET_PATTERNS if p.search(text)), None)
    if secret:
        problems.append("launcher contains a credential-like pattern")
    if problems:
        check(checks, "pkg.launcher", "package", "Launcher script contract", "FAIL",
              truncate("; ".join(problems), 1200))
    else:
        if variant == VARIANT_NODE22:
            evidence = (
                "#!/var/jb/bin/sh, PATH prepend, TMPDIR fallback, exec, \"$@\" "
                "forwarding, --single-threaded (required on iOS mprotect W^X), "
                "--experimental-sqlite, --no-warnings, assets/iOS env exports, "
                "presence-based DYLD_INSERT_LIBRARIES for the optional JIT shim, "
                "JITless/NODE_FLAGS/MAX_OLD_SPACE escape hatches; no invalid flags, "
                "no uname, no credentials"
            )
        elif variant == VARIANT_NODE26:
            evidence = (
                "#!/var/jb/bin/sh (experimental node26 variant), PATH prepend "
                "(/var/jb bin/usr/bin/usr/sbin/sbin), TMPDIR fallback, exec, "
                "\"$@\" forwarding, --single-threaded (mandatory on iOS mprotect "
                "W^X; no background V8 threads), --no-warnings, "
                f"OPENCODE_NODE_ASSETS_DIR + OTUI_ASSET_ROOT default to the packaged "
                f"/var/jb CLI asset tree ({NODE26_ASSET_ROOT}; "
                "OPENCODE_IOS_RUNTIME_ASSETS override for diagnostics only), renderer "
                "dylib is codesign-signed (ldid-signature dylibs map non-executable on "
                "iOS 16.1.1, device-verified; /var/mobile dylib mmap is sandbox-denied), "
                "NODE_FLAGS/MAX_OLD_SPACE escape hatches; no node:ffi flags needed "
                "(default-on in 26.13), no Node-22-only flags, no uname, no credentials"
            )
        else:
            evidence = (
                "#!/var/jb/bin/sh (Node 18 variant), PATH prepend, TMPDIR fallback, "
                "exec, \"$@\" forwarding, --no-warnings, assets/iOS env exports, "
                "NODE_FLAGS/MAX_OLD_SPACE escape hatches; no Node-22-only flags "
                "(--experimental-sqlite/--disable-warning/--use-system-ca/"
                "--experimental-ffi), no uname, no credentials"
            )
        check(checks, "pkg.launcher", "package", "Launcher script contract", "PASS",
              evidence)


def _check_docs(checks, ctx, extract_dir, variant=VARIANT_NODE22):
    base = Path(extract_dir) / "var/jb/usr/share/doc/opencode"
    problems = []
    texts = {}
    for name in ("README.md", "LICENSE", "copyright", "VERIFICATION.md", "INSTALL.md"):
        path = base / name
        if not path.is_file() or path.stat().st_size == 0:
            problems.append(f"missing/empty doc {name}")
        else:
            texts[name] = read_text(path)
    if base.is_dir() and (base / "KNOWN_LIMITATIONS.md").is_file():
        texts["KNOWN_LIMITATIONS.md"] = read_text(base / "KNOWN_LIMITATIONS.md")
    if problems:
        check(checks, "pkg.docs", "package", "Packaged documentation is complete", "FAIL",
              truncate("; ".join(problems), 800))
        return
    if "MIT" not in texts["LICENSE"]:
        problems.append("LICENSE does not contain the MIT licence text")
    if "opencode" not in texts["copyright"].lower():
        problems.append("copyright does not name OpenCode")
    if "Node.js" not in texts["copyright"]:
        problems.append("copyright does not attribute Node.js")
    verification_text = texts.get("VERIFICATION.md", "")
    install_text = texts.get("INSTALL.md", "")
    if "UNVERIFIED ON DEVICE" not in verification_text:
        problems.append("VERIFICATION.md does not state the UNVERIFIED ON DEVICE status")
    if "dpkg -i" not in install_text:
        problems.append("INSTALL.md lacks the dpkg install procedure")
    if problems:
        check(checks, "pkg.docs", "package", "Packaged documentation is complete", "FAIL",
              truncate("; ".join(problems), 800))
    else:
        check(checks, "pkg.docs", "package", "Packaged documentation is complete", "PASS",
              "README/LICENSE/copyright/INSTALL/VERIFICATION present; MIT + attribution + "
              "UNVERIFIED ON DEVICE stated; install procedure documented")

    # Both runtime variants must be described honestly in the packaged docs.
    combined_docs = "\n".join(
        texts.get(name, "") for name in
        ("INSTALL.md", "VERIFICATION.md", "KNOWN_LIMITATIONS.md")
    )
    has_18 = bool(re.search(r"Node(?:\.js)?\s*18", combined_docs))
    has_22 = bool(re.search(r"Node(?:\.js)?\s*22", combined_docs))
    has_26 = bool(re.search(r"Node(?:\.js)?\s*26", combined_docs))
    if has_18 and has_22:
        check(checks, "pkg.docs-runtimes", "package",
              "Packaged docs describe both Node 18 and Node 22 variants", "PASS",
              "INSTALL/VERIFICATION/KNOWN_LIMITATIONS mention the Node 22 primary/v6 "
              "and Node 18 fallback runtimes"
              + (" and the experimental Node 26 variant" if has_26 else ""))
    else:
        check(checks, "pkg.docs-runtimes", "package",
              "Packaged docs describe both Node 18 and Node 22 variants", "SKIP",
              f"Node 18 mentioned={has_18}, Node 22 mentioned={has_22}; docs update pending")
    if variant == VARIANT_NODE26:
        experimental_mention = bool(
            re.search(r"experimental", combined_docs, re.IGNORECASE)
        )
        if has_26 and experimental_mention:
            check(checks, "pkg.docs-node26", "package",
                  "Packaged docs describe the experimental node26/TUI variant", "PASS",
                  "INSTALL/VERIFICATION/KNOWN_LIMITATIONS mention Node 26 and mark it "
                  "experimental")
        else:
            check(checks, "pkg.docs-node26", "package",
                  "Packaged docs describe the experimental node26/TUI variant", "FAIL",
                  f"has_26={has_26}, experimental_mention={experimental_mention}")
    smoke = base / "device-smoke.sh"
    if smoke.is_file():
        smoke_text = read_text(smoke)
        if "--version" in smoke_text and "--help" in smoke_text and "DEVICE SMOKE TEST" in smoke_text:
            check(checks, "pkg.device-smoke-script", "package",
                  "Packaged device smoke-test script is provided", "PASS",
                  "device-smoke.sh checks runtime/launcher/--version/--help and prints a verdict")
        else:
            check(checks, "pkg.device-smoke-script", "package",
                  "Packaged device smoke-test script is provided", "FAIL",
                  "device-smoke.sh lacks expected checks")
    else:
        check(checks, "pkg.device-smoke-script", "package",
              "Packaged device smoke-test script is provided", "FAIL",
              "device-smoke.sh missing from /var/jb/usr/share/doc/opencode")


def _check_no_secrets_and_junk(checks, ctx, extract_dir):
    extract_root = Path(extract_dir)
    entries = ctx["data_entries"]
    text_exts = (".sh", ".md", ".json", ".txt", ".xml", ".plist", ".mjs", ".js", ".yml", ".yaml")
    secret_hits = []
    key_files = []
    for entry in entries:
        if entry["type"] != "file":
            continue
        rel = entry["path"]
        name = Path(rel).name
        if name in FORBIDDEN_PACKAGE_FILENAMES or name.startswith(".env."):
            key_files.append(rel)
            continue
        path = extract_root / rel
        if path.stat().st_size > 5 * 1024 * 1024:
            continue
        if not name.lower().endswith(text_exts):
            continue
        text = read_text(path)
        if "PRIVATE KEY-----" in text:
            secret_hits.append(f"{rel}: private key block")
    # Only packaging-owned files are scanned for credential shapes; the
    # upstream CLI bundle legitimately contains provider-key format strings.
    packaging_owned = [
        e["path"] for e in entries
        if e["type"] == "file" and (
            e["path"].startswith("var/jb/usr/bin/")
            or e["path"].startswith("var/jb/usr/share/doc/opencode/")
            or e["path"].startswith("var/jb/usr/lib/opencode/runtime/")
        )
    ] + [f"DEBIAN/{name}" for name in MAINTAINER_SCRIPTS]
    for rel in packaging_owned:
        if rel.startswith("DEBIAN/"):
            entry = ctx["control_files"].get(rel.split("/", 1)[1])
            if not entry:
                continue
            text = entry["data"].decode("utf-8", "replace")
        else:
            path = extract_root / rel
            if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
                continue
            text = read_text(path)
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                secret_hits.append(f"{rel}: {pattern.pattern}")
                break
    if secret_hits:
        check(checks, "pkg.no-secrets", "package",
              "Package contains no embedded credentials or key files", "FAIL",
              truncate("; ".join(secret_hits[:10]), 800))
    else:
        check(checks, "pkg.no-secrets", "package",
              "Package contains no embedded credentials or key files", "PASS",
              f"scanned {len(packaging_owned)} packaging-owned files + all text data files; "
              "no secret patterns, no .env/auth.json/id_* key files")

    junk = []
    for entry in entries:
        rel = entry["path"]
        parts = rel.split("/")
        if any(part in JUNK_NAMES for part in parts):
            junk.append(f"forbidden path {rel}")
        if entry["type"] == "file" and entry["size"] > MAX_FILE_BYTES:
            junk.append(f"{rel} is {entry['size']} bytes (> {MAX_FILE_BYTES})")
        if entry["type"] == "file" and rel.endswith(".dSYM"):
            junk.append(f"debug artefact {rel}")
    deb_size = ctx["metrics"].get("deb_size", 0)
    if deb_size > MAX_DEB_BYTES:
        junk.append(f"deb size {deb_size} bytes exceeds {MAX_DEB_BYTES}")
    if junk:
        check(checks, "pkg.no-junk", "package", "No large junk/debug artifacts in the package",
              "FAIL", truncate("; ".join(junk[:15]), 1000))
    else:
        check(checks, "pkg.no-junk", "package", "No large junk/debug artifacts in the package",
              "PASS",
              f"deb {deb_size} bytes; largest file {ctx['metrics'].get('largest_file', 'n/a')}; "
              "no .git/node_modules/.DS_Store/dSYM/source maps, no oversized files")


def _check_sha256sums(checks, ctx, deb_path, artifact_dir):
    sums_path = Path(artifact_dir) / "SHA256SUMS"
    if not sums_path.is_file():
        check(checks, "pkg.sha256sums", "package",
              "SHA256SUMS matches the built .deb", "FAIL",
              f"{sums_path} missing from the artifact directory")
        return
    try:
        sums = parse_sha256sums(read_text(sums_path))
    except DebError as exc:
        check(checks, "pkg.sha256sums", "package",
              "SHA256SUMS matches the built .deb", "FAIL", str(exc))
        return
    deb_name = Path(deb_path).name
    actual = sha256_file(deb_path)
    entry = sums.get(deb_name)
    if entry is None:
        # allow a leading ./ variant already normalised by the parser
        check(checks, "pkg.sha256sums", "package",
              "SHA256SUMS matches the built .deb", "FAIL",
              f"SHA256SUMS has no entry for {deb_name!r} (entries: {sorted(sums)[:5]})")
    elif entry != actual:
        check(checks, "pkg.sha256sums", "package",
              "SHA256SUMS matches the built .deb", "FAIL",
              f"{deb_name}: SHA256SUMS={entry} actual={actual}")
    else:
        check(checks, "pkg.sha256sums", "package",
              "SHA256SUMS matches the built .deb", "PASS",
              f"{deb_name}: sha256={actual}")


def _compare_tree(expected_files, actual_entries):
    expected = {
        f["path"]: f for f in expected_files
        if f["path"] not in ("DEBIAN",) and not f["path"].startswith("DEBIAN/")
    }
    actual = {e["path"]: e for e in actual_entries}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatches = []
    for rel in sorted(set(expected) & set(actual)):
        want, got = expected[rel], actual[rel]
        if want.get("type") != got.get("type"):
            mismatches.append(f"{rel}: type {want.get('type')} != {got.get('type')}")
            continue
        if want.get("type") in ("file", "dir") and want.get("mode") != got.get("mode"):
            mismatches.append(
                f"{rel}: mode {mode_octal(want.get('mode', 0))} != "
                f"{mode_octal(got.get('mode', 0))}"
            )
        if want.get("type") == "file":
            if want.get("sha256") != got.get("sha256"):
                mismatches.append(f"{rel}: sha256 differs")
            if want.get("size") != got.get("size"):
                mismatches.append(f"{rel}: size {want.get('size')} != {got.get('size')}")
    return missing, extra, mismatches


def _check_manifest_consistency(checks, ctx, manifest_path, manifest_label):
    try:
        manifest = read_json(manifest_path)
        files = manifest.get("files", [])
    except (OSError, ValueError) as exc:
        check(checks, "pkg.manifest-consistency", "package",
              f"{manifest_label} matches the .deb contents", "FAIL",
              f"cannot read {manifest_path}: {exc}")
        return
    missing, extra, mismatches = _compare_tree(files, ctx["data_entries"])
    if missing or extra or mismatches:
        check(checks, "pkg.manifest-consistency", "package",
              f"{manifest_label} matches the .deb contents", "FAIL",
              truncate(
                  f"missing={missing[:10]} unexpected={extra[:10]} mismatched={mismatches[:10]}",
                  1500,
              ))
    else:
        checked = len([f for f in files if not f["path"].startswith("DEBIAN/")])
        check(checks, "pkg.manifest-consistency", "package",
              f"{manifest_label} matches the .deb contents", "PASS",
              f"{checked} data entries match path/mode/size/sha256 exactly")


def _check_package_report_cross(checks, ctx, package_report_path):
    try:
        report = read_json(package_report_path)
    except (OSError, ValueError) as exc:
        check(checks, "pkg.package-report", "package",
              "Package report from the packaging run is consistent", "FAIL",
              f"cannot read {package_report_path}: {exc}")
        return None
    problems = []
    reported_deb = report.get("package", {}).get("sha256")
    actual_deb = ctx["metrics"].get("deb_sha256")
    if reported_deb and actual_deb and reported_deb != actual_deb:
        problems.append(f"report deb sha256 {reported_deb} != artifact deb sha256 {actual_deb}")
    if not report.get("sources"):
        problems.append("package-report.json has no provenance/sources section")
    if not report.get("files") and not report.get("contents", {}).get("files"):
        problems.append("package-report.json has no contents manifest")
    if not report.get("validations"):
        problems.append("package-report.json has no build validations")
    manifest_files = report.get("files") or report.get("contents", {}).get("files") or []
    if manifest_files:
        missing, extra, mismatches = _compare_tree(manifest_files, ctx["data_entries"])
        if missing or extra or mismatches:
            problems.append(
                truncate(
                    f"contents mismatch vs report: missing={missing[:8]} "
                    f"unexpected={extra[:8]} mismatched={mismatches[:8]}", 900
                )
            )
    if problems:
        check(checks, "pkg.package-report", "package",
              "Package report from the packaging run is consistent", "FAIL",
              truncate("; ".join(problems), 1500))
    else:
        runs = report.get("sources", {}).get("inputs", {})
        check(checks, "pkg.package-report", "package",
              "Package report from the packaging run is consistent", "PASS",
              "deb sha256 matches, provenance runs recorded, validation results embedded, "
              "contents manifest re-verified against the artifact")
    return report


def _check_verbatim_copy(checks, ctx, sources):
    if not sources:
        check(checks, "pkg.verbatim-copy", "package",
              "Deb files are byte-identical copies of the source artifacts", "SKIP",
              "no provenance/sources data available (older package artifact)")
        return
    extract_root = Path(ctx["extract_dir"]) if ctx.get("extract_dir") else None
    if not extract_root:
        check(checks, "pkg.verbatim-copy", "package",
              "Deb files are byte-identical copies of the source artifacts", "SKIP",
              "extracted tree not available")
        return
    inputs = sources.get("inputs", {})
    mappings = []
    runtime = inputs.get("runtime", {})
    for entry in runtime.get("files", []):
        base = Path(entry["path"]).name
        if base == "node":
            mappings.append(("runtime/node", entry))
        elif base in ("entitlements.plist", "entitlements.xml"):
            mappings.append(("runtime/entitlements.xml", entry))
        elif base == "runtime-manifest.json":
            mappings.append(("runtime/runtime-manifest.json", entry))
    cli = inputs.get("opencode_cli", {})
    for entry in cli.get("files", []):
        rel = entry["path"]
        if rel == "opencode.mjs":
            mappings.append(("cli/opencode.mjs", entry))
        elif rel == "bundle-manifest.json":
            mappings.append(("cli/bundle-manifest.json", entry))
        elif rel.startswith("assets/"):
            mappings.append(("cli/" + rel, entry))
        elif "/assets/" in rel:
            # Artifact was uploaded with a parent directory; keep the assets/
            # suffix exactly (upstream asset trees may contain deeper "assets/".
            mappings.append(("cli/assets/" + rel.split("/assets/", 1)[1], entry))
    # Optional jailbreak JIT shim artifact (renamed to the packaged dylib path).
    jitshim = inputs.get("jitshim", {})
    for entry in jitshim.get("files", []):
        if Path(entry["path"]).name.endswith(".dylib"):
            mappings.append(("runtime/libjitshim.dylib", entry))
            break
    if not mappings:
        check(checks, "pkg.verbatim-copy", "package",
              "Deb files are byte-identical copies of the source artifacts", "SKIP",
              "no comparable files listed in provenance")
        return
    problems = []
    compared = 0
    for deb_rel, entry in mappings:
        path = extract_root / "var/jb/usr/lib/opencode" / deb_rel
        if not path.is_file():
            problems.append(f"{deb_rel}: missing in package")
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            problems.append(
                f"{deb_rel}: sha256 {actual} != artifact {entry.get('sha256')}"
            )
        else:
            compared += 1
    if problems:
        check(checks, "pkg.verbatim-copy", "package",
              "Deb files are byte-identical copies of the source artifacts", "FAIL",
              truncate("; ".join(problems[:10]), 1000))
    else:
        check(checks, "pkg.verbatim-copy", "package",
              "Deb files are byte-identical copies of the source artifacts", "PASS",
              f"{compared} runtime/CLI files match the source artifact sha256 exactly")


def _check_bundle_manifest(checks, ctx, extract_dir):
    path = Path(extract_dir) / "var/jb/usr/lib/opencode/cli/bundle-manifest.json"
    if not path.is_file():
        check(checks, "pkg.bundle-manifest", "package",
              "CLI bundle manifest hashes are consistent", "SKIP",
              "opencode-cli-node-ios did not ship bundle-manifest.json; "
              "contents manifest consistency checked instead")
        return
    try:
        manifest = read_json(path)
    except (OSError, ValueError) as exc:
        check(checks, "pkg.bundle-manifest", "package",
              "CLI bundle manifest hashes are consistent", "FAIL",
              f"cannot parse bundle-manifest.json: {exc}")
        return
    entries = _collect_hash_entries(manifest)
    if not entries:
        check(checks, "pkg.bundle-manifest", "package",
              "CLI bundle manifest hashes are consistent", "SKIP",
              "bundle-manifest.json contains no recognisable sha256 file entries "
              f"(top-level keys: {sorted(manifest)[:8] if isinstance(manifest, dict) else type(manifest).__name__})")
        return
    cli_dir = Path(extract_dir) / "var/jb/usr/lib/opencode/cli"
    resolved = 0
    mismatched = []
    unresolved = []
    for rel, digest in entries:
        candidate = _resolve_cli_path(cli_dir, rel)
        if candidate is None:
            unresolved.append(rel)
            continue
        actual = sha256_file(candidate)
        if actual != digest:
            mismatched.append(f"{rel}: {actual} != {digest}")
        else:
            resolved += 1

    # Known opencode-ios/bundle-manifest/v1 shape: cross-check the bundle entry
    # point and the aggregate assets accounting in addition to per-file hashes.
    special = []
    bundle = manifest.get("bundle") if isinstance(manifest, dict) else None
    if isinstance(bundle, dict):
        mjs_info = bundle.get("opencode_mjs")
        if isinstance(mjs_info, dict):
            mjs_name = str(mjs_info.get("path") or "opencode.mjs")
            candidate = cli_dir / mjs_name
            if not candidate.is_file():
                special.append(f"bundle.opencode_mjs {mjs_name!r} missing from package")
            else:
                actual = sha256_file(candidate)
                if isinstance(mjs_info.get("sha256"), str) and mjs_info["sha256"] != actual:
                    special.append(f"bundle.opencode_mjs sha256 {actual} != {mjs_info['sha256']}")
                if isinstance(mjs_info.get("bytes"), int) and mjs_info["bytes"] != candidate.stat().st_size:
                    special.append(
                        f"bundle.opencode_mjs bytes {candidate.stat().st_size} != {mjs_info['bytes']}"
                    )
        assets_info = bundle.get("assets")
        if isinstance(assets_info, dict):
            assets_root = cli_dir / "assets"
            asset_files = [
                p for p in assets_root.rglob("*") if p.is_file()
            ] if assets_root.is_dir() else []
            if isinstance(assets_info.get("count"), int) and assets_info["count"] != len(asset_files):
                special.append(
                    f"bundle.assets.count {assets_info['count']} != packaged {len(asset_files)}"
                )
            if isinstance(assets_info.get("bytes"), int):
                actual_bytes = sum(p.stat().st_size for p in asset_files)
                if assets_info["bytes"] != actual_bytes:
                    special.append(
                        f"bundle.assets.bytes {assets_info['bytes']} != packaged {actual_bytes}"
                    )

    if mismatched or special:
        check(checks, "pkg.bundle-manifest", "package",
              "CLI bundle manifest hashes are consistent", "FAIL",
              truncate("; ".join(mismatched[:10] + special[:10]), 1500))
    elif resolved == 0:
        check(checks, "pkg.bundle-manifest", "package",
              "CLI bundle manifest hashes are consistent", "SKIP",
              f"no manifest entry could be resolved against the package "
              f"({len(unresolved)} entries, e.g. {unresolved[:3]})")
    else:
        detail = f"{resolved} manifest hash entries verified against package files"
        if isinstance(bundle, dict):
            detail += "; bundle entry-point and assets count/bytes cross-checked"
        check(checks, "pkg.bundle-manifest", "package",
              "CLI bundle manifest hashes are consistent", "PASS",
              detail + (f"; {len(unresolved)} entries not shipped/relative" if unresolved else ""))


def _collect_hash_entries(obj, base=""):
    """Best-effort extraction of (relative_path, sha256) pairs from arbitrary JSON."""
    results = []
    if isinstance(obj, dict):
        path = None
        for key in ("path", "name", "file", "filename"):
            value = obj.get(key)
            if isinstance(value, str) and value not in ("", "."):
                path = value
                break
        digest = None
        for key in ("sha256", "sha256sum", "hash", "digest", "checksum"):
            value = obj.get(key)
            if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
                digest = value.lower()
                break
        if path and digest:
            results.append((path, digest))
        for key, value in obj.items():
            if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
                if "/" in key or key.endswith((".mjs", ".js", ".bin", ".node", ".wasm", ".json")):
                    results.append((key, value.lower()))
                    continue
            if isinstance(value, (dict, list)):
                results.extend(_collect_hash_entries(value, base))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_collect_hash_entries(item, base))
    return results


def _resolve_cli_path(cli_dir, rel):
    rel = rel.replace("\\", "/").lstrip("./")
    candidates = [
        cli_dir / rel,
        cli_dir / "assets" / rel,
        cli_dir / "assets" / Path(rel).name,
    ]
    if rel.startswith("cli/"):
        candidates.insert(0, cli_dir / rel[4:])
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------
# Runtime (Mach-O) checks
# --------------------------------------------------------------------------
def _version_tuple(value):
    """Normalise '15.0', '15.0.0', (15, 0, 0) to comparable tuples without trailing zeros."""
    if isinstance(value, (tuple, list)):
        parts = [int(part) for part in value]
    else:
        parts = []
        for piece in str(value).split("."):
            piece = piece.strip()
            if piece.isdigit():
                parts.append(int(piece))
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _load_macho_auditor(repo_root):
    sys.path.insert(0, str(Path(repo_root).resolve()))
    try:
        from scripts.check_macho import audit  # type: ignore[import-not-found]

        return audit, None
    except Exception as exc:  # noqa: BLE001 - report import failure
        return None, str(exc)


def _otool_libs(binary):
    if shutil.which("xcrun"):
        cmd = ["xcrun", "otool", "-L", str(binary)]
    elif shutil.which("otool"):
        cmd = ["otool", "-L", str(binary)]
    else:
        raise RuntimeError("otool not available (xcrun/otool not found)")
    rc, out, err = run_command(cmd, timeout=120)
    if rc != 0:
        raise RuntimeError(f"otool -L failed ({rc}): {truncate(err.strip(), 400)}")
    libs = []
    for line in out.replace("\r\n", "\n").split("\n")[1:]:
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(\S+)\s+\(", line)
        if match:
            libs.append(match.group(1))
    return libs


def _validate_dylibs(libs):
    violations = []
    for lib in libs:
        if any(token in lib for token in FORBIDDEN_DEP_SUBSTRINGS):
            violations.append(f"{lib}: macOS-only or unresolved load path")
            continue
        if any(token in lib for token in FORBIDDEN_FRAMEWORKS):
            violations.append(f"{lib}: macOS-only framework")
            continue
        if not lib.startswith(ALLOWED_DEP_PREFIXES):
            violations.append(f"{lib}: not an iOS system library path")
    return violations


def _check_runtime(checks, ctx, repo_root, extract_dir, mode, skip_native):
    extract_root = Path(extract_dir)
    runtime_dir = extract_root / "var/jb/usr/lib/opencode/runtime"
    node = runtime_dir / "node"
    metrics = ctx["metrics"]
    if not node.is_file():
        check(checks, "runtime.macho-platform", "runtime",
              "Native runtime is a thin iPhoneOS arm64 Mach-O executable", "FAIL",
              "var/jb/usr/lib/opencode/runtime/node missing")
        return
    metrics["node_sha256"] = sha256_file(node)
    metrics["node_size"] = node.stat().st_size

    # Mach-O platform/arch/minos via the baseline auditor.
    auditor, import_error = _load_macho_auditor(repo_root)
    if auditor is None:
        check(checks, "runtime.macho-platform", "runtime",
              "Native runtime is a thin iPhoneOS arm64 Mach-O executable", "FAIL",
              f"cannot import scripts/check_macho.py: {import_error}")
    else:
        try:
            minos = auditor(node, (16, 1, 1))
        except ValueError as exc:
            check(checks, "runtime.macho-platform", "runtime",
                  "Native runtime is a thin iPhoneOS arm64 Mach-O executable", "FAIL",
                  f"check_macho rejected the runtime: {exc}")
        else:
            minos_str = ".".join(str(part) for part in minos)
            metrics["node_minos"] = minos_str
            metrics["node_platform"] = "iPhoneOS"
            metrics["node_arch"] = "arm64"
            check(checks, "runtime.macho-platform", "runtime",
                  "Native runtime is a thin iPhoneOS arm64 Mach-O executable", "PASS",
                  f"MH_MAGIC_64 arm64 MH_EXECUTE; LC_BUILD_VERSION platform=iPhoneOS(2); "
                  f"minOS={minos_str} <= 16.1.1")

    # Non-placeholder size sanity.
    min_node = 1024 if mode == "self-test" else REAL_NODE_MIN_BYTES
    if node.stat().st_size >= min_node:
        check(checks, "runtime.not-placeholder", "runtime",
              "Runtime is a real Node binary, not a smoke/placeholder executable", "PASS",
              f"node is {node.stat().st_size} bytes (>= {min_node})")
    else:
        check(checks, "runtime.not-placeholder", "runtime",
              "Runtime is a real Node binary, not a smoke/placeholder executable", "FAIL",
              f"node is only {node.stat().st_size} bytes (< {min_node}); refusing placeholder runtime")

    # Dylib linkage.
    if skip_native:
        check(checks, "runtime.dylibs", "runtime",
              "Runtime links only iOS system libraries", "SKIP",
              "skipped by --skip-native-audit (local dry-run only)")
    else:
        try:
            libs = _otool_libs(node)
        except RuntimeError as exc:
            check(checks, "runtime.dylibs", "runtime",
                  "Runtime links only iOS system libraries", "FAIL", str(exc))
        else:
            violations = _validate_dylibs(libs)
            metrics["node_dylibs"] = libs
            if violations:
                check(checks, "runtime.dylibs", "runtime",
                      "Runtime links only iOS system libraries", "FAIL",
                      truncate("; ".join(violations[:15]), 1500))
            else:
                check(checks, "runtime.dylibs", "runtime",
                      "Runtime links only iOS system libraries", "PASS",
                      f"{len(libs)} dependencies, all iOS system libraries: "
                      + truncate(", ".join(libs), 700))

    # Code signature presence (ldid-signed in CI; not a validity proof).
    if not skip_native and shutil.which("xcrun"):
        rc, out, _ = run_command(["xcrun", "otool", "-l", str(node)], timeout=120)
        if rc == 0 and "LC_CODE_SIGNATURE" in out:
            check(checks, "runtime.code-signature", "runtime",
                  "Runtime carries a code signature (ldid)", "PASS",
                  "LC_CODE_SIGNATURE load command present (signature validity is "
                  "device/ldid territory, not verified here)")
        else:
            check(checks, "runtime.code-signature", "runtime",
                  "Runtime carries a code signature (ldid)", "SKIP",
                  "no LC_CODE_SIGNATURE load command found (unsigned runtime)")
    else:
        check(checks, "runtime.code-signature", "runtime",
              "Runtime carries a code signature (ldid)", "SKIP",
              "otool toolchain unavailable")

    # Entitlements file.
    entitlements = runtime_dir / "entitlements.xml"
    metrics["entitlements_sha256"] = sha256_file(entitlements) if entitlements.is_file() else ""
    parsed = None
    parse_format = None
    try:
        if entitlements.is_file():
            parsed = plistlib.loads(entitlements.read_bytes())
            parse_format = "plist"
    except Exception:  # noqa: BLE001 - fall back to XML parse
        try:
            ET.parse(entitlements)
            parse_format = "xml"
        except Exception as exc:  # noqa: BLE001
            check(checks, "runtime.entitlements", "runtime",
                  "Entitlements plist ships with the runtime", "FAIL",
                  f"entitlements.xml is not valid plist/XML: {exc}")
            parsed = "invalid"
    if parsed not in (None, "invalid"):
        keys = list(parsed) if isinstance(parsed, dict) else []
        check(checks, "runtime.entitlements", "runtime",
              "Entitlements plist ships with the runtime", "PASS",
              f"valid {parse_format} entitlements ({len(keys)} keys: "
              + truncate(", ".join(keys), 300) + ")")
    elif parsed is None:
        check(checks, "runtime.entitlements", "runtime",
              "Entitlements plist ships with the runtime", "FAIL",
              "entitlements.xml missing")

    # Entitlements policy: the device-verified minimal working set for this
    # rootless jailbreak is platform-application + no-sandbox. The old
    # allow-jit/dynamic-codesigning-only sets were empirically SIGKILLed on
    # iPhone12,8 / iOS 16.1.1 (exit 137), so the package refuses them.
    if isinstance(parsed, dict):
        required_entitlements = (
            "platform-application",
            "com.apple.private.security.no-sandbox",
        )
        missing_entitlements = [
            key for key in required_entitlements if parsed.get(key) is not True
        ]
        metrics["entitlements_keys"] = keys
        if missing_entitlements:
            check(checks, "runtime.entitlements-policy", "runtime",
                  "Runtime entitlements match the device-verified minimal set", "FAIL",
                  "missing/not-true required entitlement(s): "
                  + ", ".join(missing_entitlements)
                  + ". Device-verified minimal set is platform-application=true + "
                    "com.apple.private.security.no-sandbox=true; the old "
                    "allow-jit/dynamic-codesigning sets were SIGKILLed on the target "
                    "device (exit 137). Update the runtime entitlements.plist.")
        else:
            extra = [key for key in keys if key not in required_entitlements]
            check(checks, "runtime.entitlements-policy", "runtime",
                  "Runtime entitlements match the device-verified minimal set", "PASS",
                  "required entitlements present and true: "
                  + ", ".join(required_entitlements)
                  + (f"; additional keys: {', '.join(extra)}" if extra else
                     "; no unnecessary keys"))
    elif parsed == "invalid":
        check(checks, "runtime.entitlements-policy", "runtime",
              "Runtime entitlements match the device-verified minimal set", "FAIL",
              "entitlements.xml could not be parsed")
    else:
        check(checks, "runtime.entitlements-policy", "runtime",
              "Runtime entitlements match the device-verified minimal set", "FAIL",
              "entitlements.xml missing")

    # runtime-manifest.json: JSON + hash consistency with the shipped node.
    manifest_path = runtime_dir / "runtime-manifest.json"
    if not manifest_path.is_file():
        check(checks, "runtime.manifest", "runtime",
              "Runtime manifest is valid and consistent", "FAIL",
              "var/jb/usr/lib/opencode/runtime/runtime-manifest.json missing")
    else:
        try:
            manifest = read_json(manifest_path)
        except (OSError, ValueError) as exc:
            check(checks, "runtime.manifest", "runtime",
                  "Runtime manifest is valid and consistent", "FAIL",
                  f"cannot parse runtime-manifest.json: {exc}")
        else:
            if manifest.get("self_test") is True and mode != "self-test":
                check(checks, "runtime.manifest", "runtime",
                      "Runtime manifest is valid and consistent", "FAIL",
                      "runtime-manifest.json is marked self_test placeholder; refusing to ship it")
            else:
                entries = _collect_hash_entries(manifest)
                found = 0
                mismatched = []
                for rel, digest in entries:
                    candidate = runtime_dir / rel
                    if not candidate.is_file():
                        candidate = runtime_dir / Path(rel).name
                    if not candidate.is_file():
                        continue
                    found += 1
                    if sha256_file(candidate) != digest:
                        mismatched.append(f"{rel}: hash mismatch")
                # Known runtime-manifest shape (build-ios-runtime.sh): verify the
                # binary size/sha256/entitlements hash and target minOS directly.
                special = []
                if isinstance(manifest, dict):
                    binary = manifest.get("binary")
                    if isinstance(binary, dict):
                        if isinstance(binary.get("size_bytes"), int) and \
                                binary["size_bytes"] != node.stat().st_size:
                            special.append(
                                f"manifest binary.size_bytes {binary['size_bytes']} != "
                                f"{node.stat().st_size}"
                            )
                        if isinstance(binary.get("sha256"), str) and \
                                binary["sha256"] != metrics["node_sha256"]:
                            special.append("manifest binary.sha256 != packaged node sha256")
                        if isinstance(binary.get("entitlements_sha256"), str) and \
                                entitlements.is_file():
                            actual_ent = sha256_file(entitlements)
                            if binary["entitlements_sha256"] != actual_ent:
                                special.append(
                                    "manifest binary.entitlements_sha256 != packaged "
                                    "entitlements.xml"
                                )
                    target = manifest.get("target")
                    declared_minos = target.get("min_ios_from_vtool") if isinstance(target, dict) else None
                    if declared_minos and metrics.get("node_minos") and \
                            _version_tuple(declared_minos) != _version_tuple(metrics["node_minos"]):
                        special.append(
                            f"manifest target.min_ios_from_vtool {declared_minos!r} != "
                            f"Mach-O minOS {metrics['node_minos']!r}"
                        )
                if mismatched or special:
                    check(checks, "runtime.manifest", "runtime",
                          "Runtime manifest is valid and consistent", "FAIL",
                          truncate("; ".join(mismatched[:10] + special[:10]), 1200))
                else:
                    detail = "valid JSON"
                    if found:
                        detail += (f"; {found} declared file hash(es) verified against the "
                                   f"package (node sha256={metrics['node_sha256'][:16]}...)")
                    else:
                        detail += "; no file hash entries declared"
                    if special == [] and isinstance(manifest, dict) and manifest.get("binary"):
                        detail += "; binary size/sha256/entitlements and target minOS cross-checked"
                    check(checks, "runtime.manifest", "runtime",
                          "Runtime manifest is valid and consistent", "PASS", detail)
                    metrics["runtime_manifest_sha256"] = sha256_file(manifest_path)


def _capability_enabled(value):
    """Interpret a producer capability declaration as enabled/disabled.

    The runtime manifest uses strings of the form
    ``"enabled: <evidence...>"`` / ``"disabled: <reason...>"`` (booleans are also
    accepted). Explanatory text after the state word may legitimately mention
    "jitless" or "disabled" (e.g. "the build no longer passes --v8-options=--jitless"),
    so only the declared state segment is interpreted.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    head = text.split(":", 1)[0].strip()
    return head in ("enabled", "true", "yes", "on")


def normalize_variant(value):
    """Map free-form variant labels to VARIANT_NODE22 / VARIANT_NODE18 / VARIANT_NODE26."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "26" in text:
        return VARIANT_NODE26
    if "18" in text or "node18" in text:
        return VARIANT_NODE18
    if "22" in text or "node22" in text:
        return VARIANT_NODE22
    return ""


def _runtime_manifest(extract_dir):
    path = Path(extract_dir) / "var/jb/usr/lib/opencode/runtime/runtime-manifest.json"
    if not path.is_file():
        return None, path
    try:
        return read_json(path), path
    except (OSError, ValueError):
        return None, path


def infer_variant(ctx, sources=None, package_report=None, requested=""):
    """Resolve the package variant from explicit input, provenance, or runtime manifest."""
    explicit = normalize_variant(requested)
    if explicit:
        return explicit
    explicit = normalize_variant(ctx.get("variant"))
    if explicit:
        return explicit
    for candidate in (
        (sources or {}).get("variant"),
        (sources or {}).get("runtime_kind"),
        (package_report or {}).get("variant"),
        (package_report or {}).get("runtime_kind"),
        (package_report or {}).get("sources", {}).get("variant")
        if isinstance(package_report or {}, dict) else "",
    ):
        detected = normalize_variant(candidate)
        if detected:
            return detected
    extract_dir = ctx.get("extract_dir")
    if extract_dir:
        manifest, _ = _runtime_manifest(extract_dir)
        if isinstance(manifest, dict):
            detected = normalize_variant(manifest.get("node_version"))
            if not detected:
                detected = normalize_variant(manifest.get("variant"))
            if detected:
                return detected
    return VARIANT_NODE22


def cmd_render_control(args):
    """Render DEBIAN/control from the template for a specific runtime variant."""
    variant = normalize_variant(args.variant) or VARIANT_NODE22
    node_version = args.node_version or EXPECTED_RUNTIME_NODE_VERSION[variant]
    template = read_text(args.template)
    replacements = {
        "@VERSION@": args.version,
        "@MAINTAINER@": args.maintainer,
        "@INSTALLED_SIZE@": str(args.installed_size),
        "@NODE_VERSION@": node_version,
        "@VARIANT_DESCRIPTION@": VARIANT_CONTROL_DESCRIPTION[variant],
    }
    text = template
    for key, value in replacements.items():
        text = text.replace(key, value)
    if re.search(r"@[A-Z_]+@", text):
        raise SystemExit(
            "render-control: unsubstituted placeholder remains in rendered control"
        )
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"render-control: variant={variant} node={node_version} -> {args.out}")
    return 0


def _check_runtime_profile(checks, ctx, extract_dir, variant=VARIANT_NODE22):
    """Reject runtime artifacts whose build/capabilities cannot run the CLI.

    Device-verified requirements (iPhone SE 2, iOS 16.1.1, Dopamine rootless):
    * the OpenCode CLI bundle uses Unicode property escapes and Intl (including
      Intl.Segmenter), so `--with-intl=none` fails at parse time, and full-icu is
      the intended build (small-icu trims Intl data and Intl.Segmenter is known
      to misbehave);
    * Node's built-in fetch/undici needs WebAssembly (wasm llhttp), and the
      jitless/no-wasm runtimes made every CLI command fail on device with
      `ReferenceError: WebAssembly is not defined`. WebAssembly and JIT must be
      enabled with the device-verified 2-key entitlements;
    * for the Node 22 variant an iOS V8 W^X patch (0004/0005) is required; the
      Node 18 variant (V8 10.2 memory model) is device-proven and does not need
      those Node-22-only patches.
    """
    runtime_dir = Path(extract_dir) / "var/jb/usr/lib/opencode/runtime"
    manifest_path = runtime_dir / "runtime-manifest.json"
    metrics = ctx["metrics"]
    if not manifest_path.is_file():
        check(checks, "runtime.build-profile", "runtime",
              "Runtime build/capability profile is usable by the CLI", "SKIP",
              "runtime-manifest.json missing; cannot inspect configure flags")
        return
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        check(checks, "runtime.build-profile", "runtime",
              "Runtime build/capability profile is usable by the CLI", "FAIL",
              f"cannot parse runtime-manifest.json: {exc}")
        return
    build = manifest.get("build") if isinstance(manifest, dict) else None
    flags = build.get("configure_flags") if isinstance(build, dict) else None
    policy = manifest.get("runtime_policy") if isinstance(manifest, dict) else None
    if not isinstance(policy, dict):
        policy = {}
    flags_declared = isinstance(flags, list) and bool(flags)
    flags = [str(flag) for flag in flags] if flags_declared else []
    metrics["runtime_configure_flags"] = flags
    metrics["runtime_node_version"] = (
        manifest.get("node_version") if isinstance(manifest, dict) else ""
    ) or ""
    metrics["runtime_variant"] = variant
    metrics["runtime_jit_memory"] = policy.get("jit_memory") if isinstance(policy, dict) else None
    # Machine-readable producer guidance: the runtime manifest may declare
    # device-verification status and the launcher flags it requires.
    launcher_policy = policy.get("launcher") if isinstance(policy, dict) else None
    required_flags = []
    if isinstance(launcher_policy, dict):
        required_flags = [
            str(flag) for flag in launcher_policy.get("required_flags", [])
            if isinstance(flag, str) and flag.strip()
        ]
    metrics["runtime_launcher_required_flags"] = required_flags
    metrics["runtime_device_status"] = (
        str(manifest.get("device_status", "")) if isinstance(manifest, dict) else ""
    )
    metrics["runtime_device_verification"] = (
        manifest.get("device_verification") if isinstance(manifest, dict) else None
    )
    problems = []
    notes = []
    if required_flags:
        launcher_path = Path(extract_dir) / "var/jb/usr/bin/opencode"
        if launcher_path.is_file():
            launcher_text = read_text(launcher_path)
            launcher_code = "\n".join(
                line for line in launcher_text.splitlines()
                if not line.lstrip().startswith("#")
            )
            missing_flags = [flag for flag in required_flags if flag not in launcher_code]
            if missing_flags:
                problems.append(
                    "launcher is missing launcher flags required by the runtime "
                    "manifest (runtime_policy.launcher.required_flags): "
                    + ", ".join(missing_flags)
                )
            else:
                notes.append(
                    "launcher passes manifest-required flags: " + ", ".join(required_flags)
                )
    elif variant == VARIANT_NODE22:
        notes.append("runtime manifest does not declare launcher.required_flags")

    # ---- node26 requires node:ffi (OpenTUI renderer) ---------------------
    # The Phase A/B runtime artifacts are built --without-ffi and cannot load the
    # OpenTUI dylib; the Phase C FFI-enabled runtime is required for this variant.
    if variant == VARIANT_NODE26:
        build_manifest = manifest.get("build") if isinstance(manifest, dict) else None
        ffi_support = ""
        ffi_build = None
        if isinstance(build_manifest, dict):
            ffi_support = str(build_manifest.get("ffi_support", "") or "")
            ffi_build = build_manifest.get("ffi")
        ffi_disabled = (
            (flags_declared and any("--without-ffi" in flag for flag in flags))
            or "disabled" in ffi_support.lower()
            or (isinstance(ffi_build, dict) and ffi_build.get("supported") is False)
            or (isinstance(ffi_build, dict) and ffi_build.get("enabled") is False)
        )
        metrics["runtime_ffi_disabled"] = ffi_disabled
        allow_non_ffi = bool(ctx.get("allow_non_ffi_runtime"))
        if ffi_disabled and allow_non_ffi:
            notes.append(
                "FFI DISABLED — PIPELINE-PREP artifact only: node:ffi cannot load "
                "the OpenTUI renderer, so the real TUI will NOT work; replace the "
                "runtime with the Phase C FFI-enabled build for the acceptance artifact"
            )
            metrics["runtime_ffi_gate"] = "prep-bypass"
        elif ffi_disabled:
            problems.append(
                "node26 runtime is NOT FFI-enabled (--without-ffi / ffi_support "
                "disabled): node:ffi cannot load the OpenTUI renderer. Use the "
                "Phase C FFI-enabled ios-node26-runtime artifact (or dispatch the "
                "prep build with allow_non_ffi_runtime=true for pipeline validation)."
            )
        elif ffi_support or ffi_build:
            notes.append(
                "node:ffi declared FFI-capable (required for the OpenTUI renderer)"
            )
            metrics["runtime_ffi_gate"] = "enabled"
        else:
            notes.append("runtime FFI support not declared (unverified)")
            metrics["runtime_ffi_gate"] = "unverified"
    device_verification = metrics["runtime_device_verification"]
    if isinstance(device_verification, dict) and device_verification.get("verified") is True:
        notes.append(
            "runtime manifest declares DEVICE-VERIFIED evidence "
            f"(sha256={str(device_verification.get('verified_sha256', ''))[:16]}…, "
            f"launcher_flags={device_verification.get('launcher_flags', [])})"
        )

    if not flags_declared:
        if variant in (VARIANT_NODE22, VARIANT_NODE26):
            problems.append(
                "runtime-manifest.json does not declare build.configure_flags "
                f"(required for the {VARIANT_LABELS[variant]} variant)"
            )
        else:
            notes.append("build.configure_flags not declared (Node 18 runtime)")

    # ---- ICU / Intl ------------------------------------------------------
    full_icu = any("--with-intl=full-icu" in flag for flag in flags)
    other_icu = any("--with-intl=small-icu" in flag for flag in flags)
    if flags_declared:
        if any("--with-intl=none" in flag for flag in flags):
            problems.append(
                "runtime was configured with --with-intl=none: Intl is unavailable "
                "and V8 rejects the Unicode property escapes used by the OpenCode CLI "
                "bundle (device-verified parse failure). Rebuild with "
                "--with-intl=full-icu (preferred; small-icu only if it demonstrably "
                "supports Intl.Segmenter)."
            )
        elif not (full_icu or other_icu):
            problems.append(
                "runtime does not declare an ICU build (--with-intl=full-icu); the CLI "
                "requires Intl support, including Intl.Segmenter."
            )
    intl_policy = policy.get("intl") if isinstance(policy.get("intl"), dict) else None
    if intl_policy is None:
        problems.append(
            "runtime-manifest.json does not declare runtime_policy.intl; an ICU "
            "build is required (Intl + Intl.Segmenter are used by the CLI)."
        )
    else:
        intl_mode = str(intl_policy.get("mode", ""))
        icu_version = str(intl_policy.get("icu_version", ""))
        if "none" in intl_mode.lower() or intl_mode.lower() in ("", "unknown"):
            problems.append(
                f"runtime_policy.intl.mode={intl_mode!r}: an ICU build is required"
            )
        if not icu_version:
            if variant == VARIANT_NODE22:
                problems.append("runtime_policy.intl.icu_version is not declared")
            else:
                notes.append("ICU version not declared (full-icu mode declared)")

    # ---- WebAssembly (required by Node fetch/undici) ---------------------
    wasm_policy = policy.get("webassembly")
    if wasm_policy is None:
        problems.append(
            "runtime-manifest.json does not declare runtime_policy.webassembly; the "
            "runtime must declare and enable WebAssembly (Node's fetch/undici needs "
            "wasm llhttp — a no-wasm runtime makes every CLI command fail with "
            "'ReferenceError: WebAssembly is not defined', device-verified)."
        )
    elif not _capability_enabled(wasm_policy):
        problems.append(
            f"runtime_policy.webassembly={wasm_policy!r}: WebAssembly must be enabled "
            "(Node fetch/undici requires it; no-wasm runtime fails on device)."
        )

    # ---- JIT (required for Wasm code generation; 2-key entitlements suffice)
    jit_policy = policy.get("v8_jit")
    if flags_declared and any("--v8-options=--jitless" in flag for flag in flags):
        problems.append(
            "--v8-options=--jitless is set: the shipped runtime must have JIT enabled "
            "(device verified the 2-key entitlement set permits JIT; WebAssembly needs "
            "executable memory)."
        )
    elif jit_policy is None:
        problems.append(
            "runtime-manifest.json does not declare runtime_policy.v8_jit; the runtime "
            "must declare JIT enabled."
        )
    elif not _capability_enabled(jit_policy):
        problems.append(
            f"runtime_policy.v8_jit={jit_policy!r}: JIT must be enabled for this runtime."
        )

    # ---- iOS target flags ------------------------------------------------
    if flags_declared:
        if not any("--dest-os=ios" in flag for flag in flags):
            problems.append("--dest-os=ios missing from configure flags")
        if not any("--dest-cpu=arm64" in flag for flag in flags):
            problems.append("--dest-cpu=arm64 missing from configure flags")

    # ---- iOS V8 W^X patch ------------------------------------------------
    # Node 22 v3/v4 builds without a working iOS W^X memory model trapped on
    # device; Node 26 (V8 14.6) needs its own mprotect W^X patch (patch 0007 in
    # nodejs26-ios). The Node 18 variant uses the V8 10.2 memory model that is
    # device-proven by the community build and does not need those patches.
    source = manifest.get("source") if isinstance(manifest, dict) else None
    patches = source.get("patches") if isinstance(source, dict) else None
    patch_files = ([str(item.get("file", "")) for item in patches
                    if isinstance(item, dict)] if isinstance(patches, list) else None)
    jit_enabled = _capability_enabled(jit_policy)
    # Accepted iOS V8 W^X patch families: patch 0004 (MAP_JIT write-protect),
    # 0005 (no MAP_JIT on iOS), 0006/0007 (mprotect RW<->RX toggling).
    wx_patch_names = ("jit-write-protect", "no-map-jit", "map-jit", "mprotect", "w^x")
    wx_patch_declared = bool(
        patch_files and any(
            any(marker in name.lower() for marker in wx_patch_names)
            for name in patch_files
        )
    )
    if patch_files is not None:
        metrics["runtime_patches"] = patch_files
    if variant in (VARIANT_NODE22, VARIANT_NODE26):
        if patch_files is not None and jit_enabled and not wx_patch_declared:
            problems.append(
                f"JIT-enabled {VARIANT_LABELS[variant]} runtime manifest does not list "
                "an iOS V8 W^X patch (Node 22: 0004/0005/0006 family; Node 26: "
                "patches/nodejs26/0007-v8-ios-mprotect-wx.patch); pre-W^X builds "
                "trapped on generated code on the device."
            )
        elif patch_files is None:
            notes.append("W^X patch presence not declared (unverified)")
        if variant == VARIANT_NODE26:
            notes.append(
                "Node 26 V8 14.6 mprotect W^X model (patch 0007 family): launcher "
                "MUST pass --single-threaded (process-wide toggle vs V8 background threads)"
            )
    else:
        notes.append(
            "Node 18 V8 10.2 memory model (device-proven); Node 22/26 W^X patch not required"
        )

    if problems:
        check(checks, "runtime.build-profile", "runtime",
              "Runtime build/capability profile is usable by the CLI", "FAIL",
              truncate("; ".join(problems), 1500))
    else:
        detail = f"variant={variant}"
        if flags:
            detail += "; configure flags: " + truncate(", ".join(flags), 500)
        if full_icu:
            detail += "; full-icu (preferred for Intl.Segmenter)"
        elif other_icu:
            detail += "; small-icu accepted (confirm Intl.Segmenter on device)"
        if intl_policy is not None:
            detail += f"; ICU {intl_policy.get('icu_version', 'declared')}"
        detail += "; WebAssembly enabled; JIT enabled"
        if wx_patch_declared:
            detail += "; iOS V8 W^X patch declared"
        for note in notes:
            detail += f"; {note}"
        metrics["runtime_capabilities"] = {
            "variant": variant,
            "node_version": metrics["runtime_node_version"],
            "intl_mode": (intl_policy or {}).get("mode"),
            "icu_version": (intl_policy or {}).get("icu_version"),
            "webassembly": wasm_policy,
            "v8_jit": jit_policy,
            "jit_wx_patch_declared": wx_patch_declared,
        }
        check(checks, "runtime.build-profile", "runtime",
              "Runtime build/capability profile is usable by the CLI", "PASS", detail)


def _check_optional_ripgrep(checks, ctx, extract_dir, skip_native, mode):
    rg = Path(extract_dir) / "var/jb/usr/bin/rg"
    metrics = ctx["metrics"]
    if not rg.is_file():
        check(checks, "runtime.ripgrep", "runtime",
              "Optional bundled ripgrep (ios-ripgrep) is valid if present", "SKIP",
              "optional ios-ripgrep artifact was not available; /var/jb/usr/bin/rg not shipped")
        metrics["ripgrep"] = {"included": False}
        return
    metrics["ripgrep"] = {"included": True, "sha256": sha256_file(rg), "size": rg.stat().st_size}
    if skip_native:
        check(checks, "runtime.ripgrep", "runtime",
              "Optional bundled ripgrep (ios-ripgrep) is valid if present", "SKIP",
              "present but native audit skipped by --skip-native-audit")
        return
    auditor, import_error = _load_macho_auditor(Path(ctx["repo_root"])) if ctx.get("repo_root") else (None, "no repo root")
    problems = []
    if auditor is None:
        problems.append(f"cannot import check_macho: {import_error}")
    else:
        try:
            minos = auditor(rg, (16, 1, 1))
            metrics["ripgrep"]["minos"] = ".".join(str(p) for p in minos)
        except ValueError as exc:
            problems.append(f"check_macho rejected rg: {exc}")
    try:
        libs = _otool_libs(rg)
        violations = _validate_dylibs(libs)
        if violations:
            problems.append("dylib violations: " + "; ".join(violations[:5]))
        metrics["ripgrep"]["dylibs"] = libs
    except RuntimeError as exc:
        problems.append(str(exc))
    if problems:
        check(checks, "runtime.ripgrep", "runtime",
              "Optional bundled ripgrep (ios-ripgrep) is valid if present", "FAIL",
              truncate("; ".join(problems), 1200))
    else:
        check(checks, "runtime.ripgrep", "runtime",
              "Optional bundled ripgrep (ios-ripgrep) is valid if present", "PASS",
              f"iPhoneOS arm64 Mach-O, minOS={metrics['ripgrep'].get('minos', '?')}, "
              f"only iOS system libraries; sha256={metrics['ripgrep']['sha256'][:16]}...")


# --------------------------------------------------------------------------
# CLI checks
# --------------------------------------------------------------------------
def _check_optional_jitshim(checks, ctx, extract_dir, skip_native):
    """Audit the optional jailbreak JIT interposer shim if it is shipped.

    The shim (artifact `ios-jit-shim`) relaxes W^X for V8 JIT on jailed iOS; the
    launcher injects it via DYLD_INSERT_LIBRARIES only when present. It is a
    dylib (not an executable), so the executable Mach-O auditor does not apply.
    """
    runtime_dir = Path(extract_dir) / "var/jb/usr/lib/opencode/runtime"
    shim = runtime_dir / "libjitshim.dylib"
    metrics = ctx["metrics"]
    if not shim.is_file():
        metrics["jitshim"] = {"included": False}
        check(checks, "runtime.jitshim", "runtime",
              "Optional jailbreak JIT shim (ios-jit-shim) is valid if present", "SKIP",
              "optional ios-jit-shim artifact was not shipped; the launcher will "
              "not set DYLD_INSERT_LIBRARIES (normal launch)")
        return
    metrics["jitshim"] = {
        "included": True,
        "sha256": sha256_file(shim),
        "size": shim.stat().st_size,
    }
    info = _macho_info(shim) or {}
    metrics["jitshim"].update(
        platform=info.get("platform"),
        arch=info.get("arch"),
        filetype=info.get("filetype"),
        minos=info.get("minos"),
    )
    problems = []
    if info.get("platform") != "iOS":
        problems.append(
            f"Mach-O platform {info.get('platform')!r} (requires iPhoneOS/iOS)"
        )
    if info.get("filetype") != 6:
        problems.append(
            f"Mach-O filetype {info.get('filetype')!r} (requires MH_DYLIB=6)"
        )
    if info.get("arch") != hex(0x0100000C):
        problems.append(f"Mach-O arch {info.get('arch')!r} (requires arm64)")
    launcher = Path(extract_dir) / "var/jb/usr/bin/opencode"
    if launcher.is_file():
        launcher_text = read_text(launcher)
        if "DYLD_INSERT_LIBRARIES" not in launcher_text or \
                "libjitshim.dylib" not in launcher_text:
            problems.append(
                "launcher does not conditionally inject libjitshim.dylib via "
                "DYLD_INSERT_LIBRARIES"
            )
    if skip_native:
        metrics["jitshim"]["dylibs"] = None
        if problems:
            check(checks, "runtime.jitshim", "runtime",
                  "Optional jailbreak JIT shim (ios-jit-shim) is valid if present",
                  "FAIL", truncate("; ".join(problems), 1000))
        else:
            check(checks, "runtime.jitshim", "runtime",
                  "Optional jailbreak JIT shim (ios-jit-shim) is valid if present",
                  "SKIP", "shim present but native dylib audit skipped "
                          "(--skip-native-audit)")
        return
    try:
        libs = _otool_libs(shim)
        violations = _validate_dylibs(libs)
        if violations:
            problems.append("dylib violations: " + "; ".join(violations[:5]))
        metrics["jitshim"]["dylibs"] = libs
    except RuntimeError as exc:
        problems.append(str(exc))
    if problems:
        check(checks, "runtime.jitshim", "runtime",
              "Optional jailbreak JIT shim (ios-jit-shim) is valid if present", "FAIL",
              truncate("; ".join(problems), 1200))
    else:
        check(checks, "runtime.jitshim", "runtime",
              "Optional jailbreak JIT shim (ios-jit-shim) is valid if present", "PASS",
              f"iPhoneOS arm64 MH_DYLIB, minOS={info.get('minos') or '?'}, only iOS "
              f"system libraries; sha256={metrics['jitshim']['sha256'][:16]}...; "
              "jailbreak JIT W^X interposer injected conditionally by the launcher")


# --------------------------------------------------------------------------
# CLI checks
# --------------------------------------------------------------------------
def _check_cli(checks, ctx, extract_dir, mode, variant=VARIANT_NODE22):
    cli_dir = Path(extract_dir) / "var/jb/usr/lib/opencode/cli"
    mjs = cli_dir / "opencode.mjs"
    assets = cli_dir / "assets"
    metrics = ctx["metrics"]
    if not mjs.is_file():
        check(checks, "cli.bundle", "cli", "OpenCode CLI bundle present", "FAIL",
              "var/jb/usr/lib/opencode/cli/opencode.mjs missing")
        return
    mjs_size = mjs.stat().st_size
    asset_files = [
        path for path in assets.rglob("*") if path.is_file()
    ] if assets.is_dir() else []
    asset_bytes = sum(path.stat().st_size for path in asset_files)
    metrics["cli"] = {
        "variant": variant,
        "opencode_mjs_sha256": sha256_file(mjs),
        "opencode_mjs_size": mjs_size,
        "assets_file_count": len(asset_files),
        "assets_bytes": asset_bytes,
        "bundle_manifest_sha256": sha256_file(cli_dir / "bundle-manifest.json")
        if (cli_dir / "bundle-manifest.json").is_file() else "",
    }
    problems = []
    min_mjs = 256 if mode == "self-test" else REAL_MJS_MIN_BYTES
    if mjs_size < min_mjs:
        problems.append(f"opencode.mjs is only {mjs_size} bytes (< {min_mjs}); placeholder?")
    if not assets.is_dir():
        problems.append("cli/assets directory missing")
    bundle_text = read_text(mjs, limit=32 * 1024 * 1024)
    if mode != "self-test" and "opencode" not in bundle_text.lower():
        problems.append("bundle does not look like OpenCode (name not found)")
    if mode != "self-test" and variant == VARIANT_NODE18:
        sqlite_dir = assets / "node18-sqlite"
        for name in ("sql-wasm.js", "sql-wasm.wasm"):
            sqlite_asset = sqlite_dir / name
            if not sqlite_asset.is_file() or sqlite_asset.stat().st_size == 0:
                problems.append(
                    f"Node 18 sql.js asset missing/empty: cli/assets/node18-sqlite/{name}"
                )
        metrics["cli"]["sqljs_assets"] = sorted(
            path.name for path in sqlite_dir.rglob("*") if path.is_file()
        ) if sqlite_dir.is_dir() else []
    if mode != "self-test" and variant == VARIANT_NODE26:
        opentui_asset = cli_dir / OPENTUI_REL_PATH.split(
            "var/jb/usr/lib/opencode/cli/", 1
        )[1]
        if not opentui_asset.is_file() or opentui_asset.stat().st_size == 0:
            problems.append(
                f"OpenTUI renderer asset missing/empty: cli/{OPENTUI_REL_PATH.split('cli/', 1)[1]}"
            )
        else:
            metrics["cli"]["opentui_asset_sha256"] = sha256_file(opentui_asset)
            metrics["cli"]["opentui_asset_size"] = opentui_asset.stat().st_size
            metrics["cli"]["opentui_asset_mode"] = oct(
                opentui_asset.stat().st_mode & 0o777
            )
            if opentui_asset.stat().st_size < 100_000:
                problems.append("OpenTUI renderer dylib is suspiciously small (placeholder?)")
    if problems:
        check(checks, "cli.bundle", "cli", "OpenCode CLI bundle present", "FAIL",
              truncate("; ".join(problems), 1200))
    else:
        extra = ""
        if variant == VARIANT_NODE18:
            extra = " with bundled sql.js sqlite shim (assets/node18-sqlite)"
        elif variant == VARIANT_NODE26:
            extra = (
                " with OpenTUI iOS renderer "
                f"(cli/assets/@opentui/core-ios-arm64/libopentui.dylib, "
                f"sha256={metrics['cli'].get('opentui_asset_sha256', '')[:16]}...)"
            )
        check(checks, "cli.bundle", "cli", "OpenCode CLI bundle present", "PASS",
              f"opencode.mjs {mjs_size} bytes sha256={metrics['cli']['opencode_mjs_sha256'][:16]}...; "
              f"{len(asset_files)} asset file(s), {asset_bytes} bytes{extra}")

    # Non-SEA asset-loading contract: the launcher exports
    # OPENCODE_NODE_ASSETS_DIR (verified in pkg.launcher); the bundle either
    # reads that variable or the CLI artifact's bundle-manifest declares the
    # same launcher env contract.
    bundle_manifest_path = cli_dir / "bundle-manifest.json"
    declared_env = ""
    if bundle_manifest_path.is_file():
        try:
            declared_env = json.dumps(read_json(bundle_manifest_path).get("env_contract", {}))
        except (OSError, ValueError):
            declared_env = ""
    if "OPENCODE_NODE_ASSETS_DIR" in bundle_text:
        check(checks, "cli.assets-contract", "cli",
              "Non-SEA assets directory contract is wired up", "PASS",
              "opencode.mjs references OPENCODE_NODE_ASSETS_DIR; launcher exports it")
    elif "OPENCODE_NODE_ASSETS_DIR" in declared_env:
        check(checks, "cli.assets-contract", "cli",
              "Non-SEA assets directory contract is wired up", "SKIP",
              "bundle-manifest declares OPENCODE_NODE_ASSETS_DIR in its env contract "
              "(prelude may derive assets from opencode.mjs location); device behaviour "
              "must be confirmed by the device runbook")
    else:
        check(checks, "cli.assets-contract", "cli",
              "Non-SEA assets directory contract is wired up", "SKIP",
              "neither opencode.mjs nor bundle-manifest references OPENCODE_NODE_ASSETS_DIR; "
              "asset resolution relies on prelude defaults")


def _macho_info(path):
    """Return Mach-O platform/arch metadata for a file, or None when not Mach-O."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
            if len(head) < 28:
                return None
            magic_le = struct.unpack_from("<I", head, 0)[0]
            if magic_le in (0xFEEDFACF, 0xFEEDFACE):
                is_64 = magic_le == 0xFEEDFACF
                cpu_type = struct.unpack_from("<I", head, 4)[0]
                file_type = struct.unpack_from("<I", head, 12)[0]
                ncmds = struct.unpack_from("<I", head, 16)[0]
                sizeofcmds = struct.unpack_from("<I", head, 20)[0]
                header_size = 32 if is_64 else 28
                if ncmds > 10000 or sizeofcmds > 16 * 1024 * 1024:
                    return {"arch": hex(cpu_type), "filetype": file_type,
                            "platform": "unknown", "minos": None, "fat": False}
                commands = handle.read(sizeofcmds)
            elif magic_le == 0xBEBAFECA:  # FAT_CIGAM: fat binary, big-endian header
                return {"arch": "fat", "filetype": None, "platform": "fat",
                        "minos": None, "fat": True}
            else:
                return None
    except OSError:
        return None
    if len(commands) != sizeofcmds:
        return None
    pos = 0
    platform = None
    minos = None
    for _ in range(ncmds):
        if pos + 8 > len(commands):
            break
        cmd, size = struct.unpack_from("<II", commands, pos)
        if size < 8 or pos + size > len(commands):
            break
        if cmd == 0x32 and size >= 24:  # LC_BUILD_VERSION
            plat, min_version = struct.unpack_from("<II", commands, pos + 8)
            platform = {1: "macOS", 2: "iOS", 3: "tvOS", 4: "watchOS",
                        6: "iOSSimulator", 7: "tvOSSimulator",
                        8: "watchOSSimulator", 9: "macCatalyst"}.get(plat, f"platform({plat})")
            parts = ((min_version >> 16) & 0xFFFF, (min_version >> 8) & 0xFF,
                     min_version & 0xFF)
            minos = ".".join(str(part) for part in parts)
            break
        if cmd == 0x25 and size >= 16:  # LC_VERSION_MIN_IPHONEOS
            min_version = struct.unpack_from("<I", commands, pos + 8)[0]
            platform = "iOS"
            parts = ((min_version >> 16) & 0xFFFF, (min_version >> 8) & 0xFF,
                     min_version & 0xFF)
            minos = ".".join(str(part) for part in parts)
            break
        pos += size
    return {"arch": hex(cpu_type), "filetype": file_type, "platform": platform,
            "minos": minos, "fat": False}


def _check_artifact_policy(checks, ctx, cli_dir, variant=VARIANT_NODE22):
    """Gate the CLI artifact on the producer's iOS-patch/smoke policy metadata."""
    expected_node = EXPECTED_RUNTIME_NODE_VERSION[variant]
    title = (f"CLI artifact is an iOS candidate (patch series + Node {expected_node} smoke)")
    metrics = ctx["metrics"]
    manifest_path = cli_dir / "bundle-manifest.json"
    if not manifest_path.is_file():
        check(checks, "cli.artifact-policy", "cli", title,
              "SKIP", "opencode-cli artifact did not ship bundle-manifest.json")
        return
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        check(checks, "cli.artifact-policy", "cli", title,
              "FAIL", f"cannot parse bundle-manifest.json: {exc}")
        return
    build = manifest.get("build", {}) if isinstance(manifest, dict) else {}
    status = manifest.get("verification_status", {}) if isinstance(manifest, dict) else {}
    notes = manifest.get("notes", []) if isinstance(manifest, dict) else []
    notes_text = " | ".join(str(note) for note in notes)
    required_node = status.get("host_smoke_required_node_version")
    required_passed = status.get("host_smoke_required_passed")
    build_variant = str(build.get("variant", "")) if isinstance(build, dict) else ""
    metrics["cli_artifact_policy"] = {
        "variant": variant,
        "artifact_variant": build_variant,
        "ios_prelude": build.get("ios_prelude") if isinstance(build, dict) else None,
        "host_smoke_required_node_version": required_node,
        "host_smoke_required_passed": required_passed,
        "stock_build": "STOCK upstream build" in notes_text,
        "sqlite": build.get("sqlite") if isinstance(build, dict) else None,
    }
    problems = []
    if "STOCK upstream build" in notes_text:
        problems.append(
            "artifact is a STOCK upstream build without the iOS patch series "
            "(bundle-manifest notes say it is expected to fail on the iPhoneOS runtime)"
        )
    if required_passed is False:
        problems.append("the producer's required host-Node smoke test did not pass")
    if required_node and str(required_node) != expected_node:
        problems.append(
            f"artifact was smoke-required on Node {required_node}, but the selected "
            f"variant ships the Node {expected_node} runtime"
        )
    if variant == VARIANT_NODE18:
        if "18" not in build_variant:
            problems.append(
                f"bundle build.variant={build_variant!r} does not declare the Node 18 "
                "fallback variant"
            )
        if not build.get("sqlite"):
            problems.append(
                "Node 18 bundle manifest does not declare the bundled sql.js sqlite shim"
            )
    elif variant == VARIANT_NODE26:
        if "26" not in build_variant:
            problems.append(
                f"bundle build.variant={build_variant!r} does not declare the "
                "experimental Node 26 variant"
            )
        runtime_node_version = (
            str(build.get("runtime_node_version", "")) if isinstance(build, dict) else ""
        )
        if runtime_node_version and not runtime_node_version.startswith("26."):
            problems.append(
                f"bundle build.runtime_node_version={runtime_node_version!r} is not a "
                "Node 26 runtime (experimental node26 bundle required)"
            )
        # The node26 bundle ships the OpenTUI renderer itself; the manifest must
        # declare it and its hash must match the pinned Phase C artifact.
        opentui_decl = (
            manifest.get("opentui_renderer") if isinstance(manifest, dict) else None
        )
        metrics["cli_artifact_policy"]["opentui_renderer"] = opentui_decl
        if not isinstance(opentui_decl, dict):
            problems.append(
                "node26 bundle manifest does not declare top-level "
                "opentui_renderer provenance"
            )
        else:
            opentui_asset = str(
                opentui_decl.get("asset")
                or opentui_decl.get("asset_key")
                or opentui_decl.get("key")
                or opentui_decl.get("path")
                or ""
            )
            if "@opentui/core-ios-arm64/libopentui.dylib" not in opentui_asset:
                problems.append(
                    "bundle opentui_renderer does not declare the "
                    "@opentui/core-ios-arm64/libopentui.dylib asset key"
                )
            if opentui_decl.get("sha256_matches_expected") is not True:
                problems.append(
                    "bundle opentui_renderer.sha256_matches_expected is not true "
                    "(renderer does not match the pinned Phase C artifact)"
                )
        env_contract = (
            manifest.get("env_contract") if isinstance(manifest, dict) else None
        )
        env_text = json.dumps(env_contract) if env_contract else ""
        if "OTUI_ASSET_ROOT" not in env_text:
            problems.append(
                "node26 bundle env_contract does not declare OTUI_ASSET_ROOT for the "
                "OpenTUI renderer resolution"
            )
        argv = (
            env_contract.get("launcher_argv", [])
            if isinstance(env_contract, dict) else []
        )
        if not any("--single-threaded" in str(item) for item in argv):
            problems.append(
                "node26 bundle env_contract.launcher_argv must include "
                "--single-threaded (mandatory on iOS)"
            )
    elif "18" in build_variant.lower() or "26" in build_variant.lower():
        problems.append(
            f"bundle build.variant={build_variant!r} is a Node 18/26 artifact but the "
            "package variant is node22"
        )
    if problems:
        check(checks, "cli.artifact-policy", "cli", title,
              "FAIL", truncate("; ".join(problems), 1200))
    elif required_node:
        check(checks, "cli.artifact-policy", "cli", title,
              "PASS",
              f"bundle-manifest: variant={build_variant or '?'}, "
              f"ios_prelude={build.get('ios_prelude') if isinstance(build, dict) else '?'}, "
              f"required smoke Node {required_node} passed"
              + (", sql.js shim declared" if build.get("sqlite") else ""))
    else:
        check(checks, "cli.artifact-policy", "cli", title,
              "SKIP", "bundle-manifest has no host-smoke version policy metadata")


# --------------------------------------------------------------------------
# OpenTUI renderer checks (experimental node26 variant only)
# --------------------------------------------------------------------------
def _check_opentui(checks, ctx, extract_dir, variant=VARIANT_NODE22,
                   skip_native=False, sources=None):
    """Audit the OpenTUI iOS renderer dylib for the experimental node26 variant."""
    if variant != VARIANT_NODE26:
        check(checks, "cli.opentui-renderer", "cli",
              "OpenTUI iOS renderer is valid (experimental node26 variant)", "SKIP",
              "not shipped for the node22/node18 variants (those use the line REPL)")
        return
    cli_dir = Path(extract_dir) / "var/jb/usr/lib/opencode/cli"
    rel = OPENTUI_REL_PATH.split("var/jb/usr/lib/opencode/cli/", 1)[1]
    dylib = cli_dir / rel
    metrics = ctx["metrics"]
    if not dylib.is_file():
        check(checks, "cli.opentui-renderer", "cli",
              "OpenTUI iOS renderer is valid (experimental node26 variant)", "FAIL",
              f"missing cli/{rel}; the experimental node26 build needs the OpenTUI iOS "
              "renderer (opentui-ios-renderer artifact) under /var/jb so the iOS "
              "dlopen sandbox can map it")
        return
    info = _macho_info(dylib) or {}
    missing_prefix = "var/jb/usr/lib/opencode/cli/"
    metrics["opentui"] = {
        "path": rel,
        "sha256": sha256_file(dylib),
        "size": dylib.stat().st_size,
        "mode": oct(dylib.stat().st_mode & 0o777),
        "platform": info.get("platform"),
        "arch": info.get("arch"),
        "filetype": info.get("filetype"),
        "minos": info.get("minos"),
    }
    problems = []
    if info.get("platform") != "iOS":
        problems.append(f"Mach-O platform {info.get('platform')!r} (requires iPhoneOS/iOS)")
    if info.get("filetype") != 6:
        problems.append(f"Mach-O filetype {info.get('filetype')!r} (requires MH_DYLIB=6)")
    if info.get("arch") != hex(0x0100000C):
        problems.append(f"Mach-O arch {info.get('arch')!r} (requires arm64)")
    minos = info.get("minos")
    if minos and _version_tuple(minos) > _version_tuple("16.1.1"):
        problems.append(f"Mach-O minOS {minos!r} is newer than the iOS 16.1.1 target")
    if os.name == "posix" and metrics["opentui"]["mode"] != "0o755":
        problems.append(
            f"OpenTUI renderer mode {metrics['opentui']['mode']} (expected 0o755)"
        )
    elif os.name != "posix":
        metrics["opentui"]["mode_check"] = "skipped (non-POSIX host cannot represent file modes)"
    # Producer-pinned hash (opentui-ios-renderer SHA256SUMS) if available.
    expected_sha = ""
    if isinstance(metrics.get("opentui_expected_sha256"), str):
        expected_sha = metrics["opentui_expected_sha256"]
    if not expected_sha and isinstance(sources, dict):
        opentui_inputs = sources.get("inputs", {}).get("opentui", {})
        expected_sha = str(opentui_inputs.get("expected_sha256", ""))
    if expected_sha and metrics["opentui"]["sha256"] != expected_sha:
        problems.append(
            f"OpenTUI renderer sha256 {metrics['opentui']['sha256']} does not match "
            f"the pinned producer hash {expected_sha}"
        )
    # Renderer signing (device finding, iOS 16.1.1): dyld maps ldid-signed dylibs
    # non-executable (a renderer function call SIGBUSes with __TEXT r--/rw-), while
    # Apple `codesign`-signed dylibs execute. The renderer must therefore be
    # code-signed (ad-hoc is fine); the ldid 2-key entitlement requirement stays on
    # the node executable only. codesign is the preferred verifier; ldid -e is a
    # fallback that can only confirm *a* signature, not the codesign flavour.
    signature = {
        "checked": False,
        "signed": None,
        "tool": "",
        "adhoc": False,
        "has_platform_application": False,
        "has_no_sandbox": False,
    }
    codesign = shutil.which("codesign")
    ldid = shutil.which("ldid")
    if skip_native:
        signature["checked"] = False
    elif codesign:
        signature["checked"] = True
        signature["tool"] = "codesign"
        try:
            proc = subprocess.run(
                [codesign, "-dv", "--verbose=2", str(dylib)],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f"cannot inspect OpenTUI renderer signature: {exc}")
        else:
            output = (proc.stdout or "") + (proc.stderr or "")
            signed = proc.returncode == 0
            signature["signed"] = signed
            signature["adhoc"] = (
                "Signature=adhoc" in output or "Signature=AdHoc" in output
            )
            if not signed:
                problems.append(
                    "OpenTUI renderer is not codesign-signed: on iOS 16.1.1 dyld "
                    "maps ldid/unsigned dylibs non-executable (renderer function "
                    "calls SIGBUS); the artifact must be codesign-signed (ad-hoc OK)"
                )
            try:
                ent_proc = subprocess.run(
                    [codesign, "-d", "--entitlements", ":-", str(dylib)],
                    capture_output=True, text=True, timeout=60,
                )
            except (OSError, subprocess.SubprocessError):
                entitlements = ""
            else:
                entitlements = (ent_proc.stdout or "") + (ent_proc.stderr or "")
            signature["has_platform_application"] = (
                "platform-application" in entitlements
            )
            signature["has_no_sandbox"] = (
                "com.apple.private.security.no-sandbox" in entitlements
            )
    elif ldid:
        signature["checked"] = True
        signature["tool"] = "ldid"
        try:
            proc = subprocess.run(
                [ldid, "-e", str(dylib)],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f"cannot inspect OpenTUI renderer signature via ldid: {exc}")
        else:
            signature["signed"] = proc.returncode == 0
            entitlements = proc.stdout or ""
            signature["has_platform_application"] = "platform-application" in entitlements
            signature["has_no_sandbox"] = (
                "com.apple.private.security.no-sandbox" in entitlements
            )
            # ldid is not a valid signing method for executable renderer dylibs on
            # this device, so this host cannot prove the required codesign signature.
            check(checks, "cli.opentui-renderer-signature", "cli",
                  "OpenTUI renderer is code-signed for executable mapping", "SKIP",
                  "codesign is unavailable on this host (CI uses macOS codesign); "
                  "ldid can only report the entitlements, and ldid-signed renderer "
                  "dylibs are known to map non-executable on iOS 16.1.1")
    else:
        signature["checked"] = False
        check(checks, "cli.opentui-renderer-signature", "cli",
              "OpenTUI renderer is code-signed for executable mapping", "SKIP",
              "neither codesign nor ldid is available on this host")
    if signature["checked"] and signature["tool"] == "codesign":
        ent = (
            f"platform-application={signature['has_platform_application']}, "
            f"no-sandbox={signature['has_no_sandbox']}"
        )
        if signature["signed"]:
            check(checks, "cli.opentui-renderer-signature", "cli",
                  "OpenTUI renderer is code-signed for executable mapping", "PASS",
                  f"codesign-verified signature (adhoc={signature['adhoc']}); {ent}; "
                  "ldid-signed renderer dylibs map non-executable on iOS 16.1.1 "
                  "(device finding) — codesign is required for the executable renderer")
        else:
            check(checks, "cli.opentui-renderer-signature", "cli",
                  "OpenTUI renderer is code-signed for executable mapping", "FAIL",
                  "codesign reports no valid signature")
    metrics["opentui"]["signature"] = signature
    if skip_native:
        metrics["opentui"]["dylibs"] = None
    else:
        try:
            libs = _otool_libs(dylib)
            # Drop the dylib's own LC_ID_DYLIB install name (@rpath/libopentui.dylib).
            libs = [lib for lib in libs if not lib.endswith("libopentui.dylib")]
            violations = _validate_dylibs(libs)
            if violations:
                problems.append("dylib violations: " + "; ".join(violations[:5]))
            metrics["opentui"]["dylibs"] = libs
        except RuntimeError as exc:
            metrics["opentui"]["dylibs"] = None
            problems.append(str(exc))
    title = "OpenTUI iOS renderer is valid (experimental node26 variant)"
    if problems:
        check(checks, "cli.opentui-renderer", "cli", title, "FAIL",
              truncate("; ".join(problems), 1200))
    else:
        sig = metrics["opentui"].get("signature", {})
        sig_text = ""
        if sig.get("checked") and sig.get("tool") == "codesign":
            sig_text = (
                f"codesign-signed (adhoc={sig.get('adhoc')}, "
                f"platform-application={sig.get('has_platform_application')}, "
                f"no-sandbox={sig.get('has_no_sandbox')}); "
            )
        elif sig.get("checked"):
            sig_text = f"signature inspected with {sig.get('tool')} (codesign not available); "
        check(checks, "cli.opentui-renderer", "cli", title, "PASS",
              f"iPhoneOS arm64 MH_DYLIB minOS {info.get('minos') or '?'} mode 0755; "
              f"sha256={metrics['opentui']['sha256'][:16]}...; {sig_text}"
              "only iOS system frameworks/libraries; installed under "
              f"{NODE26_ASSET_ROOT} (device-verified runtime asset root for a "
              "codesign-signed renderer); device TUI load is UNVERIFIED ON DEVICE "
              "until the Lead's Phase D run")


def _check_assets_native(checks, ctx, cli_dir):
    """No macOS/desktop Mach-O binaries may be shipped as iOS CLI assets."""
    assets_root = cli_dir / "assets"
    metrics = ctx["metrics"]
    native = []
    if assets_root.is_dir():
        for path in sorted(assets_root.rglob("*")):
            if not path.is_file():
                continue
            info = _macho_info(path)
            if info is None:
                continue
            native.append({
                "path": path.relative_to(cli_dir).as_posix(),
                "platform": info.get("platform"),
                "arch": info.get("arch"),
                "filetype": info.get("filetype"),
                "minos": info.get("minos"),
            })
    metrics["cli"]["native_assets"] = native
    ios_ok = [item for item in native if item["platform"] == "iOS"]
    violations = [item for item in native if item["platform"] != "iOS"]
    if violations:
        detail = ", ".join(
            f"{item['path']} ({item['platform'] or 'unknown'} {item['arch']})"
            for item in violations[:10]
        )
        check(checks, "cli.native-assets", "cli",
              "No desktop Mach-O binaries are shipped as CLI assets", "FAIL",
              f"{len(violations)} non-iOS native binary file(s) in assets/: {detail}. "
              "The iOS patch series must remove desktop native addons; they are not "
              "loadable on iPhoneOS and must not be packaged.")
    elif native:
        check(checks, "cli.native-assets", "cli",
              "No desktop Mach-O binaries are shipped as CLI assets", "PASS",
              f"{len(native)} Mach-O asset file(s), all iPhoneOS-platform")
    else:
        check(checks, "cli.native-assets", "cli",
              "No desktop Mach-O binaries are shipped as CLI assets", "PASS",
              "assets/ contains no Mach-O native binaries (JS/Wasm/data only)")


def _check_host_smoke(checks, ctx, host_smoke_path, variant=VARIANT_NODE22):
    expected_node = "v" + EXPECTED_RUNTIME_NODE_VERSION[variant]
    smoke_title = f"CLI bundle runs on the host Node.js {EXPECTED_RUNTIME_NODE_VERSION[variant]} runtime"
    metrics = ctx["metrics"]
    if not host_smoke_path or not Path(host_smoke_path).is_file():
        check(checks, "cli.host-node-smoke", "cli",
              smoke_title, "FAIL",
              f"host smoke JSON not found: {host_smoke_path}")
        return
    try:
        smoke = read_json(host_smoke_path)
    except (OSError, ValueError) as exc:
        check(checks, "cli.host-node-smoke", "cli",
              smoke_title, "FAIL",
              f"cannot parse host smoke JSON: {exc}")
        return
    metrics["host_smoke"] = smoke
    checks_to_report = smoke.get("checks", [])
    failed = [c for c in checks_to_report if c.get("status") == "FAIL"]
    informational_skips = [
        c.get("name") for c in checks_to_report if c.get("status") == "SKIP"
    ]
    node_version = smoke.get("node", {}).get("version", "")
    if smoke.get("status") != "PASS" or failed:
        detail = "; ".join(
            f"{c.get('name')}: exit {c.get('exit')} {truncate(c.get('stderr', ''), 200)}"
            for c in failed[:5]
        )
        check(checks, "cli.host-node-smoke", "cli",
              smoke_title, "FAIL",
              truncate(f"node {node_version}: {detail or smoke.get('error', 'smoke failed')}", 1500))
    else:
        summary = ", ".join(
            f"{c.get('name')}=exit{c.get('exit')}" for c in checks_to_report
        )
        check(checks, "cli.host-node-smoke", "cli",
              smoke_title, "PASS",
              f"host Node {node_version}; {len(checks_to_report)} command(s) checked: "
              + truncate(summary, 900)
              + (f"; informational skipped on host: {', '.join(informational_skips)}"
                 if informational_skips else ""))

    node = smoke.get("node", {})
    if node.get("pinned") is False:
        check(checks, "host.node-provenance", "host",
              "Host Node.js comes from nodejs.org with a verified checksum", "SKIP",
              f"local/dev node binary used: {node.get('path')} ({node.get('version')})")
    elif node.get("checksum_verified") is True:
        check(checks, "host.node-provenance", "host",
              "Host Node.js comes from nodejs.org with a verified checksum", "PASS",
              f"node {node.get('version')} from {node.get('url')}; "
              f"sha256 matches nodejs.org SHASUMS256.txt")
    else:
        check(checks, "host.node-provenance", "host",
              "Host Node.js comes from nodejs.org with a verified checksum", "FAIL",
              f"host node provenance not verified: {truncate(json.dumps(node), 500)}")

    if node_version == expected_node:
        check(checks, "host.node-version", "host",
              f"Host smoke runs on the pinned Node.js {EXPECTED_RUNTIME_NODE_VERSION[variant]}",
              "PASS", f"node --version = {node_version}")
    elif node.get("pinned") is False:
        check(checks, "host.node-version", "host",
              f"Host smoke runs on the pinned Node.js {EXPECTED_RUNTIME_NODE_VERSION[variant]}",
              "SKIP",
              f"diagnostic run used a local node ({node_version}), not the pinned download")
    else:
        check(checks, "host.node-version", "host",
              f"Host smoke runs on the pinned Node.js {EXPECTED_RUNTIME_NODE_VERSION[variant]}",
              "FAIL", f"expected {expected_node}, got {node_version}")


# --------------------------------------------------------------------------
# Package-report assembly
# --------------------------------------------------------------------------
def _build_package_report(ctx, checks, sources, manifest, args):
    data_entries = ctx["data_entries"]
    control = ctx["control"]
    metrics = ctx["metrics"]
    variant = ctx.get("variant") or VARIANT_NODE22
    runtime_kind = RUNTIME_KIND[variant]
    experimental = bool(EXPERIMENTAL_VARIANTS.get(variant))
    release_label = ""
    if experimental:
        release_label = (
            (sources or {}).get("release_label", "")
            if isinstance(sources, dict) else ""
        ) or EXPERIMENTAL_RELEASE_LABELS.get(variant, "")
    runtime_capabilities = metrics.get("runtime_capabilities", {})
    report = {
        "schema": 1,
        "kind": "package-report",
        "generated_at": utc_now(),
        "self_test": bool(args.mode == "self-test"),
        "variant": VARIANT_LABELS[variant],
        "runtime_kind": runtime_kind,
        "experimental": experimental,
        "bootstrap_prep": bool(ctx.get("allow_non_ffi_runtime")) if experimental else False,
        "release_label": release_label,
        "package": {
            "name": control.get("Package"),
            "version": control.get("Version"),
            "architecture": control.get("Architecture"),
            "file": Path(args.deb).name,
            "size": metrics.get("deb_size"),
            "sha256": metrics.get("deb_sha256"),
            "installed_size_kib": control.get("Installed-Size"),
            "variant": VARIANT_LABELS[variant],
            "runtime_kind": runtime_kind,
            "experimental": experimental,
            "release_label": release_label,
            "control": control,
        },
        "sources": sources,
        "contents": {
            "files": data_entries,
            "totals": {
                "entries": len(data_entries),
                "files": len([e for e in data_entries if e["type"] == "file"]),
                "bytes": metrics.get("data_bytes", 0),
            },
            "staged_manifest_sha256": metrics.get("manifest_sha256", ""),
        },
        "runtime": {
            "variant": VARIANT_LABELS[variant],
            "runtime_kind": runtime_kind,
            "experimental": experimental,
            "node": {
                "sha256": metrics.get("node_sha256"),
                "size": metrics.get("node_size"),
                "node_version": metrics.get("runtime_node_version", ""),
                "expected_sha256": (
                    (sources or {}).get("expected_node_sha256", "")
                    if isinstance(sources, dict) else ""
                ),
                "macho": {
                    "platform": metrics.get("node_platform", ""),
                    "arch": metrics.get("node_arch", ""),
                    "minos": metrics.get("node_minos", ""),
                },
                "dylibs": metrics.get("node_dylibs", []),
                "entitlements_sha256": metrics.get("entitlements_sha256", ""),
                "runtime_manifest_sha256": metrics.get("runtime_manifest_sha256", ""),
            },
            "capabilities": runtime_capabilities,
            "jit_memory": metrics.get("runtime_jit_memory"),
            "device_status": metrics.get("runtime_device_status", ""),
            "device_verification": metrics.get("runtime_device_verification"),
            "launcher_required_flags": metrics.get("runtime_launcher_required_flags", []),
            "configure_flags": metrics.get("runtime_configure_flags", []),
            "patches": metrics.get("runtime_patches", []),
            "ripgrep": metrics.get("ripgrep", {"included": False}),
            "jitshim": metrics.get("jitshim", {"included": False}),
            "open_dylib": metrics.get("opentui", {"included": False}),
            "runtime_assets_root": {
                "path": NODE26_ASSET_ROOT,
                "override": NODE26_RUNTIME_ASSETS_OVERRIDE,
                "note": "runtime root is the packaged /var/jb CLI asset tree; "
                        "/var/mobile roots are refused by the iOS sandbox for dylib "
                        "mmap, and the renderer must be codesign-signed",
            },
        },
        "cli": metrics.get("cli", {}),
        "host_smoke": metrics.get("host_smoke", {}),
        "validations": checks,
        "summary": summarize_checks(checks),
        "device_execution": {
            "status": DEVICE_STATUS,
            "banner": DEVICE_BANNER,
            "experimental": experimental,
            "note": "No device execution was performed by CI; the package was built "
                    "and validated on a hosted macOS runner only. Producer runtime "
                    "manifest device markers are recorded under runtime.device_status "
                    "/ runtime.device_verification as producer evidence, not CI proof."
                    + (" This is an EXPERIMENTAL node26/Phase D build: the real TUI "
                       "path (node:ffi + OpenTUI dylib) is NOT device-verified until "
                       "the maintainer runs the packaged acceptance."
                       if experimental else ""),
            "producer_runtime_device_status": metrics.get("runtime_device_status", ""),
            "device_tests": DEVICE_TESTS,
        },
        "workflow": {
            "run_id": args.run_id or os.environ.get("GITHUB_RUN_ID", ""),
            "run_url": args.run_url or "",
        },
        "environment": environment_info(),
    }
    if manifest:
        report["contents"]["staged_manifest"] = manifest
    return report


def summarize_checks(checks):
    passed = sum(1 for c in checks if c["status"] == "PASS")
    failed = sum(1 for c in checks if c["status"] == "FAIL")
    skipped = sum(1 for c in checks if c["status"] == "SKIP")
    return {
        "total": len(checks),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "ci_status": "PASS" if failed == 0 else "FAIL",
        "device_status": DEVICE_STATUS,
    }


# --------------------------------------------------------------------------
# Report writing
# --------------------------------------------------------------------------
def _md_escape(text):
    return (
        "" if text is None else str(text)
    ).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _md_assertions_table(checks):
    lines = ["| Check | Status | Evidence |", "| --- | --- | --- |"]
    for c in checks:
        lines.append(
            f"| `{c['id']}` — {_md_escape(c['title'])} | **{c['status']}** | "
            f"{_md_escape(truncate(c['evidence'], 400))} |"
        )
    return "\n".join(lines)


def render_markdown(report, package_report=None):
    summary = report["summary"]
    package = report.get("package") or {}
    lines = [
        "# OpenCode iOS port — verification report",
        "",
        f"Generated: `{report['generated_at']}`  ",
        f"Mode: `{report['mode']}`  ",
        f"Variant: `{report.get('variant', 'node22')}` "
        f"(runtime `{report.get('runtime_kind', 'node22')}`)  ",
        f"CI status: **{summary['ci_status']}** "
        f"({summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['skipped']} skipped)  ",
        f"Device status: **{DEVICE_STATUS}**",
        "",
        f"> **{DEVICE_BANNER}**",
        ">",
        "> All results below were produced on a hosted GitHub Actions macOS runner.",
        "> Hosted CI cannot run iOS binaries: no on-device claim is made anywhere in",
        "> this report. The device test plan below must be executed by the user.",
        "",
        "## Environment",
        "",
        "| Property | Value |",
        "| --- | --- |",
    ]
    env = report.get("environment", {})
    for key in (
        "runner_os", "runner_arch", "platform", "python_version",
        "github_repository", "github_run_id", "github_sha",
    ):
        lines.append(f"| `{key}` | {_md_escape(env.get(key, ''))} |")
    lines.extend(["", "## Package under verification", ""])
    if package:
        lines.extend([
            "| Property | Value |",
            "| --- | --- |",
            f"| File | `{_md_escape(package.get('file', ''))}` |",
            f"| Version | `{_md_escape(package.get('version', ''))}` |",
            f"| Architecture | `{_md_escape(package.get('architecture', ''))}` |",
            f"| SHA256 | `{_md_escape(package.get('sha256', ''))}` |",
            f"| Size | {package.get('size', 'n/a')} bytes |",
            f"| Installed-Size | {package.get('installed_size_kib', 'n/a')} KiB |",
        ])
        if package.get("run_url"):
            lines.append(f"| Package run | {package['run_url']} |")
    else:
        lines.append("_No package metadata recorded._")
    lines.extend(["", "## CI-runnable assertions", "", _md_assertions_table(report["assertions"])])

    if package_report:
        sources = package_report.get("sources", {})
        inputs = sources.get("inputs", {})
        lines.extend(["", "## Provenance (from package-report.json)", ""])
        lines.extend([
            "| Component | Source run | Artifact |",
            "| --- | --- | --- |",
            f"| Runtime | {_md_escape(inputs.get('runtime', {}).get('run_url', 'n/a'))} "
            f"| `ios-node-runtime` (run {_md_escape(str(inputs.get('runtime', {}).get('run_id', 'n/a')))}) |",
            f"| CLI | {_md_escape(inputs.get('opencode_cli', {}).get('run_url', 'n/a'))} "
            f"| `opencode-cli-node-ios` (run {_md_escape(str(inputs.get('opencode_cli', {}).get('run_id', 'n/a')))}) |",
            f"| ripgrep (optional) | {_md_escape(inputs.get('ripgrep', {}).get('run_url', 'n/a') if inputs.get('ripgrep', {}).get('included') else 'not shipped')} "
            f"| `ios-ripgrep` |",
        ])
        upstream = sources.get("upstream", {})
        lines.extend([
            "",
            f"Pinned upstream: OpenCode `{_md_escape(upstream.get('OPENCODE_REF', ''))}` "
            f"(v{_md_escape(upstream.get('OPENCODE_VERSION', ''))}), "
            f"nodejs-mobile `{_md_escape(upstream.get('NODE_MOBILE_COMMIT', ''))}` "
            f"(Node {_md_escape(upstream.get('NODE_VERSION', ''))}), "
            f"port commit `{_md_escape(sources.get('commit', ''))}`.",
        ])

    lines.extend([
        "",
        f"## {DEVICE_HEADING}",
        "",
        f"> **{DEVICE_BANNER}**",
        "",
        "These checks were **not executed** — hosted CI has no iOS device. Run them",
        "on the iPhone SE 2 and report the outputs (see `docs/VERIFICATION.md`).",
        "",
        "| Device test | What to run | Expected |",
        "| --- | --- | --- |",
    ])
    for test in DEVICE_TESTS:
        commands = "`" + "` ; `".join(test["commands"]) + "`"
        lines.append(
            f"| `{test['id']}` — {_md_escape(test['title'])} | {_md_escape(commands)} "
            f"| {_md_escape(test['expected'])} |"
        )
    lines.extend([
        "",
        "## Reproduce",
        "",
        "```sh",
        "# download the package artifact from the packaging workflow run, then:",
        "sha256sum -c SHA256SUMS",
        "bash scripts/validate-port.sh --deb OpenCode-iOS-rootless.deb --mode verify \\",
        "  --artifact-dir . --out-dir verification",
        "```",
        "",
        f"_Device status remains **{DEVICE_STATUS}** until a user runs the device tests._",
        "",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# verify subcommand
# --------------------------------------------------------------------------
def cmd_verify(args):
    started = time.time()
    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    deb_path = Path(args.deb)
    mode = args.mode
    checks = []
    ctx = {
        "mode": mode,
        "repo_root": repo_root,
        "metrics": {},
        "control": {},
        "control_text": "",
        "control_files": {},
        "data_entries": [],
        "extract_dir": Path(args.extract_dir) if args.extract_dir else None,
    }

    # ---- read the .deb ---------------------------------------------------
    try:
        deb = DebPackage(deb_path)
        ctx["metrics"]["deb_sha256"] = sha256_file(deb_path)
        ctx["metrics"]["deb_size"] = deb_path.stat().st_size
        check(checks, "pkg.deb-readable", "package",
              "Package file is a well-formed Debian .deb archive", "PASS",
              f"ar members: {', '.join(sorted(deb.members))}; "
              f"size={ctx['metrics']['deb_size']} bytes; "
              f"sha256={ctx['metrics']['deb_sha256']}")
        ctx["control_text"] = deb.control_text()
        ctx["control"] = deb.parse_control()
        ctx["control_files"] = deb.control_files()
        ctx["data_entries"] = deb.data_entries()
        ctx["metrics"]["data_bytes"] = sum(
            e["size"] for e in ctx["data_entries"] if e["type"] == "file"
        )
        if ctx["data_entries"]:
            largest = max(
                (e for e in ctx["data_entries"] if e["type"] == "file"),
                key=lambda e: e["size"],
                default=None,
            )
            if largest:
                ctx["metrics"]["largest_file"] = (
                    f"{largest['path']} ({largest['size']} bytes)"
                )
    except DebError as exc:
        check(checks, "pkg.deb-readable", "package",
              "Package file is a well-formed Debian .deb archive", "FAIL", str(exc))
        return _finish(args, ctx, checks, started)

    # ---- extraction ------------------------------------------------------
    extract_dir = ctx["extract_dir"]
    if extract_dir is None:
        extract_dir = out_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            deb.extract_data(extract_dir)
            ctx["extract_dir"] = extract_dir
        except DebError as exc:
            check(checks, "pkg.extract", "package",
                  "Package data archive extracts safely", "FAIL", str(exc))
            return _finish(args, ctx, checks, started)
    check(checks, "pkg.extract", "package",
          "Package data archive extracts safely", "PASS",
          f"extracted {len(ctx['data_entries'])} entries to a temp directory; "
          "no absolute paths, '..', or escaping symlinks")

    # ---- provenance inputs ----------------------------------------------
    sources = None
    if args.sources:
        try:
            sources = read_json(args.sources)
        except (OSError, ValueError) as exc:
            check(checks, "pkg.sources", "package",
                  "Provenance metadata available", "FAIL",
                  f"cannot read {args.sources}: {exc}")
    if sources is None and args.package_report:
        try:
            package_report_in = read_json(args.package_report)
            sources = package_report_in.get("sources")
            ctx["package_report_input"] = package_report_in
        except (OSError, ValueError):
            sources = None
    ctx["sources"] = sources
    if sources:
        runs = sources.get("inputs", {})
        check(checks, "pkg.sources", "package",
              "Provenance metadata available", "PASS",
              f"variant={sources.get('variant', 'n/a')}, "
              f"runtime run={runs.get('runtime', {}).get('run_id', 'n/a')}, "
              f"cli run={runs.get('opencode_cli', {}).get('run_id', 'n/a')}, "
              f"self_test={sources.get('self_test')}")
    else:
        check(checks, "pkg.sources", "package",
              "Provenance metadata available", "SKIP",
              "no sources JSON / package-report.json supplied")

    package_report_in = ctx.get("package_report_input")
    requested_variant = "" if args.variant in ("", "auto") else args.variant
    variant = infer_variant(ctx, sources, package_report_in, requested_variant)
    ctx["variant"] = variant
    allow_non_ffi = bool(getattr(args, "allow_non_ffi_runtime", False))
    if isinstance(sources, dict) and sources.get("bootstrap_prep") is True:
        allow_non_ffi = True
    ctx["allow_non_ffi_runtime"] = allow_non_ffi
    check(checks, "pkg.variant", "package",
          "Package runtime variant identified", "PASS",
          f"variant={VARIANT_LABELS[variant]} "
          f"(runtime_kind={RUNTIME_KIND[variant]}, expected Node "
          f"{EXPECTED_RUNTIME_NODE_VERSION[variant]})")
    if isinstance(sources, dict):
        opentui_expected = (
            sources.get("inputs", {}).get("opentui", {}).get("expected_sha256", "")
        )
        if opentui_expected:
            ctx["metrics"]["opentui_expected_sha256"] = opentui_expected

    expected_version = args.expected_version or expected_deb_version(repo_root)

    # ---- repository checks ----------------------------------------------
    _check_repo_checks(checks, repo_root, mode, out_dir)

    # ---- package checks --------------------------------------------------
    _check_control(checks, ctx, expected_version, variant)
    _check_paths(checks, ctx, mode)
    _check_maintainer_scripts(checks, ctx, extract_dir, variant)
    _check_launcher(checks, ctx, extract_dir, variant)
    _check_docs(checks, ctx, extract_dir, variant)
    _check_no_secrets_and_junk(checks, ctx, extract_dir)
    _check_sha256sums(checks, ctx, deb_path, args.artifact_dir or deb_path.parent)
    if args.contents_manifest:
        ctx["metrics"]["manifest_sha256"] = sha256_file(args.contents_manifest)
        _check_manifest_consistency(checks, ctx, args.contents_manifest,
                                    "Packaging contents manifest")
    if args.package_report:
        _check_package_report_cross(checks, ctx, args.package_report)
    _check_verbatim_copy(checks, ctx, sources)
    _check_bundle_manifest(checks, ctx, extract_dir)

    # ---- runtime / CLI checks -------------------------------------------
    _check_runtime(checks, ctx, repo_root, extract_dir, mode, args.skip_native_audit)
    # Node sha pin must be compared after the runtime binary has been hashed.
    sources_node_pin = ""
    if isinstance(sources, dict):
        sources_node_pin = str(sources.get("expected_node_sha256", "") or "")
    node_sha_actual = ctx["metrics"].get("node_sha256", "")
    if sources_node_pin:
        if node_sha_actual and sources_node_pin != node_sha_actual:
            check(checks, "runtime.node-pin", "runtime",
                  "Runtime node binary matches the pinned sha256", "FAIL",
                  f"pinned {sources_node_pin}, packaged node is {node_sha_actual}")
        else:
            check(checks, "runtime.node-pin", "runtime",
                  "Runtime node binary matches the pinned sha256", "PASS",
                  f"node sha256={node_sha_actual} matches the provenance pin")
    _check_runtime_profile(checks, ctx, extract_dir, variant)
    _check_optional_jitshim(checks, ctx, extract_dir, args.skip_native_audit)
    _check_optional_ripgrep(checks, ctx, extract_dir, args.skip_native_audit, mode)
    _check_cli(checks, ctx, extract_dir, mode, variant)
    _check_opentui(checks, ctx, extract_dir, variant, args.skip_native_audit, sources)
    cli_dir_check = Path(extract_dir) / "var/jb/usr/lib/opencode/cli"
    _check_artifact_policy(checks, ctx, cli_dir_check, variant)
    _check_assets_native(checks, ctx, cli_dir_check)
    if args.skip_smoke:
        check(checks, "cli.host-node-smoke", "cli",
              f"CLI bundle runs on the host Node.js "
              f"{EXPECTED_RUNTIME_NODE_VERSION[variant]} runtime", "SKIP",
              "skipped by --skip-smoke (local dry-run only)")
        check(checks, "host.node-provenance", "host",
              "Host Node.js comes from nodejs.org with a verified checksum", "SKIP",
              "skipped by --skip-smoke")
    else:
        _check_host_smoke(checks, ctx, args.host_smoke_json, variant)

    return _finish(args, ctx, checks, started)


def _finish(args, ctx, checks, started):
    summary = summarize_checks(checks)
    variant = ctx.get("variant") or VARIANT_NODE22
    environment = environment_info({
        "mode": args.mode,
        "elapsed_seconds": round(time.time() - started, 2),
        "variant": VARIANT_LABELS[variant],
        "runtime_kind": RUNTIME_KIND[variant],
    })
    package_block = {
        "file": Path(args.deb).name,
        "sha256": ctx["metrics"].get("deb_sha256", ""),
        "size": ctx["metrics"].get("deb_size"),
        "version": ctx["control"].get("Version", ""),
        "architecture": ctx["control"].get("Architecture", ""),
        "installed_size_kib": ctx["control"].get("Installed-Size", ""),
        "variant": VARIANT_LABELS[variant],
        "runtime_kind": RUNTIME_KIND[variant],
        "runtime_node_version": ctx["metrics"].get("runtime_node_version", ""),
        "run_url": args.run_url or "",
        "run_id": args.run_id or "",
    }
    report = {
        "schema": 1,
        "kind": "verification-report",
        "generated_at": utc_now(),
        "mode": args.mode,
        "variant": VARIANT_LABELS[variant],
        "runtime_kind": RUNTIME_KIND[variant],
        "environment": environment,
        "package": package_block,
        "summary": summary,
        "assertions": checks,
        "device_execution": {
            "status": DEVICE_STATUS,
            "banner": DEVICE_BANNER,
            "heading": DEVICE_HEADING,
            "note": "Device-only tests were NOT performed. Hosted CI cannot execute "
                    "iOS arm64 binaries; run the device runbook in docs/VERIFICATION.md.",
            "device_tests": DEVICE_TESTS,
        },
        "reproduction": {
            "verify_command": (
                "bash scripts/validate-port.sh --deb OpenCode-iOS-rootless.deb "
                f"--mode {args.mode} --artifact-dir . --out-dir verification"
            ),
        },
    }
    out_dir = Path(args.out_dir)
    json_write(out_dir / "check-results.json", {
        "schema": 1, "generated_at": utc_now(), "mode": args.mode,
        "summary": summary, "checks": checks,
    })
    json_write(out_dir / "verification-report.json", report)

    package_report = None
    if args.mode in ("package", "self-test"):
        sources = ctx.get("sources") or {
            "schema": 1, "kind": "package-sources",
            "self_test": args.mode == "self-test",
            "note": "no provenance JSON supplied to the verification step",
        }
        manifest = None
        if args.contents_manifest:
            try:
                manifest = read_json(args.contents_manifest)
            except (OSError, ValueError):
                manifest = None
        package_report = _build_package_report(ctx, checks, sources, manifest, args)
        if ctx.get("package_report_input"):
            package_report["reverified_package_report_sha256"] = sha256_file(
                Path(args.package_report)
            )
            package_report["sources"] = sources
        json_write(out_dir / "package-report.json", package_report)

    md = render_markdown(report, package_report)
    with open(out_dir / "verification-report.md", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(md + "\n")

    print("verification summary:")
    for c in checks:
        print(f"  [{c['status']}] {c['id']}: {c['title']}")
        if c["status"] != "PASS" and c["evidence"]:
            print(f"        {truncate(c['evidence'], 300)}")
    print(
        f"RESULT: ci_status={summary['ci_status']} device_status={DEVICE_STATUS} "
        f"passed={summary['passed']} failed={summary['failed']} "
        f"skipped={summary['skipped']} -> {out_dir}"
    )
    return 0 if summary["ci_status"] == "PASS" else 1


# --------------------------------------------------------------------------
# Self-test fixtures
# --------------------------------------------------------------------------
FAKE_MJS = r'''#!/usr/bin/env node
// Synthetic placeholder CLI used ONLY by the packaging scripts self-test.
// This is NOT OpenCode and must never be shipped in a package.
const args = process.argv.slice(2);
const has = (flag) => args.includes(flag);
if (has("--version")) {
  console.log("2.2.5");
  process.exit(0);
}
if (has("--help")) {
  console.log("Usage: opencode [options] [command]");
  console.log("");
  console.log("Synthetic self-test placeholder CLI (NOT OpenCode).");
  process.exit(0);
}
if (args.some((arg) => arg.startsWith("--definitely-not"))) {
  console.error("error: unknown option");
  process.exit(1);
}
if (has("debug") && has("paths")) {
  console.log("config  ~/.config/opencode");
  console.log("data    ~/.local/share/opencode");
  process.exit(0);
}
if (has("auth") && has("list")) {
  console.log("No credentials configured.");
  process.exit(0);
}
console.log("self-test placeholder: " + JSON.stringify(args));
'''


def _write_sums(directory, paths):
    lines = []
    for path in sorted(paths):
        rel = Path(path).relative_to(directory).as_posix()
        lines.append(f"{sha256_file(Path(path))}  {rel}")
    with open(Path(directory) / "SHA256SUMS", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def cmd_fixture(args):
    out = Path(args.out_dir)
    runtime = out / "artifacts" / "runtime"
    cli = out / "artifacts" / "opencode"
    ripgrep = out / "artifacts" / "ripgrep"
    for directory in (runtime, cli / "assets", ripgrep):
        directory.mkdir(parents=True, exist_ok=True)

    node = Path(args.node)
    if not node.is_file():
        raise SystemExit(f"fixture: --node file not found: {node}")
    shutil.copy2(node, runtime / "node")

    entitlements = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>platform-application</key>
    <true/>
    <key>com.apple.private.security.no-sandbox</key>
    <true/>
    <key>self-test-placeholder</key>
    <true/>
</dict>
</plist>
"""
    (runtime / "entitlements.plist").write_text(entitlements, encoding="utf-8")
    runtime_manifest = {
        "name": "self-test placeholder runtime (NOT Node.js)",
        "self_test": True,
        "node_version": "22.9.0",
        "note": "synthetic fixture used by the packaging scripts self-test; never shipped",
        "build": {
            "configure_flags": [
                "--dest-os=ios",
                "--dest-cpu=arm64",
                "--with-intl=full-icu",
            ]
        },
        "runtime_policy": {
            "intl": {
                "mode": "full-icu",
                "configure_flag": "--with-intl=full-icu",
                "icu_version": "self-test-placeholder",
            },
            "webassembly": "enabled: self-test placeholder",
            "v8_jit": "enabled: self-test placeholder",
        },
        "source": {
            "patches": [
                {"file": "patches/nodejs-mobile/0004-ios-jit-write-protect.patch"},
            ],
        },
        "binary": {
            "file": "node",
            "size_bytes": (runtime / "node").stat().st_size,
            "sha256": sha256_file(runtime / "node"),
        },
        "node": {"path": "node", "sha256": sha256_file(runtime / "node")},
        "entitlements": {"path": "entitlements.plist",
                         "sha256": sha256_file(runtime / "entitlements.plist")},
    }
    json_write(runtime / "runtime-manifest.json", runtime_manifest)
    _write_sums(runtime, [runtime / "node", runtime / "entitlements.plist",
                          runtime / "runtime-manifest.json"])

    (cli / "opencode.mjs").write_text(FAKE_MJS, encoding="utf-8")
    (cli / "assets" / "self-test-placeholder.bin").write_bytes(
        b"synthetic self-test asset placeholder - not OpenCode\n" * 8
    )
    bundle_manifest = {
        "bundle": "self-test-placeholder",
        "self_test": True,
        "files": [
            {"path": "opencode.mjs", "sha256": sha256_file(cli / "opencode.mjs")},
            {"path": "assets/self-test-placeholder.bin",
             "sha256": sha256_file(cli / "assets" / "self-test-placeholder.bin")},
        ],
    }
    json_write(cli / "bundle-manifest.json", bundle_manifest)
    _write_sums(cli, [cli / "opencode.mjs", cli / "assets" / "self-test-placeholder.bin",
                      cli / "bundle-manifest.json"])

    shutil.copy2(node, ripgrep / "rg")
    _write_sums(ripgrep, [ripgrep / "rg"])

    print(f"fixture: synthetic placeholder artifacts created under {out / 'artifacts'}")
    for directory in (runtime, cli, ripgrep):
        print(f"  {directory}")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="OpenCode iOS package manifests, .deb inspection and verification"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("manifest", help="build a contents manifest for a staged tree")
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--label", default="")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("sources", help="build package provenance JSON")
    p.add_argument("--lock", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--repository", default="")
    p.add_argument("--commit", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--run-url", default="")
    p.add_argument("--runtime-dir", required=True)
    p.add_argument("--runtime-run-id", default="")
    p.add_argument("--runtime-run-url", default="")
    p.add_argument("--runtime-artifact-name", default="")
    p.add_argument("--opencode-dir", required=True)
    p.add_argument("--opencode-run-id", default="")
    p.add_argument("--opencode-run-url", default="")
    p.add_argument("--ripgrep-dir", default="")
    p.add_argument("--ripgrep-run-id", default="")
    p.add_argument("--ripgrep-run-url", default="")
    p.add_argument("--jitshim-dir", default="")
    p.add_argument("--jitshim-run-id", default="")
    p.add_argument("--jitshim-run-url", default="")
    p.add_argument("--opentui-dir", default="")
    p.add_argument("--opentui-run-id", default="")
    p.add_argument("--opentui-run-url", default="")
    p.add_argument("--opentui-sha256", default="")
    p.add_argument("--opentui-relative-path", default="")
    p.add_argument("--expected-node-sha256", default="")
    p.add_argument("--experimental-label", default="")
    p.add_argument("--allow-non-ffi-runtime", action="store_true",
                   help="record a pipeline-prep build that tolerates a non-FFI "
                        "runtime for the experimental node26 variant")
    p.add_argument("--variant", default="",
                   help="node22 (default), node18 or experimental node26")
    p.add_argument("--self-test", action="store_true")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("extract", help="extract a .deb with the pure-Python reader")
    p.add_argument("--deb", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("macho-info", help="print Mach-O platform/arch metadata for a file")
    p.add_argument("--path", required=True)
    p.add_argument("--expect-platform", default="")
    p.add_argument("--expect-arch", default="")
    p.set_defaults(func=cmd_macho_info)

    p = sub.add_parser("verify", help="run the CI-runnable verification suite")
    p.add_argument("--deb", required=True)
    p.add_argument("--mode", choices=("package", "verify", "test", "self-test"),
                   required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    p.add_argument("--extract-dir", default="")
    p.add_argument("--artifact-dir", default="")
    p.add_argument("--contents-manifest", default="")
    p.add_argument("--sources", default="")
    p.add_argument("--package-report", default="")
    p.add_argument("--host-smoke-json", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--run-url", default="")
    p.add_argument("--expected-version", default="")
    p.add_argument("--variant", default="auto",
                   help="auto|node22|node18|node26 (auto infers from "
                        "provenance/manifest)")
    p.add_argument("--skip-smoke", action="store_true")
    p.add_argument("--skip-native-audit", action="store_true")
    p.add_argument("--allow-non-ffi-runtime", action="store_true",
                   help="pipeline-prep mode for experimental node26: a non-FFI "
                        "runtime is reported as a prep caveat instead of a failure "
                        "(the real TUI will not load)")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("render-control",
                       help="render DEBIAN/control from the template for a variant")
    p.add_argument("--template", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--maintainer", required=True)
    p.add_argument("--installed-size", required=True, type=int)
    p.add_argument("--variant", default="node22")
    p.add_argument("--node-version", default="")
    p.set_defaults(func=cmd_render_control)

    p = sub.add_parser("fixture", help="create synthetic placeholder inputs (self-test)")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--node", required=True)
    p.set_defaults(func=cmd_fixture)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
