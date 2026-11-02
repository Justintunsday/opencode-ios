#!/usr/bin/env python3
"""Host-Node smoke tests for the OpenCode CLI iOS bundle.

WHAT THIS PROVES AND WHAT IT DOES NOT
-------------------------------------
This script downloads *stock* Node.js binaries from nodejs.org and runs the
staged `opencode.mjs` bundle with a throw-away HOME directory on the build
host. Passing these tests proves the JavaScript bundle parses, links and the
CLI starts under a stock Node build of the same major/minor version that the
iPhoneOS runtime is compiled from. It is **not** device verification: the
iPhoneOS runtime is compiled `--jitless` with WebAssembly disabled and none of
the native Node addons exist on iOS, so behaviour can differ (documented in
docs/OPENCODE_BUILD.md).

The report is JSON and is embedded in `bundle-manifest.json` by
`bundle_manifest.py`. No result is ever fabricated: a failing command is
reported with its exit code and captured output.

Usage:
  host_smoke.py --bundle-dir DIR --cache-dir DIR --report FILE
                [--versions 22.9.0 24.22.2 26.4.0]
                [--require-version 22.9.0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

NODE_DIST = "https://nodejs.org/dist"

# Commands that must work for the CLI to be considered started. `--version`
# and `--help` are the minimum contract from the porting plan.
REQUIRED_COMMANDS = [["--version"], ["--help"]]

# Deeper, network-free commands. They exercise config paths, the bundled
# models snapshot, credential storage and the SQLite-backed session store.
# They are recorded as informational (the iOS runtime may degrade some).
DEEP_COMMANDS = [
    ["debug", "paths"],
    ["models"],
    ["auth", "list"],
    ["session", "list"],
]

# Node flags the iOS launcher wrapper must pass to the stock Node runtime we
# ship (byte-compatible flags, verified here against real Node binaries).
# 22.x exposes node:sqlite only behind --experimental-sqlite; 23.4+/24+ does
# not need the flag but tolerates it.
SQLITE_FLAG = "--experimental-sqlite"

MAX_OUTPUT_CHARS = 2000
COMMAND_TIMEOUT_SECONDS = 180


def log(message: str) -> None:
    print(f"[host-smoke] {message}", flush=True)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def node_platform() -> tuple[str, str]:
    """Return the nodejs.org platform/arch names for this host."""
    machine = platform.machine().lower()
    arch = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x64",
        "amd64": "x64",
    }.get(machine)
    if arch is None:
        raise SystemExit(f"unsupported host architecture for stock Node download: {machine}")
    if sys.platform == "darwin":
        return "darwin", arch
    if sys.platform.startswith("linux"):
        return "linux", arch
    if sys.platform == "win32":
        return "win", arch
    raise SystemExit(f"unsupported host platform for stock Node download: {sys.platform}")


def download(url: str, destination: str) -> None:
    if os.path.exists(destination):
        return
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = f"{destination}.{os.getpid()}.tmp"
    log(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as response, open(temporary, "wb") as handle:
        shutil.copyfileobj(response, handle)
    os.replace(temporary, destination)


def fetch_checksums(version: str) -> dict[str, str]:
    url = f"{NODE_DIST}/v{version}/SHASUMS256.txt"
    log(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        text = response.read().decode("utf-8")
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            checksums[parts[1]] = parts[0]
    if not checksums:
        raise SystemExit(f"no checksums returned by {url}")
    return checksums


def ensure_stock_node(version: str, cache_dir: str) -> dict[str, object]:
    """Download (once) and verify a stock Node.js release; return its metadata."""
    plat, arch = node_platform()
    if plat == "win":
        archive_name = f"node-v{version}-win-{arch}.zip"
        extract_name = archive_name[: -len(".zip")]
    else:
        archive_name = f"node-v{version}-{plat}-{arch}.tar.gz"
        extract_name = archive_name[: -len(".tar.gz")]
    extract_dir = os.path.join(cache_dir, extract_name)
    marker = os.path.join(extract_dir, ".verified")
    binary = os.path.join(extract_dir, "node.exe" if plat == "win" else os.path.join("bin", "node"))

    if os.path.exists(marker) and os.path.exists(binary):
        return {"version": version, "binary": binary, "archive": archive_name, "verified": True}

    checksums = fetch_checksums(version)
    if archive_name not in checksums:
        raise SystemExit(f"nodejs.org does not publish {archive_name} (version {version})")
    archive = os.path.join(cache_dir, archive_name)
    download(f"{NODE_DIST}/v{version}/{archive_name}", archive)

    actual = sha256_file(archive)
    if actual != checksums[archive_name]:
        os.remove(archive)
        raise SystemExit(f"checksum mismatch for {archive_name}: expected {checksums[archive_name]}, got {actual}")

    log(f"extracting {archive_name}")
    temporary = f"{extract_dir}.{os.getpid()}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    os.makedirs(temporary, exist_ok=True)
    if plat == "win":
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(temporary)
    else:
        with tarfile.open(archive, "r:gz") as handle:
            handle.extractall(temporary)
    extracted = os.path.join(temporary, extract_name)
    if not os.path.isdir(extracted):
        raise SystemExit(f"unexpected archive layout in {archive_name}")
    shutil.rmtree(extract_dir, ignore_errors=True)
    try:
        os.replace(extracted, extract_dir)
    except OSError:
        # Some hosts (notably Windows with the cache directory open in another process) refuse
        # to rename a directory over an existing path; the verified tree is complete, so copy it.
        shutil.copytree(extracted, extract_dir, dirs_exist_ok=True)
    shutil.rmtree(temporary, ignore_errors=True)
    if plat != "win":
        os.chmod(binary, 0o755)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(checksums[archive_name] + "\n")
    return {"version": version, "binary": binary, "archive": archive_name, "verified": True}


def smoke_environment(home: str) -> dict[str, str]:
    """Environment that mimics the iOS launcher's clean state.

    A throw-away HOME keeps config/credential/session state out of the runner's
    real home. OPENCODE_IOS is set here because the launcher sets it on device;
    the unpatched stock bundle ignores it.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("OPENCODE_") and key not in {"NODE_OPTIONS", "NODE_EXTRA_CA_CERTS"}
    }
    temp = os.path.join(home, "tmp")
    os.makedirs(temp, exist_ok=True)
    env.update(
        {
            "HOME": home,
            "USERPROFILE": home,  # Windows
            "TMPDIR": temp,
            "TEMP": temp,
            "TMP": temp,
            "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
            "XDG_CACHE_HOME": os.path.join(home, ".cache"),
            "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
            "CI": "1",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "OPENCODE_IOS": "1",
        }
    )
    return env


def run_command(
    binary: str,
    flags: list[str],
    bundle_dir: str,
    command: list[str],
    cwd: str,
    env: dict[str, str],
) -> dict[str, object]:
    argv = [binary, *flags, os.path.join(bundle_dir, "opencode.mjs"), *command]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        duration = int((time.monotonic() - started) * 1000)
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as error:
        duration = int((time.monotonic() - started) * 1000)
        stdout = (error.stdout or b"").decode("utf-8", "replace") if isinstance(error.stdout, bytes) else str(error.stdout or "")
        stderr = (error.stderr or b"").decode("utf-8", "replace") if isinstance(error.stderr, bytes) else str(error.stderr or "")
        exit_code = None
    return {
        "argv": argv,
        "command": command,
        "flags": flags,
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "duration_ms": duration,
        "stdout": stdout[-MAX_OUTPUT_CHARS:],
        "stderr": stderr[-MAX_OUTPUT_CHARS:],
    }


def version_major(version: str) -> int:
    try:
        return int(version.split(".")[0])
    except (ValueError, IndexError):
        return 0


def sqlite_probe(binary: str, env: dict[str, str], cwd: str) -> dict[str, object]:
    """Determine whether node:sqlite works and whether the experimental flag is needed.

    The Node 18 fallback bundle does not use node:sqlite at all: it maps the module to the
    bundled sql.js shim. On those runtimes the probe only records that the runtime module is
    absent (the CLI does not need it), and `--experimental-sqlite` must never be passed.
    """
    script = (
        "const { DatabaseSync } = require('node:sqlite');"
        "const db = new DatabaseSync(':memory:');"
        "db.exec('CREATE TABLE t (x INTEGER)');"
        "db.prepare('INSERT INTO t VALUES (?)').run(1);"
        "console.log('sqlite-ok', db.prepare('SELECT count(*) AS c FROM t').get().c);"
    )
    attempts = []
    for flags in ([], [SQLITE_FLAG]):
        argv = [binary, *flags, "-e", script]
        try:
            completed = subprocess.run(
                argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
            )
            stdout = completed.stdout.decode("utf-8", "replace")
            stderr = completed.stderr.decode("utf-8", "replace")
            attempts.append(
                {
                    "flags": flags,
                    "exit_code": completed.returncode,
                    "passed": completed.returncode == 0 and "sqlite-ok" in stdout,
                    "stdout": stdout[-MAX_OUTPUT_CHARS:],
                    "stderr": stderr[-MAX_OUTPUT_CHARS:],
                }
            )
            if completed.returncode == 0 and "sqlite-ok" in stdout:
                break
        except subprocess.TimeoutExpired:
            attempts.append({"flags": flags, "exit_code": None, "passed": False, "stdout": "", "stderr": "timeout"})
    return {
        "database_sync_importable": any(attempt["passed"] for attempt in attempts),
        "requires_experimental_flag": attempts[0]["exit_code"] != 0 if attempts else None,
        "attempts": attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Host-Node smoke tests for the OpenCode CLI iOS bundle")
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--versions", nargs="+", default=["22.9.0", "24.22.2", "26.4.0"])
    parser.add_argument("--require-version", default="22.9.0")
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument(
        "--work-root",
        default="",
        help="directory to create the throw-away HOME/cwd under (default: the system temp dir; useful on "
        "hosts where the system temp dir is not writable by child processes)",
    )
    args = parser.parse_args()

    bundle_dir = os.path.abspath(args.bundle_dir)
    if not os.path.isfile(os.path.join(bundle_dir, "opencode.mjs")):
        raise SystemExit(f"no opencode.mjs in {bundle_dir}")
    if not os.path.isdir(os.path.join(bundle_dir, "assets")):
        raise SystemExit(f"no assets/ in {bundle_dir}")
    os.makedirs(args.cache_dir, exist_ok=True)
    work_root = args.work_root or None
    if work_root:
        os.makedirs(work_root, exist_ok=True)

    home = tempfile.mkdtemp(prefix="opencode-smoke-home-", dir=work_root)
    workdir = tempfile.mkdtemp(prefix="opencode-smoke-cwd-", dir=work_root)
    env = smoke_environment(home)
    log(f"throw-away HOME: {home}")

    results: list[dict[str, object]] = []
    runtimes: list[dict[str, object]] = []
    sqlite: dict[str, object] = {}
    required_failure: dict[str, object] | None = None

    try:
        for version in args.versions:
            runtime = ensure_stock_node(version, args.cache_dir)
            runtimes.append(runtime)
            require = version == args.require_version
            major = version_major(version)
            probe = sqlite_probe(str(runtime["binary"]), env, workdir)
            if major < 20:
                # Node 18 has no node:sqlite and rejects --experimental-sqlite; the Node 18
                # fallback bundle ships its own sql.js-backed shim instead.
                probe = {
                    "runtime_module_available": False,
                    "note": "Node <20 has no node:sqlite; the Node 18 fallback bundle uses a bundled sql.js shim",
                    "attempts": probe.get("attempts", []),
                }
            sqlite[version] = probe
            flags = [SQLITE_FLAG] if probe.get("requires_experimental_flag") else []
            log(f"node {version}: flags={flags} sqlite={probe.get('database_sync_importable')}")

            for command in REQUIRED_COMMANDS:
                result = run_command(str(runtime["binary"]), flags, bundle_dir, command, workdir, env)
                result.update({"node_version": version, "required": require, "kind": "required"})
                results.append(result)
                status = "PASS" if result["passed"] else "FAIL"
                log(f"  [{version}] node opencode.mjs {' '.join(command)}: {status} (exit {result['exit_code']})")
                if require and not result["passed"]:
                    required_failure = result

            # An FFI-capable runtime must not enter the renderer with piped
            # stdin. This regressed when the iOS no-FFI fallback became optional.
            for command in ([], ["mini"]):
                result = run_command(str(runtime["binary"]), flags, bundle_dir, command, workdir, env)
                stderr = str(result["stderr"])
                output = str(result["stdout"]) + stderr
                result["passed"] = (
                    result["exit_code"] == 1
                    and stderr.startswith("Interactive mode requires a TTY (stdin and stdout).")
                    and "opencode run" in stderr
                    and "Interactive TUI is not available" not in output
                    and "\x1b[?1049h" not in output
                    and "Starting background server" not in output
                )
                result.update({"node_version": version, "required": require, "kind": "required"})
                results.append(result)
                status = "PASS" if result["passed"] else "FAIL"
                log(f"  [{version}] non-TTY {' '.join(command) or 'default'}: {status} (exit {result['exit_code']})")
                if require and not result["passed"]:
                    required_failure = result

            version_results = [item for item in results if item["node_version"] == version]
            if all(item["passed"] for item in version_results if item["kind"] == "required"):
                for command in DEEP_COMMANDS:
                    result = run_command(str(runtime["binary"]), flags, bundle_dir, command, workdir, env)
                    result.update({"node_version": version, "required": False, "kind": "informational"})
                    results.append(result)
                    status = "PASS" if result["passed"] else "FAIL"
                    log(f"  [{version}] node opencode.mjs {' '.join(command)}: {status} (exit {result['exit_code']})")
            else:
                skipped = {
                    "node_version": version,
                    "required": False,
                    "kind": "informational",
                    "command": ["deep commands"],
                    "argv": [],
                    "flags": flags,
                    "exit_code": None,
                    "passed": False,
                    "duration_ms": 0,
                    "stdout": "",
                    "stderr": "skipped: required commands failed for this version",
                }
                results.append(skipped)
                log(f"  [{version}] deeper commands skipped (required commands failed)")
    finally:
        if not args.keep_workdir:
            shutil.rmtree(home, ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)

    versions_tested = sorted({str(item["node_version"]) for item in results})
    required_results = [item for item in results if item.get("required")]
    report = {
        "label": "Host-Node smoke tests on the build runner — NOT device verification",
        "bundle_dir": bundle_dir,
        "required_node_version": args.require_version,
        "host": {
            "platform": sys.platform,
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "runtimes": runtimes,
        "sqlite": sqlite,
        "results": results,
        "summary": {
            "versions_tested": versions_tested,
            "required_node_version": args.require_version,
            "required": [{"command": item["command"], "passed": item["passed"]} for item in required_results],
            "required_passed": bool(required_results) and all(item["passed"] for item in required_results),
            "all_host_versions_version_help_passed": all(
                item["passed"] for item in results if item["kind"] == "required"
            ),
            "informational_passed": sum(1 for item in results if item["kind"] == "informational" and item["passed"]),
            "informational_total": sum(1 for item in results if item["kind"] == "informational"),
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    log(f"report written to {args.report}")

    if not report["summary"]["required_passed"]:
        failure = required_failure or {}
        log(
            f"REQUIRED smoke test failed on Node {args.require_version}: "
            f"{' '.join(failure.get('command', []))} exit={failure.get('exit_code')}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
