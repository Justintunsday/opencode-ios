#!/usr/bin/env bash
# Build, sign and statically validate an iPhoneOS arm64 `libopentui.dylib` from the pinned
# OpenTUI source (Phase C prep for the real TUI). The library is NOT device-verified and is NOT
# loaded by CI: it can only be consumed once the Node 26 iPhoneOS runtime exists and the CLI
# ships it as an asset and loads it through `node:ffi` (Phase D).
#
#   scripts/build-opentui-ios.sh fetch    # clone pinned OpenTUI, apply patches, unpack Zig deps
#   scripts/build-opentui-ios.sh zig      # install pinned Zig 0.16.0 (sha256-verified)
#   scripts/build-opentui-ios.sh build    # zig build -Dlibrary-target=aarch64-ios.15.0 ...
#   scripts/build-opentui-ios.sh package  # locate, ldid-sign, statically validate, manifest
#   scripts/build-opentui-ios.sh validate # static validation only (existing dylib)
#   scripts/build-opentui-ios.sh all      # fetch + zig + build + package (CI entry point)
#
# Requires: macOS host with Xcode command line tools (xcrun/otool/vtool), git, python3, curl,
# shasum. Zig is downloaded into the build dir; ldid is installed with Homebrew when missing.
# Not needed on device: this script only produces a build artifact.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
absolute_path() {
  case "$1" in
    /*) echo "$1" ;;
    *) echo "$ROOT/$1" ;;
  esac
}
BUILD_DIR="$(absolute_path "${OPENTUI_BUILD_DIR:-$ROOT/dist/opentui-build}")"
SRC="$(absolute_path "${OPENTUI_SRC:-$BUILD_DIR/opentui}")"
PATCHES_DIR="$ROOT/patches/opentui-ios"
DIST="$(absolute_path "${OPENTUI_DIST:-$ROOT/dist/opentui-ios-renderer}")"
IOS_SDK="${IOS_SDK_PATH:-}"

OPENTUI_REPO="${OPENTUI_REPO:-https://github.com/anomalyco/opentui.git}"
OPENTUI_REF="${OPENTUI_REF:-v0.8.0}"
OPENTUI_COMMIT="${OPENTUI_COMMIT:-738067f47e940dcec3f5aab74868908574335c6c}"

ZIG_VERSION="0.16.0"
ZIG_MACOS_AARCH64_SHA256="b23d70deaa879b5c2d486ed3316f7eaa53e84acf6fc9cc747de152450d401489"
ZIG_MACOS_X86_64_SHA256=""
ZIG_LINUX_X86_64_SHA256="70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00"
# Community mirrors first (ziglang.org asks CI to spread load); ziglang.org is the last resort.
ZIG_MIRRORS=(
  "https://pkg.hexops.org/zig"
  "https://zigmirror.hryx.net/zig"
  "https://zig.linus.dev/zig"
  "https://zig.squirl.dev"
  "https://zig.mirror.mschae23.de/zig"
  "https://ziglang.freetls.fastly.net"
  "https://zig.tilok.dev"
)

TARGET="${OPENTUI_IOS_TARGET:-aarch64-ios.15.0}"
MAX_MINOS="${OPENTUI_IOS_MAX_MINOS:-16.1.1}"
UUCODE_TABLES_GZ="$PATCHES_DIR/files/uucode-tables.zig.gz"
DYLIB_NAME="libopentui.dylib"
ARTIFACT_NAME="opentui-ios-renderer"

log() { printf '[opentui-ios] %s\n' "$*"; }
die() { printf '[opentui-ios] ERROR: %s\n' "$*" >&2; exit 1; }

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

require_macos() {
  [ "$(uname -s)" = "Darwin" ] || die "this build must run on macOS with Xcode (iPhoneOS SDK + otool/vtool)"
  command -v xcrun >/dev/null 2>&1 || die "xcrun not found (install Xcode command line tools)"
}

# --- Zig ---------------------------------------------------------------------
zig_archive() {
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) echo "zig-aarch64-macos-$ZIG_VERSION.tar.xz" ;;
    Darwin-x86_64) echo "zig-x86_64-macos-$ZIG_VERSION.tar.xz" ;;
    Linux-x86_64) echo "zig-x86_64-linux-$ZIG_VERSION.tar.xz" ;;
    *) die "no pinned Zig archive for $(uname -s) $(uname -m)" ;;
  esac
}

zig_expected_sha() {
  case "$(zig_archive)" in
    "zig-aarch64-macos-$ZIG_VERSION.tar.xz") echo "$ZIG_MACOS_AARCH64_SHA256" ;;
    "zig-x86_64-linux-$ZIG_VERSION.tar.xz") echo "$ZIG_LINUX_X86_64_SHA256" ;;
    *) die "no pinned Zig sha256 for $(zig_archive)" ;;
  esac
}

zig_bin() {
  local archive expected dir
  archive="$(zig_archive)"
  expected="${archive%.tar.xz}"
  dir="$BUILD_DIR/zig/${ZIG_VERSION}-$(uname -s)-$(uname -m)"
  echo "$dir/$expected/zig"
}

cmd_zig() {
  local archive sha dir bin expected tmp
  archive="$(zig_archive)"
  sha="$(zig_expected_sha)"
  expected="${archive%.tar.xz}"
  dir="$BUILD_DIR/zig/${ZIG_VERSION}-$(uname -s)-$(uname -m)"
  bin="$dir/$expected/zig"
  if [ -x "$bin" ] && [ "$("$bin" version)" = "$ZIG_VERSION" ]; then
    log "Zig $ZIG_VERSION already installed at $bin"
    return 0
  fi

  mkdir -p "$dir"
  tmp="$BUILD_DIR/zig/$archive"
  local ok=0 url
  for url in "${ZIG_MIRRORS[@]}" "https://ziglang.org/download/$ZIG_VERSION"; do
    log "fetching $archive from $url"
    if curl -fsSL --connect-timeout 15 --max-time 300 -o "$tmp" "$url/$archive"; then
      if [ "$(sha256_file "$tmp")" = "$sha" ]; then ok=1; break; fi
      log "checksum mismatch from $url"
    fi
    rm -f "$tmp"
  done
  [ "$ok" = "1" ] || die "could not download a sha256-verified Zig $ZIG_VERSION archive"
  rm -rf "$dir"
  mkdir -p "$dir"
  tar -xJf "$tmp" -C "$dir"
  [ -x "$bin" ] || die "zig archive layout unexpected: $bin missing"
  log "Zig installed: $("$bin" version) ($bin)"
}

# --- fetch / patches ---------------------------------------------------------
cmd_fetch() {
  require_macos
  mkdir -p "$BUILD_DIR"
  if [ ! -d "$SRC/.git" ]; then
    log "cloning $OPENTUI_REPO @ $OPENTUI_REF"
    git clone --depth 1 --branch "$OPENTUI_REF" "$OPENTUI_REPO" "$SRC" 2>&1 | tail -2
  fi
  git -C "$SRC" fetch --depth 1 origin "$OPENTUI_REF" >/dev/null 2>&1 || true
  git -C "$SRC" checkout -f "$OPENTUI_REF" >/dev/null 2>&1 || die "cannot check out $OPENTUI_REF"
  local actual
  actual="$(git -C "$SRC" rev-parse HEAD)"
  [ "$actual" = "$OPENTUI_COMMIT" ] || die "pinned commit mismatch: expected $OPENTUI_COMMIT, got $actual"

  local patch
  for patch in "$PATCHES_DIR"/*.patch; do
    [ -f "$patch" ] || continue
    log "applying $(basename "$patch")"
    git -C "$SRC" apply --check --whitespace=nowarn "$patch" ||
      die "patch does not apply: $(basename "$patch") (upstream ref changed?)"
    git -C "$SRC" apply --whitespace=nowarn "$patch"
  done

  log "unpacking vendored Zig dependencies"
  (cd "$SRC/packages/native" && sh scripts/prepare-zig-deps.sh)
  [ -d "$SRC/packages/native/zig-deps/yoga" ] || die "Zig dependency unpack failed"
}

# --- build -------------------------------------------------------------------
cmd_build() {
  require_macos
  [ -d "$SRC/packages/native" ] || die "OpenTUI source missing (run: $0 fetch)"
  [ -d "$SRC/packages/native/zig-deps" ] || die "Zig deps missing (run: $0 fetch)"
  local bin
  bin="$(zig_bin)"
  [ -x "$bin" ] || { log "installing Zig first"; cmd_zig; }
  bin="$(zig_bin)"

  if [ -z "$IOS_SDK" ]; then
    IOS_SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
  fi
  [ -n "$IOS_SDK" ] && [ -d "$IOS_SDK" ] || die "iPhoneOS SDK not found (xcrun --sdk iphoneos --show-sdk-path)"
  log "iPhoneOS SDK: $IOS_SDK"
  log "SDK version: $(xcrun --sdk iphoneos --show-sdk-version 2>/dev/null || echo unknown)"

  # Vendored pre-generated uucode tables: the iOS build must not compile/run the native
  # uucode_generate host tool, because the global --sysroot (iPhoneOS SDK) would otherwise be
  # applied to that host executable and it would link against iPhoneOS libSystem.
  [ -f "$UUCODE_TABLES_GZ" ] || die "missing vendored uucode tables: $UUCODE_TABLES_GZ"
  log "extracting vendored uucode tables (skips the host table generator)"
  gzip -dc "$UUCODE_TABLES_GZ" >"$SRC/packages/native/uucode-tables.zig" ||
    die "failed to extract vendored uucode tables"

  local logfile="$BUILD_DIR/zig-build.log"
  mkdir -p "$BUILD_DIR"
  log "zig build -Dlibrary-target=$TARGET -Doptimize=ReleaseFast (log: $logfile)"
  set +e
  (
    cd "$SRC/packages/native"
    ZIG_GLOBAL_CACHE_DIR="$BUILD_DIR/zig-cache/global" ZIG_LOCAL_CACHE_DIR="$BUILD_DIR/zig-cache/local" \
      "$bin" build -Dlibrary-target="$TARGET" -Doptimize=ReleaseFast -Dios-sdk="$IOS_SDK" -Duucode-tables=uucode-tables.zig --sysroot "$IOS_SDK" --summary all
  ) >"$logfile" 2>&1
  local rc=$?
  set -e
  tail -40 "$logfile"
  [ "$rc" = "0" ] || die "zig build failed (exit $rc); full log: $logfile"
  log "build succeeded"
}

# --- package / validate ------------------------------------------------------
find_dylib() {
  local candidate
  for candidate in \
    "$SRC/packages/native/zig-out/lib/aarch64-ios/$DYLIB_NAME" \
    "$SRC/packages/native/zig-out/lib/$TARGET/$DYLIB_NAME"; do
    [ -f "$candidate" ] && { echo "$candidate"; return 0; }
  done
  die "built $DYLIB_NAME not found under $SRC/packages/native/zig-out/lib/"
}

validate_macho() {
  local lib="$1"
  python3 - "$lib" "$MAX_MINOS" <<'PY'
import struct
import sys

path, max_minos = sys.argv[1], tuple(int(part) for part in sys.argv[2].split("."))
MH_MAGIC_64 = 0xFEEDFACF
MH_DYLIB = 6
CPU_TYPE_ARM64 = 0x0100000C
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_IPHONEOS = 0x25
PLATFORM_IOS = 2

with open(path, "rb") as handle:
    header = handle.read(32)
    if len(header) != 32:
        raise SystemExit("Mach-O header truncated")
    magic, cpu, _subtype, filetype, commands, sizeofcmds, _flags, _reserved = struct.unpack("<8I", header)
    if magic != MH_MAGIC_64:
        raise SystemExit("not a thin little-endian 64-bit Mach-O")
    if cpu != CPU_TYPE_ARM64:
        raise SystemExit(f"not arm64 (cputype=0x{cpu:08x})")
    if filetype != MH_DYLIB:
        raise SystemExit(f"not a dynamic library (filetype={filetype}, expected {MH_DYLIB})")
    if commands > 10000 or sizeofcmds > 16 * 1024 * 1024:
        raise SystemExit("unreasonable Mach-O load command size")
    payload = handle.read(sizeofcmds)
if len(payload) != sizeofcmds:
    raise SystemExit("truncated Mach-O load commands")

platforms = []
pos = 0
for _ in range(commands):
    cmd, size = struct.unpack_from("<II", payload, pos)
    if size < 8 or pos + size > len(payload):
        raise SystemExit("malformed load command")
    if cmd == LC_BUILD_VERSION:
        if size < 24:
            raise SystemExit("truncated LC_BUILD_VERSION")
        platform, minos = struct.unpack_from("<II", payload, pos + 8)
        if platform != PLATFORM_IOS:
            raise SystemExit(f"Mach-O targets platform {platform} (requires iPhoneOS=2)")
        platforms.append(((minos >> 16) & 0xFFFF, (minos >> 8) & 0xFF, minos & 0xFF))
    elif cmd == LC_VERSION_MIN_IPHONEOS:
        minos, = struct.unpack_from("<I", payload, pos + 8)
        platforms.append(((minos >> 16) & 0xFFFF, (minos >> 8) & 0xFF, minos & 0xFF))
    pos += size
if pos != len(payload):
    raise SystemExit("unaccounted Mach-O command bytes")
if len(platforms) != 1:
    raise SystemExit(f"expected exactly one iOS platform command, found {platforms}")
minos = platforms[0]
if minos > max_minos:
    raise SystemExit(f"minOS {minos} exceeds {max_minos}")
print(f"Mach-O OK: arm64 dylib platform iOS minOS {minos[0]}.{minos[1]}.{minos[2]}")
PY
}

cmd_validate() {
  require_macos
  local lib
  lib="${1:-$DIST/$DYLIB_NAME}"
  [ -f "$lib" ] || die "dylib not found: $lib"
  log "Mach-O audit: $lib"
  validate_macho "$lib"

  log "otool -L dependency audit"
  xcrun otool -L "$lib" | tee "$DIST/otool-L.txt"
  local deps bad
  deps="$(xcrun otool -L "$lib" | tail -n +2 | awk 'NF {print $1}')"
  bad="$(printf '%s\n' "$deps" | grep -vE '^(/usr/lib/|/System/Library/Frameworks/)' || true)"
  [ -z "$bad" ] || die "non-iOS-system dylib dependency detected: $bad"

  log "vtool build platform audit"
  xcrun vtool -show-build "$lib" | tee "$DIST/vtool.txt"
  grep -q 'platform IOS' "$DIST/vtool.txt" || die "vtool did not report platform IOS"

  log "ldid signature audit"
  if ! command -v ldid >/dev/null 2>&1; then
    log "WARNING: ldid not installed yet; skipping embedded-signature audit (package installs it)"
    return 0
  fi
  ldid -e "$lib" >"$DIST/entitlements-signed.xml" 2>&1 ||
    die "dylib is not ldid-signed (ldid -e failed)"
  if ! grep -q 'platform-application' "$DIST/entitlements-signed.xml"; then
    # A dylib without embedded entitlements is still a signed Mach-O; ldid -S (ad-hoc) emits an
    # empty entitlement blob, which is acceptable for a library. Only require a code signature.
    log "WARNING: no embedded entitlements blob (ad-hoc signature retained)"
  fi
  log "signature audit done"
}

cmd_package() {
  require_macos
  local src_lib lib
  src_lib="$(find_dylib)"
  mkdir -p "$DIST"
  log "staging $src_lib -> $DIST/$DYLIB_NAME"
  cp -f "$src_lib" "$DIST/$DYLIB_NAME"
  chmod 0644 "$DIST/$DYLIB_NAME"

  if ! command -v ldid >/dev/null 2>&1; then
    log "installing ldid (brew install ldid)"
    brew install ldid >/dev/null 2>&1 || die "ldid not installed and brew install ldid failed"
  fi
  log "ldid signing with the device-verified 2-key node entitlements"
  ldid -S"$ROOT/scripts/ios-runtime/entitlements.plist" "$DIST/$DYLIB_NAME"
  ldid -e "$DIST/$DYLIB_NAME" >"$DIST/entitlements-signed.xml" 2>&1 || true

  cmd_validate "$DIST/$DYLIB_NAME"

  local sha size sdk_version zig_version
  sha="$(sha256_file "$DIST/$DYLIB_NAME")"
  size="$(wc -c <"$DIST/$DYLIB_NAME" | tr -d ' ')"
  sdk_version="$(xcrun --sdk iphoneos --show-sdk-version 2>/dev/null || echo unknown)"
  zig_version="$("$(zig_bin)" version 2>/dev/null || echo "$ZIG_VERSION")"

  {
    echo "artifact=$ARTIFACT_NAME"
    echo "library=$DYLIB_NAME"
    echo "library_size=$size"
    echo "library_sha256=$sha"
    echo "target=$TARGET"
    echo "max_minos=$MAX_MINOS"
    echo "upstream_repo=$OPENTUI_REPO"
    echo "upstream_ref=$OPENTUI_REF"
    echo "upstream_commit=$OPENTUI_COMMIT"
    echo "zig_version=$zig_version"
    echo "ios_sdk_version=$sdk_version"
    echo "ios_sdk_path=$IOS_SDK"
    echo "signed_with=ldid $(command -v ldid) -S<2-key node entitlements>"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ -n "${GITHUB_RUN_ID:-}" ]; then
      echo "github_repository=$GITHUB_REPOSITORY"
      echo "github_run_id=$GITHUB_RUN_ID"
      echo "github_sha=$GITHUB_SHA"
    fi
    echo "patches:"
    local patch
    for patch in "$PATCHES_DIR"/*.patch; do
      [ -f "$patch" ] || continue
      echo "  - $(basename "$patch") sha256=$(sha256_file "$patch")"
    done
    echo ""
    echo "STATUS: build feasibility artifact -- NOT device-verified."
    echo "Phase D work: ship this dylib as a CLI asset, teach the iOS CLI resolver to accept"
    echo "ios-arm64, and launch/load it through Node 26 node:ffi on the device."
  } >"$DIST/opentui-ios-manifest.txt"

  {
    echo "=== file ==="; file "$DIST/$DYLIB_NAME"
    echo "=== otool -hv ==="; xcrun otool -hv "$DIST/$DYLIB_NAME"
  } >"$DIST/file.txt" 2>&1 || true

  (cd "$DIST" && shasum -a 256 "$DYLIB_NAME" opentui-ios-manifest.txt entitlements-signed.xml \
    otool-L.txt vtool.txt file.txt > SHA256SUMS)

  log "artifact: $DIST ($size bytes dylib)"
  log "dylib sha256: $sha"
}

cmd_all() {
  cmd_zig
  cmd_fetch
  cmd_build
  cmd_package
}

main() {
  local command="${1:-all}"
  case "$command" in
    zig) cmd_zig ;;
    fetch) cmd_fetch ;;
    build) cmd_build ;;
    package) cmd_package ;;
    validate) shift || true; cmd_validate "$@" ;;
    all) cmd_all ;;
    *) die "unknown command '$command' (zig|fetch|build|package|validate|all)" ;;
  esac
}

main "$@"
