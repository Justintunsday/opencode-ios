#!/usr/bin/env bash
# OpenCode iOS port — host-runtime CLI smoke test.
#
# Runs the packaged OpenCode CLI bundle on a *host* Node.js 22.9.0 (downloaded
# from nodejs.org with checksum verification) and exercises:
#   * node --version
#   * node <flags> opencode.mjs --version / --help  (direct bundle execution)
#   * the packaged /var/jb/usr/bin/opencode launcher via env overrides
#     (OPENCODE_IOS_PREFIX + OPENCODE_IOS_NODE) to prove flag ordering and
#     argument forwarding.
#
# This proves the JS bundle + launcher are runnable on the pinned Node.js
# version on macOS. It is NOT an on-device test: hosted CI cannot execute iOS
# arm64 binaries (see docs/VERIFICATION.md).
#
# Usage:
#   scripts/smoke-bundle-host.sh --bundle-dir DIR [--output FILE] \
#       [--launcher PATH] [--prefix DIR] [--work-dir DIR] \
#       [--node-bin PATH] [--node-version 22.9.0] [--expected-version 2.2.5]
#
# Exit code 0 iff every check passed. Always writes the JSON result when
# --output is supplied (also on failure).
set -u

BUNDLE_DIR=""
LAUNCHER=""
PREFIX=""
WORK_DIR=""
NODE_BIN=""
NODE_VERSION="22.9.0"
OUTPUT=""
EXPECTED_VERSION=""
TIMEOUT=120
KEEP_WORK=0

die() { echo "smoke-bundle-host: error: $*" >&2; exit 2; }
info() { echo "==> $*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --bundle-dir) BUNDLE_DIR="${2:-}"; shift 2 ;;
        --launcher) LAUNCHER="${2:-}"; shift 2 ;;
        --prefix) PREFIX="${2:-}"; shift 2 ;;
        --work-dir) WORK_DIR="${2:-}"; shift 2 ;;
        --node-bin) NODE_BIN="${2:-}"; shift 2 ;;
        --node-version) NODE_VERSION="${2:-}"; shift 2 ;;
        --output) OUTPUT="${2:-}"; shift 2 ;;
        --expected-version) EXPECTED_VERSION="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT="${2:-}"; shift 2 ;;
        --keep-work) KEEP_WORK=1; shift ;;
        -h|--help)
            sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[ -n "$BUNDLE_DIR" ] || die "--bundle-dir is required"
[ -d "$BUNDLE_DIR" ] || die "bundle directory not found: $BUNDLE_DIR"
[ -f "$BUNDLE_DIR/opencode.mjs" ] || die "opencode.mjs not found in $BUNDLE_DIR"
[ -n "$OUTPUT" ] || OUTPUT="$(pwd)/host-smoke.json"

if [ -n "$PREFIX" ] && [ -z "$LAUNCHER" ] && [ -f "$PREFIX/usr/bin/opencode" ]; then
    LAUNCHER="$PREFIX/usr/bin/opencode"
fi
if [ -n "$LAUNCHER" ]; then
    [ -f "$LAUNCHER" ] || die "launcher not found: $LAUNCHER"
fi

# ---------------------------------------------------------------- tooling ---
PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN=python3
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN=python
    else
        die "python3 is required to write the smoke JSON result"
    fi
fi

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        "$PYTHON_BIN" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}

WORK_DIR="${WORK_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/opencode-host-smoke.XXXXXX")}"
mkdir -p "$WORK_DIR/node" "$WORK_DIR/home" "$WORK_DIR/cwd" "$WORK_DIR/results"
HOME_DIR="$WORK_DIR/home"
RESULTS_TSV="$WORK_DIR/results.tsv"
: > "$RESULTS_TSV"

# ---------------------------------------------------------- node download ---
NODE=""
NODE_URL=""
NODE_PINNED="false"
NODE_CHECKSUM_VERIFIED="false"
SHASUMS_URL=""
NODE_ARCHIVE=""

cleanup() {
    if [ "$KEEP_WORK" = "0" ]; then
        rm -rf "$WORK_DIR"
    else
        info "work dir kept: $WORK_DIR"
    fi
}
trap cleanup EXIT INT TERM

if [ -n "$NODE_BIN" ]; then
    [ -x "$NODE_BIN" ] || die "provided node binary is not executable: $NODE_BIN"
    NODE="$NODE_BIN"
    info "using provided node binary: $NODE"
else
    case "$(uname -s)" in
        Darwin) NODE_OS="darwin" ;;
        Linux) NODE_OS="linux" ;;
        MINGW*|MSYS*|CYGWIN*) NODE_OS="win" ;;
        *) die "unsupported host OS for the pinned Node.js download: $(uname -s)" ;;
    esac
    case "$(uname -m)" in
        arm64|aarch64) NODE_ARCH="arm64" ;;
        x86_64|amd64) NODE_ARCH="x64" ;;
        *) die "unsupported host architecture: $(uname -m)" ;;
    esac
    if [ "$NODE_OS" = "win" ]; then
        NODE_ARCHIVE="node-v${NODE_VERSION}-win-${NODE_ARCH}.zip"
        NODE_REL="node.exe"
    else
        NODE_ARCHIVE="node-v${NODE_VERSION}-${NODE_OS}-${NODE_ARCH}.tar.gz"
        NODE_REL="bin/node"
    fi
    NODE_DIR="$WORK_DIR/node/node-v${NODE_VERSION}-${NODE_OS}-${NODE_ARCH}"
    NODE="$NODE_DIR/$NODE_REL"
    NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}"
    SHASUMS_URL="https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt"
    if [ ! -x "$NODE" ]; then
        info "downloading pinned host Node.js ${NODE_VERSION}: $NODE_URL"
        command -v curl >/dev/null 2>&1 || die "curl is required to download Node.js"
        curl -fsSL --retry 3 -o "$WORK_DIR/node/$NODE_ARCHIVE" "$NODE_URL" \
            || die "failed to download $NODE_URL"
        curl -fsSL --retry 3 -o "$WORK_DIR/node/SHASUMS256.txt" "$SHASUMS_URL" \
            || die "failed to download $SHASUMS_URL"
        EXPECTED_SHA="$(awk -v archive="$NODE_ARCHIVE" '$2 == archive { print $1 }' \
            "$WORK_DIR/node/SHASUMS256.txt")"
        [ -n "$EXPECTED_SHA" ] || die "no SHA256SUMS256 entry for $NODE_ARCHIVE"
        ACTUAL_SHA="$(sha256_of "$WORK_DIR/node/$NODE_ARCHIVE")"
        if [ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]; then
            die "SHA256 mismatch for $NODE_ARCHIVE: expected $EXPECTED_SHA got $ACTUAL_SHA"
        fi
        NODE_CHECKSUM_VERIFIED="true"
        info "checksum verified: sha256=$EXPECTED_SHA"
        if [ "$NODE_OS" = "win" ]; then
            unzip -q "$WORK_DIR/node/$NODE_ARCHIVE" -d "$WORK_DIR/node" \
                || die "failed to unzip $NODE_ARCHIVE"
        else
            tar -xzf "$WORK_DIR/node/$NODE_ARCHIVE" -C "$WORK_DIR/node" \
                || die "failed to extract $NODE_ARCHIVE"
        fi
        NODE_PINNED="true"
    fi
    [ -x "$NODE" ] || die "downloaded node binary missing: $NODE"
fi

# ------------------------------------------------------------- run checks ---
# run_limited SECONDS OUT ERR COMMAND... -> exit code (137 on timeout)
run_limited() {
    local seconds="$1" out="$2" err="$3"
    shift 3
    "$@" >"$out" 2>"$err" &
    local cmd_pid=$!
    ( sleep "$seconds"; kill -9 "$cmd_pid" 2>/dev/null ) >/dev/null 2>&1 &
    local guard_pid=$!
    local rc=0
    wait "$cmd_pid" || rc=$?
    kill "$guard_pid" 2>/dev/null || true
    wait "$guard_pid" 2>/dev/null || true
    if [ "$rc" -eq 137 ]; then
        echo "timed out after ${seconds}s" >>"$err"
    fi
    return "$rc"
}

record() {
    # record NAME STATUS EXIT COMMAND STDOUT_FILE STDERR_FILE
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" >>"$RESULTS_TSV"
    echo "[$2] $1 (exit $3)"
}

NODE_FLAGS="--experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings"
ASSETS_DIR="$BUNDLE_DIR/assets"
[ -d "$ASSETS_DIR" ] || ASSETS_DIR=""
CLI_ENV="HOME=$HOME_DIR OPENCODE_IOS=1"
if [ -n "$ASSETS_DIR" ]; then
    CLI_ENV="$CLI_ENV OPENCODE_NODE_ASSETS_DIR=$ASSETS_DIR"
fi
DIRECT_MJS="$BUNDLE_DIR/opencode.mjs"

# 1. host node version
if run_limited 30 "$WORK_DIR/results/node-version.out" "$WORK_DIR/results/node-version.err" \
        "$NODE" --version; then
    NODE_ACTUAL="$(tr -d '\r\n' < "$WORK_DIR/results/node-version.out")"
    if [ "$NODE_PINNED" = "true" ] && [ "$NODE_ACTUAL" != "v$NODE_VERSION" ]; then
        record node-version FAIL 0 "$NODE --version" \
            "$WORK_DIR/results/node-version.out" "$WORK_DIR/results/node-version.err"
    else
        record node-version PASS 0 "$NODE --version" \
            "$WORK_DIR/results/node-version.out" "$WORK_DIR/results/node-version.err"
    fi
else
    rc=$?
    record node-version FAIL "$rc" "$NODE --version" \
        "$WORK_DIR/results/node-version.out" "$WORK_DIR/results/node-version.err"
fi
NODE_ACTUAL="${NODE_ACTUAL:-unknown}"
info "host node: $NODE_ACTUAL ($NODE)"

# 2. direct bundle execution: --version
if run_limited "$TIMEOUT" "$WORK_DIR/results/direct-version.out" "$WORK_DIR/results/direct-version.err" \
        env $CLI_ENV "$NODE" $NODE_FLAGS "$DIRECT_MJS" --version; then
    DIRECT_VERSION_OUT="$(cat "$WORK_DIR/results/direct-version.out")"
    if [ -n "$(printf '%s' "$DIRECT_VERSION_OUT" | tr -d '[:space:]')" ]; then
        record cli-version-direct PASS 0 "$NODE $NODE_FLAGS opencode.mjs --version" \
            "$WORK_DIR/results/direct-version.out" "$WORK_DIR/results/direct-version.err"
    else
        record cli-version-direct FAIL 0 "$NODE $NODE_FLAGS opencode.mjs --version" \
            "$WORK_DIR/results/direct-version.out" "$WORK_DIR/results/direct-version.err"
    fi
else
    rc=$?
    DIRECT_VERSION_OUT=""
    record cli-version-direct FAIL "$rc" "$NODE $NODE_FLAGS opencode.mjs --version" \
        "$WORK_DIR/results/direct-version.out" "$WORK_DIR/results/direct-version.err"
fi

# 3. pinned upstream version appears in --version output
if [ -n "$EXPECTED_VERSION" ]; then
    if printf '%s' "$DIRECT_VERSION_OUT" | grep -Fq "$EXPECTED_VERSION"; then
        printf '%s\n' "version output contains pinned upstream version $EXPECTED_VERSION" \
            >"$WORK_DIR/results/version-pinned.out"
        record cli-version-pinned PASS 0 \
            "grep '$EXPECTED_VERSION' <<< 'opencode.mjs --version'" \
            "$WORK_DIR/results/version-pinned.out" /dev/null
    else
        printf 'expected upstream version %s, got: %s\n' \
            "$EXPECTED_VERSION" "$(printf '%s' "$DIRECT_VERSION_OUT" | head -n 3)" \
            >"$WORK_DIR/results/version-pinned.out"
        record cli-version-pinned FAIL 0 \
            "grep '$EXPECTED_VERSION' <<< 'opencode.mjs --version'" \
            "$WORK_DIR/results/version-pinned.out" /dev/null
    fi
fi

# 4. direct bundle execution: --help
if run_limited "$TIMEOUT" "$WORK_DIR/results/direct-help.out" "$WORK_DIR/results/direct-help.err" \
        env $CLI_ENV "$NODE" $NODE_FLAGS "$DIRECT_MJS" --help; then
    if grep -qi "opencode" "$WORK_DIR/results/direct-help.out"; then
        record cli-help-direct PASS 0 "$NODE $NODE_FLAGS opencode.mjs --help" \
            "$WORK_DIR/results/direct-help.out" "$WORK_DIR/results/direct-help.err"
    else
        record cli-help-direct FAIL 0 "$NODE $NODE_FLAGS opencode.mjs --help" \
            "$WORK_DIR/results/direct-help.out" "$WORK_DIR/results/direct-help.err"
    fi
else
    rc=$?
    record cli-help-direct FAIL "$rc" "$NODE $NODE_FLAGS opencode.mjs --help" \
        "$WORK_DIR/results/direct-help.out" "$WORK_DIR/results/direct-help.err"
fi

# 5. launcher: --version (flag ordering + exec + env)
if [ -n "$LAUNCHER" ]; then
    LAUNCHER_PREFIX="${PREFIX:-}"
    LAUNCHER_ENV="HOME=$HOME_DIR OPENCODE_IOS=1 OPENCODE_IOS_NODE=$NODE"
    if [ -n "$LAUNCHER_PREFIX" ]; then
        LAUNCHER_ENV="$LAUNCHER_ENV OPENCODE_IOS_PREFIX=$LAUNCHER_PREFIX"
    fi
    if run_limited "$TIMEOUT" "$WORK_DIR/results/launcher-version.out" "$WORK_DIR/results/launcher-version.err" \
            env $LAUNCHER_ENV sh "$LAUNCHER" --version; then
        LAUNCHER_VERSION_OUT="$(cat "$WORK_DIR/results/launcher-version.out")"
        if [ "$(printf '%s' "$LAUNCHER_VERSION_OUT" | tr -d '[:space:]')" = \
             "$(printf '%s' "$DIRECT_VERSION_OUT" | tr -d '[:space:]')" ] && \
           [ -n "$(printf '%s' "$LAUNCHER_VERSION_OUT" | tr -d '[:space:]')" ]; then
            record launcher-version PASS 0 "sh $LAUNCHER --version" \
                "$WORK_DIR/results/launcher-version.out" "$WORK_DIR/results/launcher-version.err"
        else
            record launcher-version FAIL 0 "sh $LAUNCHER --version" \
                "$WORK_DIR/results/launcher-version.out" "$WORK_DIR/results/launcher-version.err"
        fi
    else
        rc=$?
        record launcher-version FAIL "$rc" "sh $LAUNCHER --version" \
            "$WORK_DIR/results/launcher-version.out" "$WORK_DIR/results/launcher-version.err"
    fi

    if run_limited "$TIMEOUT" "$WORK_DIR/results/launcher-help.out" "$WORK_DIR/results/launcher-help.err" \
            env $LAUNCHER_ENV sh "$LAUNCHER" --help; then
        if grep -qi "opencode" "$WORK_DIR/results/launcher-help.out"; then
            record launcher-help PASS 0 "sh $LAUNCHER --help" \
                "$WORK_DIR/results/launcher-help.out" "$WORK_DIR/results/launcher-help.err"
        else
            record launcher-help FAIL 0 "sh $LAUNCHER --help" \
                "$WORK_DIR/results/launcher-help.out" "$WORK_DIR/results/launcher-help.err"
        fi
    else
        rc=$?
        record launcher-help FAIL "$rc" "sh $LAUNCHER --help" \
            "$WORK_DIR/results/launcher-help.out" "$WORK_DIR/results/launcher-help.err"
    fi

    # 6. unknown flag must reach the CLI and be rejected: proves "$@" forwarding
    if run_limited "$TIMEOUT" "$WORK_DIR/results/launcher-unknown.out" "$WORK_DIR/results/launcher-unknown.err" \
            env $LAUNCHER_ENV sh "$LAUNCHER" --definitely-not-a-real-opencode-ios-flag; then
        # Exit 0 means the CLI silently swallowed the flag.
        record launcher-args-forwarded FAIL 0 \
            "sh $LAUNCHER --definitely-not-a-real-opencode-ios-flag (expected non-zero)" \
            "$WORK_DIR/results/launcher-unknown.out" "$WORK_DIR/results/launcher-unknown.err"
    else
        rc=$?
        record launcher-args-forwarded PASS "$rc" \
            "sh $LAUNCHER --definitely-not-a-real-opencode-ios-flag (non-zero = forwarded)" \
            "$WORK_DIR/results/launcher-unknown.out" "$WORK_DIR/results/launcher-unknown.err"
    fi
else
    record launcher-version SKIP 0 "no --launcher/--prefix supplied" /dev/null /dev/null
fi

# ---------------------------------------------------------------- results ---
FAILED_COUNT="$(awk -F'\t' '$2 == "FAIL" { c++ } END { print c + 0 }' "$RESULTS_TSV")"
TOTAL_COUNT="$(wc -l < "$RESULTS_TSV" | tr -d ' ')"
if [ "$FAILED_COUNT" -eq 0 ]; then
    SMOKE_STATUS="PASS"
else
    SMOKE_STATUS="FAIL"
fi

SMOKE_JSON_PATH="$OUTPUT" \
SMOKE_STATUS="$SMOKE_STATUS" \
SMOKE_BUNDLE_DIR="$BUNDLE_DIR" \
SMOKE_LAUNCHER="$LAUNCHER" \
SMOKE_NODE="$NODE" \
SMOKE_NODE_ACTUAL="$NODE_ACTUAL" \
SMOKE_NODE_PINNED="$NODE_PINNED" \
SMOKE_NODE_CHECKSUM_VERIFIED="$NODE_CHECKSUM_VERIFIED" \
SMOKE_NODE_URL="$NODE_URL" \
SMOKE_SHASUMS_URL="$SHASUMS_URL" \
SMOKE_EXPECTED_VERSION="$EXPECTED_VERSION" \
SMOKE_RESULTS_TSV="$RESULTS_TSV" \
SMOKE_WORK_DIR="$WORK_DIR" \
"$PYTHON_BIN" - <<'PY'
import json
import os
import platform
from datetime import datetime, timezone

results = []
with open(os.environ["SMOKE_RESULTS_TSV"], encoding="utf-8") as handle:
    for line in handle:
        line = line.rstrip("\n")
        if not line:
            continue
        name, status, exit_code, command, out_path, err_path = line.split("\t")

        def _read(path, limit=4000):
            if path in ("", "/dev/null") or not os.path.isfile(path):
                return ""
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    return fh.read()[:limit]
            except OSError:
                return ""

        results.append({
            "name": name,
            "status": status,
            "exit": int(exit_code),
            "command": command,
            "stdout": _read(out_path),
            "stderr": _read(err_path),
        })

payload = {
    "schema": 1,
    "kind": "host-cli-smoke",
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": os.environ["SMOKE_STATUS"],
    "bundle_dir": os.environ["SMOKE_BUNDLE_DIR"],
    "launcher": os.environ["SMOKE_LAUNCHER"],
    "expected_upstream_version": os.environ["SMOKE_EXPECTED_VERSION"],
    "node": {
        "path": os.environ["SMOKE_NODE"],
        "version": os.environ["SMOKE_NODE_ACTUAL"],
        "pinned": os.environ["SMOKE_NODE_PINNED"] == "true",
        "checksum_verified": os.environ["SMOKE_NODE_CHECKSUM_VERIFIED"] == "true",
        "url": os.environ["SMOKE_NODE_URL"],
        "shasums_url": os.environ["SMOKE_SHASUMS_URL"],
    },
    "host": {
        "platform": platform.platform(),
        "machine": platform.machine(),
    },
    "checks": results,
    "summary": {
        "total": len(results),
        "failed": sum(1 for r in results if r["status"] == "FAIL"),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "skipped": sum(1 for r in results if r["status"] == "SKIP"),
    },
}
out = os.environ["SMOKE_JSON_PATH"]
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY

echo ""
echo "host smoke: status=$SMOKE_STATUS node=$NODE_ACTUAL checks=$TOTAL_COUNT failures=$FAILED_COUNT"
echo "host smoke JSON: $OUTPUT"
if [ "$FAILED_COUNT" -ne 0 ]; then
    awk -F'\t' '$2 == "FAIL" { print "  FAILED: " $1 }' "$RESULTS_TSV"
    exit 1
fi
exit 0
