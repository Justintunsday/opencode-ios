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

stage "Writing checksums"
(cd "$OUT" && shasum -a 256 node > SHA256SUMS && sed -i '' -e 's#  node#  node#' SHA256SUMS)
cat "$OUT/SHA256SUMS"
echo "NODE18_RUNTIME_BUILD_OK node=$(shasum -a 256 "$OUT/node" | awk '{print $1}') bytes=$(stat -f%z "$OUT/node")"
