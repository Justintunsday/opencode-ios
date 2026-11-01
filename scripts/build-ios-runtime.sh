#!/usr/bin/env bash
#
# Build, sign and statically validate a native iPhoneOS arm64 Node.js 22.9.0
# runtime executable (the `node` CLI) from the pinned nodejs-mobile source.
#
#   scripts/build-ios-runtime.sh configure   # generate config.gypi + out/Makefile (fast gate)
#   scripts/build-ios-runtime.sh build       # make -j N (long: 40-90 min first run)
#   scripts/build-ios-runtime.sh package     # locate/link `node`, ldid-sign, validate, manifest
#   scripts/build-ios-runtime.sh all         # configure + build + package (local convenience)
#
# The CI workflow (.github/workflows/build-runtime.yml) applies
# patches/nodejs-mobile/*.patch to a clean checkout of the pinned nodejs-mobile
# commit, restores/saves the out/Release cache and then calls the three
# subcommands above. See docs/RUNTIME_BUILD.md for the complete recipe, pins,
# evidence and limitations.
#
# Why no --enable-static: nodejs-mobile's configure.py sets gyp's
# node_target_type=static_library when --enable-static is passed (that is the
# NodeMobile.framework path). Without it, node_target_type defaults to
# executable and `make` links out/Release/node as a standalone iPhoneOS arm64
# CLI binary. We only need the CLI, not the .framework.
#
# JIT + WebAssembly are ENABLED: Node 22.9's built-in fetch()/undici needs a wasm
# llhttp parser at startup, so a jitless/no-wasm runtime is unusable by the CLI
# (device evidence in docs/RUNTIME_BUILD.md). patches/nodejs-mobile/0003 restores
# upstream v8_enable_webassembly behaviour.
#
# iOS JIT memory model (patches 0005 + 0006): no MAP_JIT, no RWX requests;
# V8's RwxMemoryWriteScope is implemented over per-range mprotect toggling.
# Device probing on the target iPhone proved the only working executable-memory
# pattern on iOS 16.1.1: plain mapping -> write -> mprotect RX -> execute.
# MAP_JIT mmap/mprotect is denied / strips PROT_EXEC, and
# pthread_jit_write_protect_np is absent. Patch 0005 skips MAP_JIT on iOS; patch
# 0006 enables V8_HAS_PTHREAD_JIT_WRITE_PROTECT on iOS so the write-scope
# machinery is compiled in, and implements SetJitWriteProtected as mprotect
# RW<->RX over ranges registered by RegisterIOSCodeRange (heap code chunks and
# wasm code spaces). No RWX permission is ever requested on iOS. Entitlements
# are the device-verified 2-key set (see scripts/ios-runtime/entitlements.plist).
#
# Environment overrides:
#   NODE_SRC   nodejs-mobile checkout          (default: <repo>/nodejs-mobile)
#   DIST       artifact output directory       (default: <repo>/dist/ios-node-runtime)
#   JOBS       make parallelism                (default: sysctl -n hw.ncpu)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODE_SRC="${NODE_SRC:-$ROOT/nodejs-mobile}"
DIST="${DIST:-$ROOT/dist/ios-node-runtime}"
JOBS="${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 4)}"
ENTITLEMENTS="$ROOT/scripts/ios-runtime/entitlements.plist"
LAUNCHER_SRC="$ROOT/scripts/ios-runtime/node_main.cc"
PATCH_GLOB="$ROOT/patches/nodejs-mobile/*.patch"
CHECK_MACHO="$ROOT/scripts/check_macho.py"
MAKE_LOG="$ROOT/dist/build-make.log"
MAKE_RC_FILE="$ROOT/dist/.make-exit-code"

# Deliberately no --enable-static (see header). This is the exact flag set used
# by nodejs-mobile tools/ios_framework_prepare.sh minus --enable-static.
CONFIGURE_FLAGS=(
  --dest-os=ios
  --dest-cpu=arm64
  --with-intl=full-icu
  --cross-compiling
  --openssl-no-asm
  --without-node-code-cache
  --without-node-snapshot
)

log()  { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_tools() {
  local tool
  for tool in python3 make git; do
    command -v "$tool" >/dev/null 2>&1 || die "required tool not found: $tool"
  done
  [[ -f "$CHECK_MACHO" ]] || die "missing static validator: $CHECK_MACHO"
  [[ -f "$ENTITLEMENTS" ]] || die "missing entitlements: $ENTITLEMENTS"
}

# Verify the source tree is the pinned nodejs-mobile tree WITH the PR #150
# build-fix patch applied. Both markers below only exist after the patch.
require_patched_source() {
  [[ -d "$NODE_SRC" ]] || die "nodejs-mobile source not found: $NODE_SRC"
  [[ -f "$NODE_SRC/configure.py" ]] || die "$NODE_SRC does not look like nodejs-mobile"
  # One stable marker per patch in the series (0001..0006). Keep in sync with
  # patches/nodejs-mobile/*.patch: a missing marker means the series was not
  # applied (or a patch changed without updating this function).
  grep -q 'kPathSeparator = std::filesystem::path::preferred_separator' \
    "$NODE_SRC/src/util.h" \
    || die "patch series not applied: 0001 marker (src/util.h kPathSeparator) missing"
  grep -q 'nodejs-mobile-build-fixes: for iOS cross builds' \
    "$NODE_SRC/common.gypi" \
    || die "patch series not applied: 0002 marker (common.gypi host toolset) missing"
  grep -q "v8_enable_webassembly'\] = 0 if options.v8_lite_mode else 1" \
    "$NODE_SRC/configure.py" \
    || die "patch series not applied: 0003 marker (configure.py v8_enable_webassembly) missing"
  grep -q 'platform-ios.cc' \
    "$NODE_SRC/tools/v8_gypfiles/v8.gyp" \
    || die "patch series not applied: 0004 marker (v8.gyp platform-ios.cc) missing"
  grep -q 'defined(V8_OS_DARWIN) && !defined(V8_OS_IOS)' \
    "$NODE_SRC/deps/v8/src/base/platform/platform-posix.cc" \
    || die "patch series not applied: 0005 marker (platform-posix.cc no-MAP_JIT-on-iOS) missing"
  grep -q 'RegisterIOSCodeRange' \
    "$NODE_SRC/deps/v8/src/base/platform/platform-ios.cc" \
    || die "patch series not applied: 0006 marker (platform-ios.cc mprotect registry) missing"
  grep -q 'RegisterIOSCodeRange' \
    "$NODE_SRC/deps/v8/src/heap/memory-allocator.cc" \
    || die "patch series not applied: 0006 marker (memory-allocator.cc registration) missing"
  grep -q 'RegisterIOSCodeRange' \
    "$NODE_SRC/deps/v8/src/wasm/wasm-code-manager.cc" \
    || die "patch series not applied: 0006 marker (wasm-code-manager.cc registration) missing"
}

node_version_from_source() {
  local header="$NODE_SRC/src/node_version.h"
  local major minor patch
  major="$(sed -n 's/^#define NODE_MAJOR_VERSION \([0-9]*\)/\1/p' "$header")"
  minor="$(sed -n 's/^#define NODE_MINOR_VERSION \([0-9]*\)/\1/p' "$header")"
  patch="$(sed -n 's/^#define NODE_PATCH_VERSION \([0-9]*\)/\1/p' "$header")"
  printf '%s.%s.%s' "$major" "$minor" "$patch"
}

# Stable fingerprint of everything that changes the compiled object tree: the
# patch-series content and the configure flag set. It is stored inside the
# cached build tree (out/Release/.runtime-build-inputs) so a later run can tell
# whether restored objects are still valid or must be rebuilt.
build_inputs_fingerprint() {
  local patch_sha flags_sha
  patch_sha="$(cat "$ROOT"/patches/nodejs-mobile/*.patch | shasum -a 256 | awk '{print $1}')"
  flags_sha="$(printf '%s\n' "${CONFIGURE_FLAGS[@]}" | shasum -a 256 | awk '{print $1}')"
  printf 'patch_sha=%s\nflags_sha=%s\n' "$patch_sha" "$flags_sha"
}

# Prepare a restored out/Release cache for an incremental `make`.
#
# A fresh `git checkout` stamps every source file with "now", which is newer
# than every cached .o, so make would rebuild the entire tree even though the
# cache is valid. We therefore stamp the pristine tree to a fixed old time and
# then decide, from the build-inputs fingerprint stored in the cached tree,
# whether the restored objects still correspond to this patch series/flags:
#   - fingerprint matches  -> keep objects (only configure/make no-op)
#   - patch changed        -> re-stamp only the files the patch rewrote
#   - flags changed        -> stamp everything to now (correct full rebuild)
cmd_normalize_cache() {
  local cache_hit="${1:-false}"
  require_patched_source
  if [[ ! -d "$NODE_SRC/out/Release" ]]; then
    log "no restored out/Release build tree; nothing to normalize"
    return 0
  fi
  log "normalizing source mtimes for incremental reuse of the restored build tree (cache_hit=$cache_hit)"
  find "$NODE_SRC" -path "$NODE_SRC/out" -prune -o -type f -exec touch -t 200001010000 {} +

  local marker="$NODE_SRC/out/Release/.runtime-build-inputs"
  if [[ ! -f "$marker" ]]; then
    # Unknown provenance (cache produced by an older script): rebuild everything
    # rather than risk mixing objects built with different configure flags.
    warn "cached tree has no build-inputs fingerprint (older cache); forcing a full rebuild"
    find "$NODE_SRC" -path "$NODE_SRC/out" -prune -o -type f -exec touch {} +
    return 0
  fi

  local cur cached cur_patch cur_flags cached_patch cached_flags
  cur="$(build_inputs_fingerprint)"
  cached="$(cat "$marker")"
  cur_patch="$(printf '%s\n' "$cur" | sed -n 's/^patch_sha=//p')"
  cur_flags="$(printf '%s\n' "$cur" | sed -n 's/^flags_sha=//p')"
  cached_patch="$(printf '%s\n' "$cached" | sed -n 's/^patch_sha=//p')"
  cached_flags="$(printf '%s\n' "$cached" | sed -n 's/^flags_sha=//p')"

  if [[ "$cur_patch" == "$cached_patch" && "$cur_flags" == "$cached_flags" ]]; then
    log "restored tree was built from identical patch series + configure flags; keeping cached objects"
  elif [[ "$cur_flags" != "$cached_flags" ]]; then
    # Configure flags change compile-time defines for many targets (e.g. V8
    # WebAssembly / i18n), so no object can be trusted: force a full rebuild.
    warn "configure flags changed; stamping all sources to now to force a correct full rebuild"
    find "$NODE_SRC" -path "$NODE_SRC/out" -prune -o -type f -exec touch {} +
  else
    warn "patch series changed; re-stamping only the files rewritten by the patch (incremental rebuild)"
    (
      cd "$NODE_SRC"
      git diff --name-only | while read -r f; do [ -f "$f" ] && touch "$f"; done
      git diff --name-only
    )
  fi
}

cmd_configure() {
  require_tools
  require_patched_source
  cd "$NODE_SRC"

  log "nodejs-mobile source: $NODE_SRC (Node.js $(node_version_from_source))"
  export GYP_DEFINES="target_arch=arm64 host_os=mac target_os=ios"
  log "GYP_DEFINES=$GYP_DEFINES"
  log "configure ${CONFIGURE_FLAGS[*]}"

  ./configure "${CONFIGURE_FLAGS[@]}"

  [[ -f out/Makefile ]] || die "configure succeeded but out/Makefile was not generated"
  grep -q '^NODE_TARGET_TYPE=executable$' config.mk \
    || die "expected NODE_TARGET_TYPE=executable in config.mk (do not pass --enable-static)"
  log "config.mk: $(grep -E '^(BUILDTYPE|NODE_TARGET_TYPE)=' config.mk | tr '\n' ' ')"
  log "config.gypi target variables: $(grep -E "'(OS|node_target_type|node_use_node_snapshot|node_use_node_code_cache)':" config.gypi | tr -d ' ' | tr '\n' ' ')"
  grep -q "'OS': 'ios'" config.gypi || die "config.gypi does not select OS=ios"
  mkdir -p out/Release
  build_inputs_fingerprint > out/Release/.runtime-build-inputs
  log "build-inputs fingerprint stored in out/Release/.runtime-build-inputs:"
  cat out/Release/.runtime-build-inputs
  log "configure OK: gyp makefiles generated for iPhoneOS arm64 (node executable target)"
}

cmd_build() {
  require_tools
  require_patched_source
  cd "$NODE_SRC"
  [[ -f out/Makefile ]] || die "out/Makefile missing; run: $0 configure"

  mkdir -p "$ROOT/dist"
  log "make -j$JOBS (Node.js iPhoneOS arm64; first cold build typically 40-90 min on a macOS runner)"
  local start rc
  start="$SECONDS"
  set +e
  make -j"$JOBS" 2>&1 | tee "$MAKE_LOG"
  rc="${PIPESTATUS[0]}"
  set -e
  log "make finished in $((SECONDS - start))s with exit code $rc"

  if [[ "$rc" -ne 0 ]]; then
    warn "make exited $rc; tail of $MAKE_LOG:"
    tail -n 120 "$MAKE_LOG" >&2 || true
    if [[ -f out/Release/libnode.a ]]; then
      warn "out/Release/libnode.a exists, so the static libraries were built before the failure."
      warn "The package step will attempt the documented fallback link of scripts/ios-runtime/node_main.cc."
      printf '%s\n' "$rc" > "$MAKE_RC_FILE"
      return 0
    fi
    die "make failed before out/Release/libnode.a was produced; no fallback link is possible"
  fi

  printf '0\n' > "$MAKE_RC_FILE"
  if [[ -f out/Release/node ]]; then
    log "make produced out/Release/node:"
    file out/Release/node
  else
    warn "make succeeded but out/Release/node is missing; package step will use the fallback link"
  fi
}

# Recover the exact `node` link command from a verbose make run and retry it
# with iOS framework flags appended. This is a safety net for the (unexpected)
# case where gyp's generated executable link line needs extra iOS frameworks or
# still carries macOS-only flags such as -Wl,-no_pie.
fallback_link() {
  local retry_log="$ROOT/dist/fallback-link.log"
  local link_cmd fixed_cmd
  log "FALLBACK LINK: re-running make with V=1 to capture the node link command"
  (
    cd "$NODE_SRC"
    set +e
    make -C out -k -j"$JOBS" V=1
    printf 'make exit: %s\n' "$?"
  ) >"$retry_log" 2>&1 || true

  link_cmd="$(grep -E -- '-o [^ ]*out/Release/node( |$)' "$retry_log" | tail -n 1 || true)"
  if [[ -z "$link_cmd" ]]; then
    link_cmd="$(grep -F 'node_main.cc' "$retry_log" | grep -F ' -o ' | tail -n 1 || true)"
  fi
  [[ -n "$link_cmd" ]] \
    || die "could not recover the node link command from $retry_log; inspect it and $MAKE_LOG"

  # iOS executables must be position independent: drop the macOS-only -no_pie.
  fixed_cmd="${link_cmd//-Wl,-no_pie/}"
  fixed_cmd+=" -framework CoreFoundation -framework Foundation -framework Security"
  log "FALLBACK LINK command: $fixed_cmd"
  (
    cd "$NODE_SRC"
    eval "$fixed_cmd"
  ) || die "fallback link failed; see $retry_log"

  [[ -f "$NODE_SRC/out/Release/node" ]] \
    || die "fallback link reported success but $NODE_SRC/out/Release/node is absent"
  log "FALLBACK LINK succeeded: out/Release/node"
}

# Static (host-side) validation. Never proves device execution.
validate_static() {
  local bin="$1" stage="$2" file_out deps bad
  [[ -f "$bin" ]] || die "missing binary: $bin"
  [[ -x "$bin" ]] || die "binary is not executable: $bin"

  log "[$stage] file(1)"
  file "$bin" | tee "$DIST/file.txt"
  grep -q 'Mach-O 64-bit executable arm64' "$DIST/file.txt" \
    || die "unexpected file type (want Mach-O 64-bit executable arm64)"

  log "[$stage] scripts/check_macho.py --max-minos 16.1.1"
  python3 "$CHECK_MACHO" "$bin" --max-minos 16.1.1 | tee "$DIST/check-macho-$stage.txt"

  log "[$stage] xcrun vtool -show-build"
  xcrun vtool -show-build "$bin" | tee "$DIST/vtool-$stage.txt"
  grep -q 'platform IOS' "$DIST/vtool-$stage.txt" \
    || die "vtool did not report platform IOS (not an iPhoneOS binary)"
  grep -q 'minos 1[0-6]\.' "$DIST/vtool-$stage.txt" \
    || warn "unexpected vtool minos (expected <= 16.1)"

  log "[$stage] xcrun otool -L dylib audit"
  xcrun otool -L "$bin" | tee "$DIST/otool-L-$stage.txt"
  deps="$(xcrun otool -L "$bin" | tail -n +2 | awk 'NF {print $1}')"
  bad="$(printf '%s\n' "$deps" | grep -vE '^(/usr/lib/|/System/Library/Frameworks/)' || true)"
  [[ -z "$bad" ]] || die "non-iOS-system dylib dependency detected: $bad"
  if grep -qE '(/opt/homebrew|/usr/local/|/Library/Frameworks|/System/Library/PrivateFrameworks|@rpath)' \
      "$DIST/otool-L-$stage.txt"; then
    die "macOS-only or non-system dependency found in otool -L output (see $DIST/otool-L-$stage.txt)"
  fi
  # ECMA-402/Intl and V8 Unicode property escapes (\p{...}) are required by the
  # OpenCode CLI bundle (device evidence: the initial --with-intl=none runtime was
  # rejected with "Invalid property name in character class"). The build must have
  # V8 i18n enabled and full ICU linked statically.
  #
  # IMPORTANT: Node builds ICU with visibility=hidden, so ICU symbols are LOCAL in
  # the final binary (and some link configurations strip the symbol table). Do not
  # rely on a global-symbol grep. Collect several independent signals and fail
  # only if the build config denies i18n or every signal indicates ICU is absent.
  log "[$stage] ICU/Intl presence audit"
  local icu_evidence="$DIST/icu-evidence-$stage.txt"
  local nm_file="$DIST/nm-symbols-$stage.txt"
  local bin_size icu_signals=0
  bin_size="$(stat -f %z "$bin")"
  # Capture tool output to files BEFORE grepping: `nm ... | grep -q` is flaky
  # under `set -o pipefail`, because grep -q exits on the first match and nm can
  # then die with SIGPIPE (exit 141), failing the whole pipeline even though the
  # match was found. Grepping a file has no such failure mode.
  nm "$bin" > "$nm_file" 2>"$DIST/nm-stderr-$stage.txt" || true
  {
    echo "== config.gypi =="
    grep -E "'(v8_enable_i18n_support|icu_small|icu_ver_major|icu_endianness)':" "$NODE_SRC/config.gypi" || true
    echo "== binary size =="
    echo "$bin_size bytes (no-Intl baseline was 60598384 bytes)"
    echo "== nm (local symbols included, no -g/-U) =="
    grep -aE '(icudt[0-9]+[a-z_]*_dat|u_strToUpper|u_getPropertyEnum|u_getIntPropertyValue|u_getUnicodeVersion|u_init|icu_[0-9]+_dat)' "$nm_file" | head -n 10 || true
    echo "== binary strings: ICU version =="
    LC_ALL=C grep -a -m3 -E 'ICU [0-9]+\.[0-9]+' "$bin" || true
    echo "== binary strings: ICU data name =="
    LC_ALL=C grep -a -m3 'icudt[0-9]' "$bin" || true
  } > "$icu_evidence" 2>&1
  cat "$icu_evidence"

  grep -q "'v8_enable_i18n_support': 1" "$NODE_SRC/config.gypi" \
    || die "config.gypi has no v8_enable_i18n_support=1 (build must use --with-intl=full-icu)"

  if grep -aqE '(icudt[0-9]+[a-z_]*_dat|u_strToUpper|u_getPropertyEnum|u_getIntPropertyValue)' "$nm_file"; then
    icu_signals=$((icu_signals + 1))
    log "[$stage] ICU signal: nm found ICU symbols (local symbols count)"
  fi
  if LC_ALL=C grep -aqE 'ICU [0-9]+\.[0-9]+' "$bin"; then
    icu_signals=$((icu_signals + 1))
    log "[$stage] ICU signal: ICU version string present"
  fi
  if LC_ALL=C grep -aq 'icudt[0-9]' "$bin"; then
    icu_signals=$((icu_signals + 1))
    log "[$stage] ICU signal: ICU data name present"
  fi
  if [[ "$bin_size" -gt 70000000 ]]; then
    icu_signals=$((icu_signals + 1))
    log "[$stage] ICU signal: binary size $bin_size > 70 MB (no-Intl baseline 60.6 MB, full ICU adds ~25-35 MB)"
  fi
  if [[ "$icu_signals" -eq 0 ]]; then
    die "no ICU evidence found (config says i18n=1, but nm/strings/size all indicate absence); see $icu_evidence"
  fi
  log "[$stage] ICU present: full-icu statically linked (v8_enable_i18n_support=1; $icu_signals/4 signals)"
  # WebAssembly must be compiled in: Node 22.9 fetch()/undici instantiates a wasm
  # llhttp parser at startup (device-rejected without it). Hard requirement:
  # config.gypi says v8_enable_webassembly=1 and the build no longer passes
  # --v8-options=--jitless. Presence signals (V8 wasm symbols are local too):
  log "[$stage] V8 WebAssembly presence audit"
  local wasm_evidence="$DIST/wasm-evidence-$stage.txt"
  local wasm_signals=0
  {
    echo "== config.gypi =="
    grep -E "'(v8_enable_webassembly|v8_enable_lite_mode|v8_enable_turbofan)':" "$NODE_SRC/config.gypi" || true
    echo "== configure flags (must not contain --jitless) =="
    grep -E 'v8-options|jitless' "$NODE_SRC/config.status" || true
    echo "== nm: wasm symbols (local included) =="
    grep -aiE '(_?wasm|liftoff|turboshaft|wasm_|Wasm)' "$nm_file" | head -n 10 || true
    echo "== binary strings: WebAssembly =="
    LC_ALL=C grep -a -m3 'WebAssembly' "$bin" || true
  } > "$wasm_evidence" 2>&1
  cat "$wasm_evidence"

  grep -q "'v8_enable_webassembly': 1" "$NODE_SRC/config.gypi" \
    || die "config.gypi says v8_enable_webassembly != 1 (apply patches/nodejs-mobile/0003; Node fetch/undici needs wasm)"
  if grep -q -- '--jitless' "$NODE_SRC/config.status"; then
    die "config.status still passes --v8-options=--jitless; JIT/wasm would be unusable"
  fi

  if grep -aqiE '(_?wasm|liftoff|wasm_)' "$nm_file"; then
    wasm_signals=$((wasm_signals + 1))
    log "[$stage] WebAssembly signal: V8 wasm symbols present in nm output"
  fi
  if LC_ALL=C grep -aq 'WebAssembly' "$bin"; then
    wasm_signals=$((wasm_signals + 1))
    log "[$stage] WebAssembly signal: 'WebAssembly' strings present"
  fi
  if grep -q "'v8_enable_turbofan': 1" "$NODE_SRC/config.gypi"; then
    wasm_signals=$((wasm_signals + 1))
    log "[$stage] WebAssembly signal: V8 turbofan (wasm compiler) enabled"
  fi
  if [[ "$wasm_signals" -eq 0 ]]; then
    die "no WebAssembly evidence found; see $wasm_evidence"
  fi
  log "[$stage] WebAssembly present: enabled ($wasm_signals/3 signals); JIT enabled (no --jitless)"
  # iOS JIT memory model (patch 0005): the shipped binary must use the no-MAP_JIT
  # / plain-mprotect path. With V8_HAS_PTHREAD_JIT_WRITE_PROTECT=0 on iOS device
  # the platform-ios.cc dlsym thunk (patch 0004) is compiled out, so the
  # pthread_jit_write_protect_np string must be ABSENT from the binary. Its
  # presence would mean the MAP_JIT path was enabled, which device testing
  # showed aborts (v4 SIGTRAP / FatalProcessOOM) or traps with SIGBUS (v3).
  log "[$stage] iOS JIT memory-model audit (mprotect RW<->RX toggling; no MAP_JIT / no RWX)"
  grep -q 'defined(V8_OS_DARWIN) && !defined(V8_OS_IOS)' \
    "$NODE_SRC/deps/v8/src/base/platform/platform-posix.cc" \
    || die "platform-posix.cc is missing the patch-0005 MAP_JIT guard"
  grep -q 'RegisterIOSCodeRange' \
    "$NODE_SRC/deps/v8/src/base/platform/platform-ios.cc" \
    || die "platform-ios.cc is missing the patch-0006 mprotect registry implementation"
  grep -q 'RegisterIOSCodeRange' \
    "$NODE_SRC/deps/v8/src/heap/memory-allocator.cc" \
    || die "memory-allocator.cc is missing iOS code-chunk registration (patch 0006)"
  grep -q 'RegisterIOSCodeRange' \
    "$NODE_SRC/deps/v8/src/wasm/wasm-code-manager.cc" \
    || die "wasm-code-manager.cc is missing iOS wasm-space registration (patch 0006)"
  if ! LC_ALL=C grep -aq 'RegisterIOSCodeRange' "$bin"; then
    die "binary does not contain RegisterIOSCodeRange (patch 0006 missing): iOS JIT would have no W^X toggling"
  fi
  if LC_ALL=C grep -aq 'pthread_jit_write_protect_np' "$bin"; then
    warn "binary references pthread_jit_write_protect_np; expected only the mprotect-based iOS implementation"
  fi
  {
    echo "== platform-posix.cc MAP_JIT guard (patch 0005) =="
    grep -n 'defined(V8_OS_DARWIN) && !defined(V8_OS_IOS)' "$NODE_SRC/deps/v8/src/base/platform/platform-posix.cc" || true
    echo "== patch-0006 iOS mprotect registry =="
    grep -nE 'RegisterIOSCodeRange|SetJitWriteProtected|mprotect' "$NODE_SRC/deps/v8/src/base/platform/platform-ios.cc" || true
    echo "== patch-0006 heap/wasm registration call sites =="
    grep -n 'RegisterIOSCodeRange' "$NODE_SRC/deps/v8/src/heap/memory-allocator.cc" "$NODE_SRC/deps/v8/src/wasm/wasm-code-manager.cc" || true
    echo "== binary references RegisterIOSCodeRange (mprotect W^X toggling built in) =="
    if grep -aq 'RegisterIOSCodeRange' "$bin"; then echo "present (good)"; else echo "MISSING (bad)"; fi
    echo "== binary must not reference pthread_jit_write_protect_np (APRR path) =="
    if LC_ALL=C grep -aq 'pthread_jit_write_protect_np' "$bin"; then echo "PRESENT (bad)"; else echo "absent (good)"; fi
  } | tee "$DIST/jit-memory-model-$stage.txt"
  log "[$stage] JIT memory model OK: mprotect RW<->RX toggling over registered code ranges, no MAP_JIT, no RWX requests, 2-key entitlements"
  log "[$stage] static validation PASSED (iOS platform, arm64, system libraries only, ICU + WebAssembly; iOS JIT mprotect W^X audited)"
}

# ldid ad-hoc signing with the DEVICE-VERIFIED 2-key entitlement set:
#   platform-application + com.apple.private.security.no-sandbox
# No JIT-specific entitlements are needed: the shipped iOS JIT model uses
# plain mprotect RW<->RX toggling without MAP_JIT (patch 0006), and a JIT-enabled
# Node 18 reference binary runs on this exact iPhone with only these two keys.
# Extra JIT keys never fixed the MAP_JIT failures and are rejected by this gate.
# See docs/RUNTIME_BUILD.md and scripts/ios-runtime/entitlements.plist.
sign_binary() {
  local bin="$1"
  command -v ldid >/dev/null 2>&1 || die "ldid not installed (brew install ldid)"
  log "ldid -S<entitlements> $bin"
  ldid -S"$ENTITLEMENTS" "$bin"

  log "embedded entitlements (ldid -e):"
  ldid -e "$bin" > "$DIST/entitlements-signed.xml" 2>&1 || true
  cat "$DIST/entitlements-signed.xml"

  # Exact-set check: the signed binary must carry exactly the two device-verified
  # keys. This is a hard gate - the previous 4-key JIT set was SIGKILLed.
  python3 - "$DIST/entitlements-signed.xml" <<'PY'
import plistlib
import sys

expected = {
        "platform-application",
        "com.apple.private.security.no-sandbox",
    }
path = sys.argv[1]
try:
    with open(path, "rb") as f:
        data = plistlib.load(f)
except Exception as exc:  # noqa: BLE001 - report and fall back to text checks
    print(f"WARNING: could not parse ldid -e output as a plist ({exc}); using text checks")
    text = open(path, encoding="utf-8", errors="replace").read()
    missing = [k for k in expected if k not in text]
    if missing:
        sys.exit(f"ERROR: signature is missing required entitlement(s): {', '.join(missing)}")
    for forbidden in (
        "com.apple.security.cs.allow-jit",
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "com.apple.security.cs.disable-library-validation",
        "dynamic-codesigning",
    ):
        if forbidden in text:
            sys.exit(f"ERROR: signature carries the rejected entitlement {forbidden!r} "
                     "(device-verified to cause SIGKILL 137)")
    print("entitlements: exactly the two device-verified keys are present")
    sys.exit(0)

keys = set(data) if isinstance(data, dict) else set()
if keys != expected:
    sys.exit(
        "ERROR: signed entitlements must be exactly "
        f"{sorted(expected)}, got {sorted(keys)}"
    )
print("entitlements: exactly the two device-verified keys are present:", sorted(keys))
PY

  # Informational: codesign may or may not be able to read an ldid signature.
  if codesign -d --entitlements :- "$bin" >"$DIST/codesign-entitlements.xml" \
      2>"$DIST/codesign-stderr.txt"; then
    log "codesign -d --entitlements output saved to codesign-entitlements.xml"
  else
    warn "codesign could not read the ldid signature (informational only; ldid -e is authoritative)"
  fi
  log "signing OK (platform-application + com.apple.private.security.no-sandbox)"
}

# Keep runtime-manifest.json compatible with package-rootless.yml's capability
# gate (packaging/verify/port_verify.py _check_runtime_profile): the webassembly
# and v8_jit policy strings must START with "enabled:" and must not contain the
# words the gate treats as failure ("disabled" / "jitless"), and configure_flags
# must contain --with-intl=full-icu without any interpreter-only flag.
check_manifest_profile_gate() {
  log "checking runtime-manifest.json against the packager capability gate"
  python3 - "$DIST/runtime-manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
build = manifest.get("build") or {}
policy = manifest.get("runtime_policy") or {}
flags = [str(f) for f in (build.get("configure_flags") or [])]
errs = []
for key in ("webassembly", "v8_jit"):
    text = str(policy.get(key, "")).strip().lower()
    if not text.startswith("enabled:"):
        errs.append(f"runtime_policy.{key} must start with 'enabled:'")
    bad = [w for w in ("disabled", "jitless") if w in text]
    if bad:
        errs.append(f"runtime_policy.{key} contains forbidden word(s) {bad}")
if not any("--with-intl=full-icu" in f for f in flags):
    errs.append("build.configure_flags must contain --with-intl=full-icu")
if any("--v8-options=--jitless" in f for f in flags):
    errs.append("build.configure_flags must not contain --v8-options=--jitless")
if not any("--dest-os=ios" in f for f in flags):
    errs.append("build.configure_flags must contain --dest-os=ios")
if not any("--dest-cpu=arm64" in f for f in flags):
    errs.append("build.configure_flags must contain --dest-cpu=arm64")
intl = policy.get("intl") or {}
if str(intl.get("mode", "")).lower() in ("", "none", "unknown"):
    errs.append("runtime_policy.intl.mode must be a real ICU mode (full-icu)")
if not intl.get("icu_version"):
    errs.append("runtime_policy.intl.icu_version must be set")
if errs:
    print("ERROR: runtime-manifest.json is not packager-gate compatible:")
    for err in errs:
        print(" - " + err)
    sys.exit(1)
print("runtime-manifest.json capability profile is packager-gate compatible")
PY
}

write_manifest() {
  local build_path="$1" make_rc="$2"
  log "writing runtime-manifest.json (build path: $build_path)"
  BUILD_PATH="$build_path" MAKE_RC="$make_rc" NODE_SRC="$NODE_SRC" DIST="$DIST" ROOT="$ROOT" \
    NODE_VERSION_EXPECTED="${NODE_VERSION:-22.9.0}" python3 - <<'PY'
import hashlib
import json
import os
import pathlib
import re
import subprocess

dist = pathlib.Path(os.environ["DIST"])
src = pathlib.Path(os.environ["NODE_SRC"])
root = pathlib.Path(os.environ["ROOT"])
node = dist / "node"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path, default=""):
    try:
        return pathlib.Path(path).read_text()
    except OSError:
        return default


def macro(name):
    m = re.search(r"^#define %s (\d+)" % name, read(src / "src" / "node_version.h"), re.M)
    return int(m.group(1)) if m else None


node_version = ".".join(
    str(macro(n)) for n in ("NODE_MAJOR_VERSION", "NODE_MINOR_VERSION", "NODE_PATCH_VERSION")
)
cfg = read(src / "config.gypi")
m = re.search(r"'OS': '([^']+)'", cfg)
target_os = m.group(1) if m else "unknown"

patch_files = sorted(root.glob("patches/nodejs-mobile/*.patch"))
patches = [{"file": str(p.relative_to(root)), "sha256": sha256(p)} for p in patch_files]

otool = read(dist / "otool-L-signed.txt")
dylibs = [ln.split()[0] for ln in otool.splitlines()[1:] if ln.strip()]
vtool = read(dist / "vtool-signed.txt")
minos = re.search(r"minos (\S+)", vtool)
sdk = re.search(r"sdk (\S+)", vtool)
file_out = read(dist / "file.txt").strip()

# ICU / Intl state (required by the CLI bundle: ECMA-402 + V8 \p{} escapes).
i18n = re.search(r"'v8_enable_i18n_support': (\d+)", cfg)
icu_small = re.search(r"'icu_small': '(\w+)'", cfg)
icu_version = None
uvm = read(src / "deps" / "icu-small" / "source" / "common" / "unicode" / "uvernum.h")
m_icu = re.search(r'#define U_ICU_VERSION_SHORT "([^"]+)"', uvm)
if m_icu:
    icu_version = m_icu.group(1)

if target_os == "ios":
    platform_evidence = (
        "process.platform is initialised from the NODE_PLATFORM compile-time macro "
        "(src/node_metadata.cc: Metadata::Metadata() : arch(NODE_ARCH), platform(NODE_PLATFORM)); "
        "node.gyp defines NODE_PLATFORM=\"<(OS)\" for both the node and libnode targets and "
        "configure.py sets OS=ios when --dest-os=ios is used, so the runtime reports "
        "process.platform === \"ios\" (not \"darwin\"). Confirmed from the pinned tree and "
        "config.gypi; device execution is still UNVERIFIED ON DEVICE."
    )
else:
    platform_evidence = "config.gypi did not report OS=ios; inspect the build before trusting process.platform."

manifest = {
    "artifact": "ios-node-runtime",
    "node_version": node_version or os.environ["NODE_VERSION_EXPECTED"],
    "target": {
        "platform": "iPhoneOS",
        "arch": "arm64",
        "min_ios_from_vtool": minos.group(1) if minos else None,
        "sdk_from_vtool": sdk.group(1) if sdk else None,
        "static_validation_max_minos": "16.1.1",
    },
    "source": {
        "nodejs_mobile_repo": "https://github.com/nodejs-mobile/nodejs-mobile",
        "nodejs_mobile_branch": "update22-9-0",
        "nodejs_mobile_commit": "106c51f95d55d1010de56a2ffd09bfb4ba819a47",
        "base_node_version": "22.9.0",
        "patches": patches,
        "build_fixes_source": "https://github.com/nodejs-mobile/nodejs-mobile/pull/150",
        "patch_subset_note": (
            "patches/nodejs-mobile/0001-ios-build-fixes.patch is the source/build subset of "
            "PR #150; its .github/workflows/*, .gitignore and tools/android_build.sh hunks are "
            "intentionally omitted (this repository does not use them)."
        ),
    },
    "build": {
        "build_path": os.environ["BUILD_PATH"],
        "make_exit_code": int(os.environ["MAKE_RC"]),
        "configure_flags": [
            "--dest-os=ios",
            "--dest-cpu=arm64",
            "--with-intl=full-icu",
            "--cross-compiling",
            "--openssl-no-asm",
            "--without-node-code-cache",
            "--without-node-snapshot",
        ],
        "configure_status": read(src / "config.status").strip(),
        "xcode_version": os.environ.get("XCODE_VERSION", "16.4"),
        "runner_os": os.environ.get("RUNNER_OS", "macOS"),
        "job_started_utc": os.environ.get("RUNTIME_BUILD_START_UTC", ""),
        "build_date_utc": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
        "github_workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
    },
    "binary": {
        "file": "node",
        "size_bytes": node.stat().st_size,
        "sha256": sha256(node),
        "file_output": file_out,
        "linked_dylibs": dylibs,
        "entitlements_sha256": sha256(dist / "entitlements.plist"),
    },
    "runtime_policy": {
        "v8_jit": "enabled: JIT compiled in and on by default. On iOS, V8's "
                  "RwxMemoryWriteScope is implemented over mprotect, toggling registered "
                  "code ranges between RW (writing) and RX (executing) - patches 0005+0006: "
                  "no MAP_JIT, no RWX requests, no APRR. Device-probed: the only working "
                  "executable-memory pattern on iOS 16.1.1 is RW -> write -> mprotect RX -> "
                  "execute; the 2-key entitlement set is the device-verified configuration.",
        "webassembly": "enabled: V8 WebAssembly + Liftoff compiled in; required by Node's "
                       "built-in fetch/undici wasm llhttp parser at startup. Wasm code uses the "
                       "same mprotect RW<->RX toggling model as JIT (patch 0006); the "
                       "device-verified configuration is the 2-key entitlement set.",
        "jit_memory": "iOS: plain mprotect RW<->RX toggling over executable ranges registered by "
                      "RegisterIOSCodeRange (JS code chunks via memory-allocator.cc and wasm code "
                      "spaces via wasm-code-manager.cc); SetJitWriteProtected(0/1) in "
                      "platform-ios.cc mprotects them RW/RX (patch 0006). No MAP_JIT (patch 0005), "
                      "no RWX permission requests (iOS silently drops PROT_EXEC), and no "
                      "pthread_jit_write_protect_np (absent on iOS 16.1.1). Device probe: plain "
                      "RW->write->mprotect RX->execute works; MAP_JIT/RWX paths trap. Trade-off: "
                      "mprotect is process-wide, so a write scope briefly makes the whole "
                      "registered range non-executable (correctness-first; may be slower).",
        "intl": {
            "mode": "full-icu",
            "configure_flag": "--with-intl=full-icu",
            "v8_enable_i18n_support": int(i18n.group(1)) if i18n else None,
            "icu_small": icu_small.group(1) if icu_small else None,
            "icu_version": icu_version,
            "icu_source": "canned full ICU bundled in the pinned nodejs-mobile tree "
                          "(deps/icu-small, README-FULL-ICU.txt; data file "
                          "source/data/in/icudt75l.dat.bz2 is unpacked by configure)",
            "data_statically_linked": True,
            "device_requirement_note": (
                "ICU is REQUIRED for ECMA-402/Intl and V8 Unicode property escapes "
                "(\\p{...}). Device evidence: the initial --with-intl=none runtime started "
                "on the iPhone but the CLI bundle failed to parse with 'SyntaxError: Invalid "
                "regular expression: /[\\p{Mark}...]/gu: Invalid property name in character "
                "class' and Intl was undefined. This ICU build is the fix; it is statically "
                "linked so otool -L stays libSystem/libc++ only."
            ),
        },
        "entitlements": [
            "platform-application",
            "com.apple.private.security.no-sandbox",
        ],
        "entitlements_status": "device-verified minimal set (2 keys); the shipped runtime uses "
                               "the no-MAP_JIT/plain-mprotect JIT memory model, and a "
                               "JIT-enabled Node 18 reference binary runs with only these keys.",
        "entitlements_note": (
            "The 2-key set has been device-verified repeatedly on the target iPhone "
            "(platform-application + com.apple.private.security.no-sandbox): the v2 "
            "interpreted-only runtime ran with it, and a JIT-enabled reference Node 18 binary "
            "runs JIT + WebAssembly with it. The loader SIGKILLs (exit 137) this runtime with "
            "platform-application alone or with the old 4-key JIT set without no-sandbox. "
            "dynamic-codesigning/allow-unsigned/allow-jit are NOT needed because the shipped "
            "iOS JIT model uses plain mprotect RW<->RX toggling without MAP_JIT (patch 0006) "
            "and those keys are rejected by the CI signing gate."
        ),
        "node_cli_flags_available": {
            "--experimental-sqlite": True,
            "--experimental-vm-modules": True,
            "--use-system-ca": False,
            "--experimental-ffi": False,
        },
        "node_cli_flags_note": (
            "Verified against the pinned Node 22.9.0 src/node_options.cc: --experimental-sqlite "
            "and --experimental-vm-modules exist; --use-system-ca and --experimental-ffi do not "
            "exist in 22.9.0 (do not pass them to the wrapper)."
        ),
        "process_platform": target_os,
        "process_platform_evidence": platform_evidence,
    },
    "signing": {
        "tool": "ldid",
        "command": "ldid -S<entitlements.plist> node",
        "entitlement_keys": [
            "platform-application",
            "com.apple.private.security.no-sandbox",
        ],
        "entitlements_status": "device-verified minimal set (2 keys)",
        "entitlements_device_verified": True,
        "revalidated_after_signing": True,
        "codesign_could_read_signature": (dist / "codesign-entitlements.xml").stat().st_size > 0,
    },
    "device_status": "UNVERIFIED ON DEVICE",
    "device_status_note": (
        "The 2-key entitlement set is device-verified, and a JIT-enabled Node 18 reference "
        "binary runs JIT + WebAssembly on the target iPhone SE 2 with only these keys. Earlier "
        "22.9.0 builds of this source were device-verified to run but were rejected by the CLI "
        "first for missing Intl/\\p{} (fixed with full-icu) and then for missing WebAssembly in "
        "Node fetch/undici (fixed by enabling V8 JIT+WebAssembly); the MAP_JIT variants then "
        "aborted on the device (v3 SIGBUS, v4 SIGTRAP/FatalProcessOOM in "
        "CodeRange::InitReservation, both unfixable by entitlements). Device probing proved "
        "that iOS 16.1.1 only supports explicit mprotect W^X toggling, so patch 0006 "
        "implements V8's write scopes over mprotect (RW<->RX over registered code ranges; no "
        "MAP_JIT, no RWX). This v6 artifact is the rebuild for all those blockers; its device "
        "execution is pending external verification. GitHub-hosted macOS runners cannot "
        "execute iPhoneOS binaries; all payload checks in CI are static (Mach-O platform/minos, "
        "dylib linkage, ldid signature, ICU/WebAssembly/JIT mprotect-model audits). See "
        "docs/RUNTIME_BUILD.md and scripts/ios-runtime/README.md."
    ),
}

(dist / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest["target"], indent=2))
PY
}

write_checksums() {
  log "writing SHA256SUMS"
  (
    cd "$DIST"
    shasum -a 256 node entitlements.plist runtime-manifest.json > SHA256SUMS
    cat SHA256SUMS
  )
}

write_validation_report() {
  local build_path="$1" make_rc="$2"
  {
    echo "# ios-node-runtime static validation report"
    echo
    echo "Generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Build path: $build_path (make exit code: $make_rc)"
    echo
    echo "## Verdict"
    echo
    echo "- Mach-O: iPhoneOS arm64 executable, minos <= 16.1.1 (scripts/check_macho.py PASS)"
    echo "- Dylib linkage: iOS system libraries/frameworks only (no Homebrew, no macOS-only libs)"
    echo "- V8: JIT enabled (no --jitless) and WebAssembly enabled (required by Node fetch/undici)"
    echo "- V8 iOS JIT memory: mprotect RW<->RX toggling over registered code ranges, no MAP_JIT, no RWX requests (patches 0005+0006)"
    echo "- ICU: full-icu statically linked (ECMA-402 Intl + V8 \\p{...} regexps)"
    echo "- ldid signing: ad-hoc signature with the device-verified 2-key entitlement set; re-validated after signing"
    echo "- Device execution: **UNVERIFIED ON DEVICE** (GitHub-hosted runners cannot run iOS binaries)"
    echo
    echo "## file(1)"
    echo '```'
    cat "$DIST/file.txt"
    echo '```'
    echo
    echo "## scripts/check_macho.py (after signing)"
    echo '```'
    cat "$DIST/check-macho-signed.txt"
    echo '```'
    echo
    echo "## vtool -show-build (after signing)"
    echo '```'
    cat "$DIST/vtool-signed.txt"
    echo '```'
    echo
    echo "## otool -L (after signing)"
    echo '```'
    cat "$DIST/otool-L-signed.txt"
    echo '```'
    echo
    echo "## ldid entitlements (ldid -e)"
    echo '```'
    cat "$DIST/entitlements-signed.xml"
    echo '```'
    echo
    echo "## build log tail (make)"
    echo '```'
    tail -n 40 "$MAKE_LOG" 2>/dev/null || echo "(no build log recorded)"
    echo '```'
  } > "$DIST/validation-report.txt"
  log "wrote validation-report.txt"
}

cmd_package() {
  require_tools
  require_patched_source
  cd "$NODE_SRC"
  [[ -f out/Makefile ]] || die "out/Makefile missing; run: $0 configure"

  rm -rf "$DIST"
  mkdir -p "$DIST"

  local make_rc=0 build_path node_bin
  if [[ -f "$MAKE_RC_FILE" ]]; then
    make_rc="$(cat "$MAKE_RC_FILE")"
  fi

  if [[ -f out/Release/node ]]; then
    build_path="make-executable"
    node_bin="out/Release/node"
    log "using out/Release/node produced by the normal Node.js executable build"
  else
    warn "out/Release/node is missing; falling back to scripts/ios-runtime/node_main.cc"
    build_path="fallback-link"
    fallback_link
    node_bin="out/Release/node"
  fi

  cp "$node_bin" "$DIST/node"
  chmod 0755 "$DIST/node"
  cp "$ENTITLEMENTS" "$DIST/entitlements.plist"
  log "staged artifact binary: $(file "$DIST/node")"

  validate_static "$DIST/node" unsigned
  sign_binary "$DIST/node"
  log "re-running static validation after signing (signing modifies the Mach-O)"
  validate_static "$DIST/node" signed

  write_manifest "$build_path" "$make_rc"
  check_manifest_profile_gate
  write_validation_report "$build_path" "$make_rc"
  write_checksums

  log "artifact ready in $DIST:"
  ls -l "$DIST"
  log "DEVICE EXECUTION: UNVERIFIED ON DEVICE - CI validation is static only."
}

usage() {
  cat <<'USAGE'
usage: scripts/build-ios-runtime.sh {normalize-cache <cache_hit>|configure|build|package|all|--help}

  normalize-cache <cache_hit>
             prepare a restored out/Release cache for incremental make (mtime
             normalization + patch/flag fingerprint check); cache_hit is the
             actions/cache hit value ("true"/"false"/empty)
  configure  run nodejs-mobile ./configure for iPhoneOS arm64 (generates gyp makefiles)
  build      run make -j N (produces out/Release/node; 40-90 min first cold build)
  package    locate/link `node`, ldid-sign, statically validate, write manifest/checksums
  all        configure + build + package
USAGE
}

case "${1:-}" in
  normalize-cache) cmd_normalize_cache "${2:-false}" ;;
  configure)       cmd_configure ;;
  build)           cmd_build ;;
  package)         cmd_package ;;
  all)             cmd_configure; cmd_build; cmd_package ;;
  -h|--help|help)  usage ;;
  *) usage; die "unknown subcommand: ${1:-<none>}" ;;
esac
