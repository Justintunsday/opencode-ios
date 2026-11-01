#!/usr/bin/env python3
"""Generate (or verify) `bundle-manifest.json` + `SHA256SUMS` for the iOS CLI artifact.

The manifest is the machine-readable hand-over contract between
`build-opencode.yml` (producer) and `package-rootless.yml` / `test-port.yml`
(consumers). It records exactly what was built from which upstream commit and
patch series, every bundled file's size/hash, the launcher environment contract
the .deb wrapper must provide, and the host-Node smoke results.

Honesty rules enforced here:
  * `device_verified` is always false: CI can only verify on host Node.
  * The smoke report is embedded verbatim under `smoke`; failures are not hidden.
  * Asset categories are derived from the actual staged tree, never assumed.

Usage:
  bundle_manifest.py --artifact-dir DIR --build-info FILE --smoke-report FILE
                     --patches-dir DIR --upstream-lock FILE
  bundle_manifest.py --artifact-dir DIR --build-info FILE --patches-dir DIR
                     --upstream-lock FILE --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

MANIFEST_NAME = "bundle-manifest.json"
SUMS_NAME = "SHA256SUMS"
MANIFEST_SCHEMA = "opencode-ios/bundle-manifest/v1"

# Launcher contract for the .deb wrapper (/var/jb/usr/bin/opencode). Values are
# relative to the rootless install prefix and are also documented in
# docs/OPENCODE_BUILD.md. `package-rootless.yml` must match this contract.
#
# Two conditional variants share this generator:
#   opencode-cli-node-ios       Node 22.9 runtime bundle (default)
#   opencode-cli-node18-ios     Node 18 runtime fallback (sql.js-backed node:sqlite shim)
INSTALL_PREFIX = "/var/jb"
ENV_CONTRACT = {
    "artifact_layout": {
        "bundle_entry": f"{INSTALL_PREFIX}/usr/lib/opencode/cli/opencode.mjs",
        "assets_dir": f"{INSTALL_PREFIX}/usr/lib/opencode/cli/assets",
        "runtime_node": f"{INSTALL_PREFIX}/usr/lib/opencode/runtime/node",
        "launcher": f"{INSTALL_PREFIX}/usr/bin/opencode",
    },
    "launcher_argv": [
        f"{INSTALL_PREFIX}/usr/lib/opencode/runtime/node",
        "--single-threaded",
        "--experimental-sqlite",
        f"{INSTALL_PREFIX}/usr/lib/opencode/cli/opencode.mjs",
        '"$@"',
    ],
    "launcher_env": {
        "OPENCODE_IOS": "1",
        "OPENCODE_NODE_ASSETS_DIR": f"{INSTALL_PREFIX}/usr/lib/opencode/cli/assets",
        "HOME": "device user home (writable)",
        "TMPDIR": "writable temporary directory",
    },
    "node_flags": {
        "required": ["--single-threaded", "--experimental-sqlite"],
        "forbidden": ["--experimental-ffi", "--use-system-ca"],
        "notes": [
            "--experimental-ffi does not exist on Node 22.9.0 and the ffi-rs addon is absent on iPhoneOS.",
            "--use-system-ca does not exist on Node 22.9.0 (added to later Node lines); do not pass it.",
            "--single-threaded is REQUIRED by the v6 iPhoneOS Node 22.9 runtime: its V8 JIT/wasm code-memory toggling is process-wide and background V8 threads race it, so multithreaded processes die with SIGBUS on the first optimized loop/fetch. --no-concurrent-recompilation is an accepted alternative (device-reported). The CLI forwards --single-threaded (and --max-old-space-size=...) to spawned server children (patches/opencode/0010), so passing it once on the launcher is enough.",
            "The runtime must provide ECMA-402 Intl (full-icu/small-icu) and Node 22.9's built-in WebAssembly llhttp parser (fetch/undici needs it; a --jitless build cannot instantiate wasm). The shipped runtime enables full-icu + WebAssembly + JIT. The CLI bundle itself does not require WebAssembly at startup.",
        ],
    },
    "notes": [
        "The prelude derives the assets directory from opencode.mjs location; OPENCODE_NODE_ASSETS_DIR may be set by the wrapper to override it.",
        "Device execution has NOT been verified by CI; see docs/OPENCODE_BUILD.md device checklist.",
    ],
}

# Node 18 fallback variant: no --experimental-sqlite (the runtime rejects the flag and has no
# node:sqlite module); the bundle carries a sql.js-based shim in assets/node18-sqlite/ instead.
ENV_CONTRACT_NODE18 = {
    "artifact_layout": ENV_CONTRACT["artifact_layout"],
    "launcher_argv": [
        f"{INSTALL_PREFIX}/usr/lib/opencode/runtime/node",
        "--no-warnings",
        f"{INSTALL_PREFIX}/usr/lib/opencode/cli/opencode.mjs",
        '"$@"',
    ],
    "launcher_env": ENV_CONTRACT["launcher_env"],
    "node_flags": {
        "required": [],
        "forbidden": ["--experimental-sqlite", "--disable-warning=ExperimentalWarning", "--experimental-ffi", "--use-system-ca"],
        "notes": [
            "The Node 18 iPhoneOS runtime rejects --experimental-sqlite, --disable-warning=... and --use-system-ca (all are newer Node flags).",
            "node:sqlite does not exist on Node 18; this bundle maps it to a bundled sql.js (WebAssembly) shim in assets/node18-sqlite/ and persists the database file itself.",
            "The runtime must provide ECMA-402 Intl (ICU) and WebAssembly+JIT (the sql.js shim and Node 18 fetch/undici need them).",
        ],
    },
    "notes": [
        "Fallback variant for the device-proven Node 18.20.4 iPhoneOS runtime; the default artifact remains the Node 22.9 bundle.",
        "Same asset layout as the default variant, plus the node18-sqlite shim payload.",
        "Device execution has NOT been verified by CI; see docs/OPENCODE_BUILD.md §13.",
    ],
}

ASSET_CATEGORY_NOTES = {
    "app-archive": "Web/TUI app archive embedded by the Node build (read by the server).",
    "audio": "attention sound assets used by the interface.",
    "wasm": "WebAssembly payload (photon image processing / tree-sitter syntax parsing / the Node 18 sql.js sqlite shim); included but optional — the CLI does not require WebAssembly at startup and degrades gracefully when it is unavailable or when the matching JS glue is not shipped.",
    "native-binary": "NATIVE BINARY: not loadable on iPhoneOS (macOS/Linux addon or helper). Present only for stock/desktop builds; the iOS patch series must remove these.",
    "data": "other static data file.",
}


def log(message: str) -> None:
    print(f"[bundle-manifest] {message}", flush=True)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def read_lock(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def classify_asset(relative: str) -> str:
    normalized = relative.replace(os.sep, "/")
    if normalized == "app-archive.bin":
        return "app-archive"
    if normalized.endswith(".wasm"):
        return "wasm"
    if "/audio/" in f"/{normalized}" or normalized.endswith((".mp3", ".aac", ".wav", ".ogg")):
        return "audio"
    if normalized.endswith((".node", ".dylib", ".so", ".dll", ".exe")) or "spawn-helper" in normalized:
        return "native-binary"
    if "opencode-pty" in normalized:
        return "native-binary"
    return "data"


def hash_tree(root: str, paths: list[str]) -> tuple[str, int]:
    """Stable digest over (relative path, file sha256) pairs, sorted."""
    digest = hashlib.sha256()
    total = 0
    for relative in sorted(paths):
        file_path = os.path.join(root, relative)
        size = os.path.getsize(file_path)
        total += size
        digest.update(relative.replace(os.sep, "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(file_path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), total


def collect_artifact(artifact_dir: str) -> tuple[dict[str, object], dict[str, str]]:
    entry = os.path.join(artifact_dir, "opencode.mjs")
    if not os.path.isfile(entry):
        raise SystemExit(f"missing {entry}")
    assets_root = os.path.join(artifact_dir, "assets")
    if not os.path.isdir(assets_root):
        raise SystemExit(f"missing {assets_root}")

    asset_paths: list[str] = []
    for base, _dirs, files in os.walk(assets_root):
        for name in files:
            full = os.path.join(base, name)
            asset_paths.append(os.path.relpath(full, assets_root))
    if not asset_paths:
        raise SystemExit("assets/ is empty")

    files: list[dict[str, object]] = []
    for relative in sorted(asset_paths):
        full = os.path.join(assets_root, relative)
        files.append(
            {
                "path": relative.replace(os.sep, "/"),
                "bytes": os.path.getsize(full),
                "sha256": sha256_file(full),
                "category": classify_asset(relative),
            }
        )
    tree_sha, tree_bytes = hash_tree(assets_root, asset_paths)
    categories: dict[str, int] = {}
    for item in files:
        categories[str(item["category"])] = categories.get(str(item["category"]), 0) + 1

    entry_hash = sha256_file(entry)
    bundle = {
        "opencode_mjs": {
            "path": "opencode.mjs",
            "bytes": os.path.getsize(entry),
            "sha256": entry_hash,
        },
        "assets": {
            "path": "assets",
            "count": len(files),
            "bytes": tree_bytes,
            "tree_sha256": tree_sha,
            "categories": categories,
            "files": files,
        },
    }
    checksums = {"opencode.mjs": entry_hash}
    for item in files:
        checksums[f"assets/{item['path']}"] = str(item["sha256"])
    return bundle, checksums


def collect_patches(patches_dir: str) -> dict[str, object]:
    files: list[dict[str, object]] = []
    series = hashlib.sha256()
    if os.path.isdir(patches_dir):
        for name in sorted(os.listdir(patches_dir)):
            if not name.endswith(".patch"):
                continue
            path = os.path.join(patches_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as handle:
                content = handle.read()
            file_hash = hashlib.sha256(content).hexdigest()
            series.update(name.encode("utf-8") + b"\0" + content + b"\n")
            files.append({"name": name, "sha256": file_hash, "bytes": len(content)})
    return {"directory": "patches/opencode", "count": len(files), "series_sha256": series.hexdigest(), "files": files}


def collect_signatures(artifact_dir: str) -> dict[str, object]:
    """Inspect the generated bundle for startup code that Node 22.9 / iPhoneOS cannot load.

    A *named* `import { registerHooks } from "node:module"` or
    `import { getRawAsset } from "node:sea"` makes Node 22.9 throw a module
    link SyntaxError before any code runs, so these are the load-bearing checks.
    Property access (`nodeModule.registerHooks`) is fine and guarded.
    """
    path = os.path.join(artifact_dir, "opencode.mjs")
    with open(path, "rb") as handle:
        data = handle.read()

    def search(pattern: bytes) -> bool:
        return re.search(pattern, data) is not None

    shebang = data.split(b"\n", 1)[0].decode("utf-8", "replace")
    return {
        "bytes": len(data),
        "shebang": shebang,
        "ios_prelude_marker": b"opencode-ios-prelude" in data,
        "node18_prelude_marker": b"opencode-ios-node18-prelude" in data,
        "bundled_sqlite_shim": b"node18-sqlite" in data and b"sql-wasm" in data,
        "named_import_registerHooks": search(
            rb"\{[^}]{0,120}registerHooks[^}]{0,120}\}\s*from\s*['\"]node:module['\"]"
        ),
        "named_import_node_sea_asset_api": search(
            rb"\{[^}]{0,160}(?:getRawAsset|getAssetKeys)[^}]{0,160}\}\s*from\s*['\"]node:sea['\"]"
        ),
        "imports_node_sea": search(rb"from\s*['\"]node:sea['\"]"),
        "prelude_uses_experimental_ffi": "--experimental-ffi" in shebang,
        "prelude_uses_experimental_sqlite": "--experimental-sqlite" in shebang,
    }


def build_manifest(args: argparse.Namespace, bundle: dict[str, object], checksums: dict[str, str]) -> dict[str, object]:
    info = read_env_file(args.build_info)
    lock = read_lock(args.upstream_lock)
    patches = collect_patches(args.patches_dir)
    signatures = collect_signatures(args.artifact_dir)
    smoke = None
    if args.smoke_report and os.path.isfile(args.smoke_report):
        with open(args.smoke_report, encoding="utf-8") as handle:
            smoke = json.load(handle)

    ci: dict[str, str] = {}
    for key in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_SHA", "RUNNER_OS", "RUNNER_ARCH"):
        if info.get(key):
            ci[key] = info[key]
    run_url = None
    if info.get("GITHUB_REPOSITORY") and info.get("GITHUB_RUN_ID"):
        run_url = f"https://github.com/{info['GITHUB_REPOSITORY']}/actions/runs/{info['GITHUB_RUN_ID']}"

    device_verified = False
    required_passed = None
    if smoke is not None:
        required_passed = bool(smoke.get("summary", {}).get("required_passed"))

    node18 = info.get("NODE18_VARIANT", "0") == "1"
    artifact_name = info.get("ARTIFACT_NAME") or ("opencode-cli-node18-ios" if node18 else "opencode-cli-node-ios")
    variant = "node18-fallback" if node18 else "node22"
    env_contract = ENV_CONTRACT_NODE18 if node18 else ENV_CONTRACT
    ios_prelude = bool(signatures.get("ios_prelude_marker") or signatures.get("node18_prelude_marker"))
    if node18 and not signatures.get("node18_prelude_marker"):
        raise SystemExit("Node 18 variant bundle is missing the node18 prelude marker (build target mismatch?)")

    native = int(bundle["assets"].get("categories", {}).get("native-binary", 0))
    notes: list[str] = []
    if patches["count"] == 0:
        notes.append(
            "STOCK upstream build: no iOS patch series applied yet. The bundle was smoke-tested on host Node "
            "and is expected to fail on the shipped iPhoneOS runtime until the iOS prelude/optional-native patches land."
        )
    if node18:
        notes.append(
            "Node 18 fallback variant (hedge for the Node 22.9 iPhoneOS runtime's JIT/wasm limitation): the bundle "
            "targets Node 18.20.4 and maps node:sqlite to a bundled sql.js WebAssembly shim (assets/node18-sqlite/). "
            "The default Node 22 artifact is the primary deliverable; this one requires a Node 18 iPhoneOS runtime."
        )
    if native:
        notes.append(
            f"{native} native-binary asset file(s) are staged (Darwin/Linux addons). They are NOT loadable on iPhoneOS; "
            "the iOS patch series removes them, and this manifest records what was actually present."
        )
    if required_passed is False:
        notes.append(
            "The required host-Node smoke test did not pass for the configured runtime version; this artifact is NOT "
            "a runnable candidate for the device."
        )

    return {
        "schema": MANIFEST_SCHEMA,
        "artifact": artifact_name,
        "variant": variant,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream": {
            "repo": lock.get("OPENCODE_REPO", info.get("UPSTREAM_REPO")),
            "commit": lock.get("OPENCODE_REF", info.get("UPSTREAM_COMMIT")),
            "version": lock.get("OPENCODE_VERSION", info.get("UPSTREAM_VERSION")),
        },
        "patches": patches,
        "build": {
            "target": info.get("TARGET", "darwin-arm64"),
            "variant": variant,
            "runtime_node_version": "18.20.4" if node18 else "22.9.0",
            "sqlite": {
                "module": "node:sqlite",
                "provider": "bundled sql.js shim (WebAssembly)"
                if node18
                else "runtime node:sqlite (--experimental-sqlite)",
            },
            "ios_prelude": ios_prelude,
            "bun_version": info.get("BUN_VERSION"),
            "host_os": info.get("BUILD_HOST_OS"),
            "host_arch": info.get("BUILD_HOST_ARCH"),
            "host_node": info.get("BUILD_HOST_NODE"),
            "built_at": info.get("BUILT_AT"),
            "ci": ci,
            "run_url": run_url,
            **(
                {
                    "sqljs_version": info.get("SQLJS_VERSION"),
                    "sqljs_tarball_sha256": info.get("SQLJS_TARBALL_SHA256"),
                }
                if node18
                else {}
            ),
        },
        "bundle": bundle,
        "runtime_bootstrap_signatures": signatures,
        "assets_policy": {
            "categories": ASSET_CATEGORY_NOTES,
            "notes": [
                "Assets are exactly what the upstream asset collector staged for the build target; "
                "iOS filtering is implemented in the patch series (not post-hoc in the workflow).",
            ]
            + (
                [
                    "assets/node18-sqlite/sql-wasm.js + sql-wasm.wasm implement node:sqlite for the Node 18 variant "
                    "(sql.js 1.15.2, MIT; pinned tarball sha256 in the patch/build script)."
                ]
                if node18
                else []
            ),
        },
        "env_contract": env_contract,
        "smoke": smoke,
        "verification_status": {
            "host_smoke_required_passed": required_passed,
            "host_smoke_required_node_version": (smoke or {}).get("required_node_version"),
            "device_verified": device_verified,
            "device_verification_note": "CI runs on a macOS build host only; on-device execution remains user-verified. "
            "Do not claim device success from this manifest.",
        },
        "notes": notes,
    }


def write_sums(artifact_dir: str, checksums: dict[str, str]) -> None:
    lines = [f"{checksums[path]}  {path}\n" for path in sorted(checksums)]
    with open(os.path.join(artifact_dir, SUMS_NAME), "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)


def verify(artifact_dir: str, args: argparse.Namespace) -> int:
    manifest_path = os.path.join(artifact_dir, MANIFEST_NAME)
    sums_path = os.path.join(artifact_dir, SUMS_NAME)
    for path in (manifest_path, sums_path):
        if not os.path.isfile(path):
            log(f"ERROR: missing {path}")
            return 1
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    bundle, _ = collect_artifact(artifact_dir)
    problems: list[str] = []

    if manifest.get("bundle") != bundle:
        problems.append("bundle manifest does not match the staged artifact tree")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append("unexpected manifest schema")

    expected = dict(bundle["opencode_mjs"].items())
    del expected["bytes"]
    del expected["path"]
    _ = expected
    recomputed = {"opencode.mjs": bundle["opencode_mjs"]["sha256"]}
    for item in bundle["assets"]["files"]:
        recomputed[f"assets/{item['path']}"] = item["sha256"]
    recomputed[MANIFEST_NAME] = sha256_file(manifest_path)

    listed: dict[str, str] = {}
    with open(sums_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                problems.append(f"malformed SHA256SUMS line: {line}")
                continue
            listed[parts[1]] = parts[0]
    for path, digest in sorted(recomputed.items()):
        if path not in listed:
            problems.append(f"SHA256SUMS is missing {path}")
        elif listed[path] != digest:
            problems.append(f"SHA256SUMS mismatch for {path}")
    for path in sorted(listed):
        if path not in recomputed:
            problems.append(f"SHA256SUMS lists unexpected file {path}")

    if problems:
        for problem in problems:
            log(f"ERROR: {problem}")
        return 1
    log(
        f"verified {len(recomputed)} files "
        f"(bundle {manifest.get('bundle', {}).get('opencode_mjs', {}).get('bytes')} bytes, "
        f"{manifest.get('bundle', {}).get('assets', {}).get('count')} assets) "
        f"and SHA256SUMS"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/verify the iOS CLI bundle manifest")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--build-info", default="")
    parser.add_argument("--smoke-report", default="")
    parser.add_argument("--patches-dir", default="")
    parser.add_argument("--upstream-lock", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        return verify(args.artifact_dir, args)

    bundle, checksums = collect_artifact(args.artifact_dir)
    manifest = build_manifest(args, bundle, checksums)
    manifest_path = os.path.join(args.artifact_dir, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    checksums[MANIFEST_NAME] = sha256_file(manifest_path)
    write_sums(args.artifact_dir, checksums)
    log(
        f"wrote {MANIFEST_NAME} and {SUMS_NAME}: opencode.mjs {bundle['opencode_mjs']['bytes']} bytes, "
        f"{bundle['assets']['count']} assets ({bundle['assets']['bytes']} bytes), "
        f"patches={manifest['patches']['count']}"
    )
    return verify(args.artifact_dir, args)


if __name__ == "__main__":
    sys.exit(main())
