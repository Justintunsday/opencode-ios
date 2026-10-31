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
import sys
from datetime import datetime, timezone

MANIFEST_NAME = "bundle-manifest.json"
SUMS_NAME = "SHA256SUMS"
MANIFEST_SCHEMA = "opencode-ios/bundle-manifest/v1"

# Launcher contract for the .deb wrapper (/var/jb/usr/bin/opencode). Values are
# relative to the rootless install prefix and are also documented in
# docs/OPENCODE_BUILD.md. `package-rootless.yml` must match this contract.
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
        "required": ["--experimental-sqlite"],
        "forbidden": ["--experimental-ffi", "--use-system-ca"],
        "notes": [
            "--experimental-ffi does not exist on Node 22.9.0 and the ffi-rs addon is absent on iPhoneOS.",
            "--use-system-ca does not exist on Node 22.9.0 (added to later Node lines); do not pass it.",
            "The iPhoneOS runtime is built --jitless with WebAssembly disabled; this bundle was not Wasm-required at startup.",
        ],
    },
    "notes": [
        "The prelude derives the assets directory from opencode.mjs location; OPENCODE_NODE_ASSETS_DIR may be set by the wrapper to override it.",
        "Device execution has NOT been verified by CI; see docs/OPENCODE_BUILD.md device checklist.",
    ],
}

ASSET_CATEGORY_NOTES = {
    "app-archive": "Web/TUI app archive embedded by the Node build (read by the server).",
    "audio": "attention sound assets used by the interface.",
    "wasm": "WebAssembly payload (photon image processing); included but optional — the iPhoneOS runtime has WebAssembly disabled, consumers must degrade gracefully.",
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
    """Detect whether the bundle still carries SEA/registerHooks-only startup code."""
    path = os.path.join(artifact_dir, "opencode.mjs")
    with open(path, "rb") as handle:
        data = handle.read()
    return {
        "contains_registerHooks_call": b"registerHooks(" in data or b"registerHooks({" in data,
        "contains_node_sea_import": b'from"node:sea"' in data or b"from 'node:sea'" in data or b"node:sea" in data,
        "contains_experimental_ffi": b"--experimental-ffi" in data,
        "bytes": len(data),
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

    native = int(bundle["assets"].get("categories", {}).get("native-binary", 0))
    notes: list[str] = []
    if info.get("PATCHED", "0") != "1" and patches["count"] == 0:
        notes.append(
            "STOCK upstream build: no iOS patch series applied yet. The bundle was smoke-tested on host Node "
            "and is expected to fail on the shipped iPhoneOS runtime until the iOS prelude/optional-native patches land."
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
        "artifact": "opencode-cli-node-ios",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream": {
            "repo": lock.get("OPENCODE_REPO", info.get("UPSTREAM_REPO")),
            "commit": lock.get("OPENCODE_REF", info.get("UPSTREAM_COMMIT")),
            "version": lock.get("OPENCODE_VERSION", info.get("UPSTREAM_VERSION")),
        },
        "patches": patches,
        "build": {
            "target": info.get("TARGET", "darwin-arm64"),
            "ios_prelude": info.get("OPENCODE_IOS", "0") == "1",
            "bun_version": info.get("BUN_VERSION"),
            "host_os": info.get("BUILD_HOST_OS"),
            "host_arch": info.get("BUILD_HOST_ARCH"),
            "host_node": info.get("BUILD_HOST_NODE"),
            "built_at": info.get("BUILT_AT"),
            "ci": ci,
            "run_url": run_url,
        },
        "bundle": bundle,
        "runtime_bootstrap_signatures": signatures,
        "assets_policy": {
            "categories": ASSET_CATEGORY_NOTES,
            "notes": [
                "Assets are exactly what the upstream asset collector staged for the build target; "
                "iOS filtering is implemented in the patch series (not post-hoc in the workflow).",
            ],
        },
        "env_contract": ENV_CONTRACT,
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
