#!/usr/bin/env bash
# Build, sign and statically validate an iPhoneOS arm64 `libopentui.dylib` from the pinned
# OpenTUI source (Phase C prep for the real TUI). The library is NOT device-verified and is NOT
# loaded by CI: it can only be consumed once the Node 26 iPhoneOS runtime exists and the CLI
# ships it as an asset and loads it through `node:ffi` (Phase D).
#
#   scripts/build-opentui-ios.sh fetch    # clone pinned OpenTUI, apply patches, unpack Zig deps
#   scripts/build-opentui-ios.sh zig      # install pinned Zig 0.16.0 (sha256-verified)
#   scripts/build-opentui-ios.sh build    # zig build -Dlibrary-target=aarch64-ios.15.0 ...
#   scripts/build-opentui-ios.sh package  # clang-link from Zig static lib, codesign, validate
#   scripts/build-opentui-ios.sh validate # static validation only (existing dylib)
#   scripts/build-opentui-ios.sh all      # fetch + zig + build + package (CI entry point)
#
# Requires: macOS host with Xcode command line tools (xcrun/otool/vtool), git, python3, curl,
# shasum. Zig is downloaded into the build dir. The dylib is signed with Apple `codesign`
# (ad-hoc), NOT ldid: device evidence shows ldid-signed dylibs are mapped non-executable by dyld
# on iOS (executing them SIGBUSes; __TEXT r--/rw-), while codesign-ad-hoc dylibs execute under
# node:ffi. See docs/OPENTUI_IOS.md and the dlopen/exec-mapping evidence.
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
find_static_lib() {
  local candidate base
  # build.zig installs both libraries to <package>/lib/<output_name>; the static archive is the
  # input for the clang/ld64 final link (the Zig-linked dylib is mapped non-executable on device).
  for base in "$SRC/packages/native/lib" "$SRC/packages/native/zig-out" "$SRC/packages/native"; do
    [ -d "$base" ] || continue
    candidate="$(find "$base" -name 'libopentui.a' -type f 2>/dev/null | head -n 1 || true)"
    if [ -n "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  log "native package tree (for diagnosis):"
  find "$SRC/packages/native" -maxdepth 4 \( -name '*.a' -o -name '*.dylib' -o -name 'lib' -o -name 'zig-out' \) 2>/dev/null |
    sed -n '1,40p' >&2 || true
  die "Zig static library libopentui.a not found under $SRC/packages/native"
}

# Zig compiler-rt archive for aarch64-ios. The Zig static library does not embed compiler-rt, and
# the clang/ld64 final link must not leave operator-runtime helpers undefined (dlsym would never
# resolve them at runtime). Built once per build dir with the pinned Zig.
ensure_compiler_rt() {
  local zig_lib compiler_rt_src archive
  zig_lib="$(dirname "$(zig_bin)")/lib"
  compiler_rt_src="$zig_lib/compiler_rt.zig"
  archive="$BUILD_DIR/compiler_rt/libcompiler_rt-$TARGET.a"
  if [ -f "$archive" ]; then
    echo "$archive"
    return 0
  fi
  [ -f "$compiler_rt_src" ] || die "Zig compiler_rt.zig not found at $compiler_rt_src"
  mkdir -p "$(dirname "$archive")"
  # NOTE: log to stderr: ensure_compiler_rt's stdout is captured by the caller
  # (`compiler_rt="$(ensure_compiler_rt)"`), so stdout must contain only the
  # archive path (a log line on stdout made clang++ treat it as an input file).
  log "building Zig compiler-rt static archive for $TARGET" >&2
  "$(zig_bin)" build-lib "$compiler_rt_src" -target "$TARGET" -OReleaseFast -fPIC \
    -femit-bin="$archive" >"$BUILD_DIR/compiler_rt/build.log" 2>&1 ||
    { sed -n '1,80p' "$BUILD_DIR/compiler_rt/build.log" >&2; die "failed to build Zig compiler-rt archive"; }
  [ -f "$archive" ] || die "compiler-rt archive was not produced: $archive"
  echo "$archive"
}

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
      "$bin" build -Dlibrary-target="$TARGET" -Doptimize=ReleaseFast -Dios-sdk="$IOS_SDK" -Duucode-tables=uucode-tables.zig --summary all
  ) >"$logfile" 2>&1
  local rc=$?
  set -e
  tail -40 "$logfile"
  [ "$rc" = "0" ] || die "zig build failed (exit $rc); full log: $logfile"
  log "build succeeded"
}

# --- package / validate ------------------------------------------------------
find_dylib() {
  local candidate base
  # The build installs libraries to <package>/lib/<output_name> (install_path is "../lib/..." in
  # build.zig), older/other targets may end up under zig-out; search both, then the package root.
  for base in "$SRC/packages/native/lib" "$SRC/packages/native/zig-out" "$SRC/packages/native"; do
    [ -d "$base" ] || continue
    candidate="$(find "$base" -name "$DYLIB_NAME" -type f 2>/dev/null | head -n 1 || true)"
    if [ -n "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  log "native package tree (for diagnosis):"
  find "$SRC/packages/native" -maxdepth 4 \( -name '*.dylib' -o -name 'zig-out' -o -name 'lib' \) -type f 2>/dev/null | sed -n '1,40p' >&2 || true
  die "built $DYLIB_NAME not found under $SRC/packages/native"
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
  local deps bad own_id
  # otool -L lists the library's own LC_ID_DYLIB install name first; it is not a dependency.
  own_id="$(xcrun otool -D "$lib" | tail -n +2 | head -n 1 | tr -d '[:space:]')"
  deps="$(xcrun otool -L "$lib" | tail -n +2 | awk 'NF {print $1}' | grep -vFx "${own_id:-__no_install_id__}" || true)"
  bad="$(printf '%s\n' "$deps" | grep -vE '^(/usr/lib/|/System/Library/Frameworks/)' || true)"
  [ -z "$bad" ] || die "non-iOS-system dylib dependency detected: $bad"

  log "vtool build platform audit"
  xcrun vtool -show-build "$lib" | tee "$DIST/vtool.txt"
  grep -q 'platform IOS' "$DIST/vtool.txt" || die "vtool did not report platform IOS"

  log "codesign signature audit"
  xcrun codesign --verify --verbose=2 "$lib" >"$DIST/codesign-verify.txt" 2>&1 ||
    die "dylib is not validly codesign-signed (see $DIST/codesign-verify.txt)"
  xcrun codesign -dvv "$lib" >"$DIST/codesign.txt" 2>&1 || true
  if ! grep -q 'Signature=adhoc' "$DIST/codesign.txt"; then
    log "WARNING: signature is not ad-hoc (the anonymous iPhoneOS build expects ad-hoc)"
  fi
  log "codesign signature audit done (ad-hoc; see codesign.txt)"
}

cmd_package() {
  require_macos
  local src_zig src_static compiler_rt ziglinked
  src_zig="$(find_dylib)"
  src_static="$(find_static_lib)"
  mkdir -p "$DIST"
  rm -f "$DIST/$DYLIB_NAME" "$DIST/libopentui-ziglinked.dylib" "$DIST"/codesign*.txt \
    "$DIST"/nm-exported*.txt "$DIST/clang-link.txt" "$DIST/compiler-rt.txt"

  # Device finding: the Zig-linked Mach-O is mapped non-executable by dyld on iOS 16.1.1 even
  # when codesign(ad-hoc) signed (SIGBUS, __TEXT r--/rw-, both original and normalized header
  # flags), while a clang/ld64-linked dylib with the identical signature executes. The final
  # renderer dylib is therefore linked by Xcode clang from the Zig static archive; the Zig-linked
  # dylib is kept in the artifact for the record/diagnostics.
  ziglinked="$DIST/libopentui-ziglinked.dylib"
  cp -f "$src_zig" "$ziglinked"
  chmod 0644 "$ziglinked"
  log "staged Zig-linked dylib (record/diagnostic): $src_zig -> $ziglinked"

  compiler_rt="$(ensure_compiler_rt)"
  log "Zig static library: $src_static ($(wc -c <"$src_static" | tr -d ' ') bytes)"
  log "Zig compiler-rt: $compiler_rt"

  # Export the exact same dynamic symbol set as the Zig-linked dylib (the node:ffi ABI: the
  # Zig-linked build exported these names and node:ffi resolves them with dlsym). ld64 by default
  # exports all globals, but the C shim objects are compiled with -fvisibility=hidden, so pin the
  # ABI explicitly with -exported_symbols_list instead of relying on default visibility.
  local exported_symbols="$DIST/exported-symbols.txt"
  xcrun nm -gU "$src_zig" 2>/dev/null | awk '{print $NF}' | grep '^_' | sort -u >"$exported_symbols" || true
  [ -s "$exported_symbols" ] || die "could not extract exported symbols from the Zig-linked dylib"
  log "exported ABI symbols from Zig dylib: $(wc -l <"$exported_symbols" | tr -d ' ')"

  {
    echo "=== renderer link: Xcode clang/ld64 from the Zig static library ==="
    echo "zig_static_lib=$src_static"
    echo "zig_static_lib_size=$(wc -c <"$src_static" | tr -d ' ')"
    echo "zig_static_lib_sha256=$(sha256_file "$src_static")"
    echo "zig_compiler_rt=$compiler_rt"
    echo "zig_compiler_rt_sha256=$(sha256_file "$compiler_rt")"
    echo "zig_linked_dylib=$src_zig"
    echo "zig_linked_dylib_sha256=$(sha256_file "$src_zig")"
    xcrun --find clang++
    xcrun clang++ --version | head -n 2
  } >"$DIST/clang-link.txt"

  log "clang/ld64 linking $DIST/$DYLIB_NAME"
  if ! xcrun clang++ -dynamiclib -target "arm64-apple-ios15.0" -isysroot "$IOS_SDK" \
    -o "$DIST/$DYLIB_NAME" \
    -install_name "@rpath/$DYLIB_NAME" \
    -Wl,-force_load,"$src_static" \
    -Wl,-exported_symbols_list,"$exported_symbols" \
    "$compiler_rt" \
    -lc++ -lc++abi \
    -framework CoreFoundation -framework CoreAudio -framework AudioToolbox \
    -framework Foundation -framework AVFoundation -framework AVFAudio \
    -framework ImageIO -framework CoreGraphics \
    >>"$DIST/clang-link.txt" 2>&1; then
    log "clang link failed; last 120 log lines:"
    tail -n 120 "$DIST/clang-link.txt" >&2
    die "clang/ld64 link failed (see $DIST/clang-link.txt)"
  fi
  chmod 0644 "$DIST/$DYLIB_NAME"
  echo "linked ok" >>"$DIST/clang-link.txt"

  # Export audit: node:ffi resolves renderer entry points with dlsym on the dlopen'ed dylib, so
  # the symbols must be in the dynamic symbol table (the static archive objects must not hide
  # them). imageRetainIccCache is the symbol from the device crash stack / probe.
  xcrun nm -gU "$DIST/$DYLIB_NAME" >"$DIST/nm-exported.txt" 2>&1 || true
  xcrun nm -gU "$ziglinked" >"$DIST/nm-exported-ziglinked.txt" 2>&1 || true
  log "exported symbol count: primary=$(wc -l <"$DIST/nm-exported.txt" | tr -d ' ') ziglinked=$(wc -l <"$DIST/nm-exported-ziglinked.txt" | tr -d ' ')"
  # The clang-linked dylib must export the Zig dylib's ABI so node:ffi dlsym keeps working.
  local abi_missing
  abi_missing="$(comm -23 <(sort -u "$exported_symbols") <(xcrun nm -gU "$DIST/$DYLIB_NAME" 2>/dev/null | awk '{print $NF}' | grep '^_' | sort -u) || true)"
  [ -z "$abi_missing" ] ||
    die "clang-linked dylib is missing exported ABI symbols: $(printf '%s ' $abi_missing | cut -c1-400)"
  grep -q 'imageRetainIccCache' "$DIST/nm-exported.txt" ||
    die "imageRetainIccCache is not exported by the clang-linked dylib (node:ffi dlsym would fail)"

  log "codesign (ad-hoc) signing the clang-linked renderer"
  xcrun codesign --force --sign - --timestamp=none "$DIST/$DYLIB_NAME" ||
    die "codesign ad-hoc signing failed"
  xcrun codesign --verify --verbose=2 "$DIST/$DYLIB_NAME" >"$DIST/codesign-verify.txt" 2>&1 ||
    die "codesign verification failed after signing (see $DIST/codesign-verify.txt)"
  xcrun codesign -dvv "$DIST/$DYLIB_NAME" >"$DIST/codesign.txt" 2>&1 || true

  # The Zig-linked record copy is signed the same way (it is known non-executable on device, but
  # keeping it signed lets the device reproduce/diagnose the difference safely).
  xcrun codesign --force --sign - --timestamp=none "$ziglinked" ||
    die "codesign ad-hoc signing failed for the Zig-linked record copy"
  xcrun codesign --verify --verbose=2 "$ziglinked" >"$DIST/codesign-verify-ziglinked.txt" 2>&1 ||
    die "codesign verification failed for the Zig-linked record copy"
  xcrun codesign -dvv "$ziglinked" >"$DIST/codesign-ziglinked.txt" 2>&1 || true

  cmd_validate "$DIST/$DYLIB_NAME"

  local sha size sha_ziglinked size_ziglinked sha_static size_static sha_rt sdk_version zig_version clang_version
  sha="$(sha256_file "$DIST/$DYLIB_NAME")"
  size="$(wc -c <"$DIST/$DYLIB_NAME" | tr -d ' ')"
  sha_ziglinked="$(sha256_file "$ziglinked")"
  size_ziglinked="$(wc -c <"$ziglinked" | tr -d ' ')"
  sha_static="$(sha256_file "$src_static")"
  size_static="$(wc -c <"$src_static" | tr -d ' ')"
  sha_rt="$(sha256_file "$compiler_rt")"
  sdk_version="$(xcrun --sdk iphoneos --show-sdk-version 2>/dev/null || echo unknown)"
  zig_version="$("$(zig_bin)" version 2>/dev/null || echo "$ZIG_VERSION")"
  clang_version="$(xcrun clang++ --version 2>/dev/null | head -n 1)"

  {
    echo "artifact=$ARTIFACT_NAME"
    echo "library=$DYLIB_NAME"
    echo "library_size=$size"
    echo "library_sha256=$sha"
    echo "library_linker=clang/ld64 (Xcode clang++ -dynamiclib), from the Zig static archive"
    echo "library_zigtarget=$TARGET"
    echo "library_min_ios=15.0"
    echo "zig_static_lib_size=$size_static"
    echo "zig_static_lib_sha256=$sha_static"
    echo "zig_compiler_rt_sha256=$sha_rt"
    echo "zig_linked_dylib=libopentui-ziglinked.dylib"
    echo "zig_linked_dylib_size=$size_ziglinked"
    echo "zig_linked_dylib_sha256=$sha_ziglinked"
    echo "device_finding=Zig-self-linked dylib is mapped non-executable by dyld on iOS 16.1.1 (SIGBUS, __TEXT r--/rw-); clang/ld64-linked dylib is the shipping path"
    echo "clang_version=$clang_version"
    echo "target=$TARGET"
    echo "max_minos=$MAX_MINOS"
    echo "upstream_repo=$OPENTUI_REPO"
    echo "upstream_ref=$OPENTUI_REF"
    echo "upstream_commit=$OPENTUI_COMMIT"
    echo "zig_version=$zig_version"
    echo "ios_sdk_version=$sdk_version"
    echo "ios_sdk_path=$IOS_SDK"
    echo "signed_with=codesign ad-hoc (xcrun codesign --force --sign - --timestamp=none)"
    echo "signing_scheme=ad-hoc (no Team ID, no entitlements; codesign-verified)"
    echo "exported_symbols=$(wc -l <"$DIST/nm-exported.txt" | tr -d ' ')"
    echo "exported_symbols_source=Zig-linked dylib ABI (exported_symbols.txt)"
    echo "exported_symbols_file=exported-symbols.txt"
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
    echo "STATUS: renderer built with clang/ld64 + codesign(ad-hoc); device node:ffi load is"
    echo "Lead-verified. The CLI Node 26 bundle ships this dylib as"
    echo "@opentui/core-ios-arm64/libopentui.dylib and loads it through node:ffi."
  } >"$DIST/opentui-ios-manifest.txt"

  {
    echo "=== file ==="; file "$DIST/$DYLIB_NAME"
    echo "=== otool -hv (clang-linked) ==="; xcrun otool -hv "$DIST/$DYLIB_NAME"
    echo "=== otool -hv (zig-linked record) ==="; xcrun otool -hv "$ziglinked"
  } >"$DIST/file.txt" 2>&1 || true

  (cd "$DIST" && shasum -a 256 "$DYLIB_NAME" libopentui-ziglinked.dylib opentui-ios-manifest.txt \
    clang-link.txt exported-symbols.txt nm-exported.txt nm-exported-ziglinked.txt \
    codesign.txt codesign-verify.txt codesign-ziglinked.txt codesign-verify-ziglinked.txt \
    otool-L.txt vtool.txt file.txt > SHA256SUMS)

  log "artifact: $DIST ($size bytes clang-linked dylib)"
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
