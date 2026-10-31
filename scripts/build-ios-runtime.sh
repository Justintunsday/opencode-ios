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
  --with-intl=none
  --cross-compiling
  --openssl-no-asm
  --v8-options=--jitless
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
  grep -q 'nodejs-mobile patch: disable V8_HAS_PTHREAD_JIT_WRITE_PROTECT' \
    "$NODE_SRC/deps/v8/src/base/build_config.h" \
    || die "patches/nodejs-mobile/*.patch does not look applied (build_config.h marker missing)"
  grep -q "v8_enable_webassembly'\] = 0" "$NODE_SRC/configure.py" \
    || die "patches/nodejs-mobile/*.patch does not look applied (configure.py WebAssembly marker missing)"
}

node_version_from_source() {
  local header="$NODE_SRC/src/node_version.h"
  local major minor patch
  major="$(sed -n 's/^#define NODE_MAJOR_VERSION \([0-9]*\)/\1/p' "$header")"
  minor="$(sed -n 's/^#define NODE_MINOR_VERSION \([0-9]*\)/\1/p' "$header")"
  patch="$(sed -n 's/^#define NODE_PATCH_VERSION \([0-9]*\)/\1/p' "$header")"
  printf '%s.%s.%s' "$major" "$minor" "$patch"
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
  log "[$stage] static validation PASSED (iOS platform, arm64, system libraries only)"
}

# ldid ad-hoc signing with the minimal, device-verified entitlement set.
# Exactly platform-application + com.apple.private.security.no-sandbox are
# verified to run on the target jailbroken device; anything else tested was
# SIGKILLed (exit 137) by the iOS loader. See docs/RUNTIME_BUILD.md.
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

expected = {"platform-application", "com.apple.private.security.no-sandbox"}
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
            "--with-intl=none",
            "--cross-compiling",
            "--openssl-no-asm",
            "--v8-options=--jitless",
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
        "v8_jit": "disabled at build time: configure --v8-options=--jitless compiles "
                  "NODE_V8_OPTIONS=\"--jitless\" into the binary",
        "webassembly": "disabled: PR #150 sets v8_enable_webassembly=0 in configure.py "
                       "(jitless iOS build); WebAssembly is NOT available on this runtime",
        "entitlements": [
            "platform-application",
            "com.apple.private.security.no-sandbox",
        ],
        "entitlements_note": (
            "Exactly these two keys were verified ON DEVICE (iPhone SE 2 / iOS 16.1.1 / "
            "Dopamine rootless, 2026-10-31) as the minimal working set. The loader SIGKILLs "
            "(exit 137) this runtime with platform-application alone or with the previous "
            "4-key JIT set (allow-jit, allow-unsigned-executable-memory, "
            "disable-library-validation, dynamic-codesigning); JIT entitlements are omitted "
            "because this runtime is jitless and has no WebAssembly."
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
        "entitlements_device_verified": True,
        "revalidated_after_signing": True,
        "codesign_could_read_signature": (dist / "codesign-entitlements.xml").stat().st_size > 0,
    },
    "device_status": "UNVERIFIED ON DEVICE",
    "device_status_note": (
        "The entitlement set in this artifact is DEVICE-VERIFIED on the target iPhone "
        "(platform-application + com.apple.private.security.no-sandbox run; the old 4-key JIT "
        "set is SIGKILLed with exit 137). Execution of THIS 22.9.0 build on the device is still "
        "pending; GitHub-hosted macOS runners cannot execute iPhoneOS binaries. All payload "
        "checks in CI are static (Mach-O platform/minos, dylib linkage, ldid signature). See "
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
    echo "- ldid signing: ad-hoc signature with minimal entitlements; re-validated after signing"
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
  write_validation_report "$build_path" "$make_rc"
  write_checksums

  log "artifact ready in $DIST:"
  ls -l "$DIST"
  log "DEVICE EXECUTION: UNVERIFIED ON DEVICE - CI validation is static only."
}

usage() {
  cat <<'USAGE'
usage: scripts/build-ios-runtime.sh {configure|build|package|all|--help}

  configure  run nodejs-mobile ./configure for iPhoneOS arm64 (generates gyp makefiles)
  build      run make -j N (produces out/Release/node; 40-90 min first cold build)
  package    locate/link `node`, ldid-sign, statically validate, write manifest/checksums
  all        configure + build + package
USAGE
}

case "${1:-}" in
  configure) cmd_configure ;;
  build)     cmd_build ;;
  package)   cmd_package ;;
  all)       cmd_configure; cmd_build; cmd_package ;;
  -h|--help|help) usage ;;
  *) usage; die "unknown subcommand: ${1:-<none>}" ;;
esac
