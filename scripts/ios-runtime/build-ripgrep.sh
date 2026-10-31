#!/usr/bin/env bash
#
# Optional stretch component: cross-compile ripgrep for iPhoneOS arm64.
#
# OpenCode's search tool needs an `rg` on PATH; the package workflow
# (package-rootless.yml) downloads this artifact as `ios-ripgrep` when it exists
# and ships it under /var/jb/usr/bin/rg. This script builds it with the Rust
# aarch64-apple-ios target, ldid-signs it and statically validates the Mach-O.
#
# Status: device execution UNVERIFIED ON DEVICE (hosted CI cannot run it).
#
# Env:
#   RIPGREP_VERSION  crates.io version to build (default: 14.1.1, pinned in workflow)
#   DIST             artifact output dir (default: <repo>/dist/ios-ripgrep)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="${DIST:-$ROOT/dist/ios-ripgrep}"
RIPGREP_VERSION="${RIPGREP_VERSION:-14.1.1}"
TARGET="aarch64-apple-ios"
CARGO_ROOT="${CARGO_ROOT:-$ROOT/.cargo-ripgrep}"
CHECK_MACHO="$ROOT/scripts/check_macho.py"

log()  { printf '==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v cargo >/dev/null 2>&1 || die "cargo not found (install the Rust aarch64-apple-ios target first)"
command -v ldid >/dev/null 2>&1 || die "ldid not installed (brew install ldid)"
[[ -f "$CHECK_MACHO" ]] || die "missing $CHECK_MACHO"

# Use the real iPhoneOS SDK for the linker; rustc's cc-linking step honours SDKROOT.
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
export SDKROOT="$SDK"
log "iPhoneOS SDK: $SDK"

log "cargo install ripgrep@$RIPGREP_VERSION --target $TARGET --no-default-features"
log "(pcre2/serde default features are disabled: pcre2 is a C dependency that"
log " would need a separate iPhoneOS cross-build; the Rust regex engine is used)"
cargo install "ripgrep@${RIPGREP_VERSION}" \
  --target "$TARGET" \
  --no-default-features \
  --root "$CARGO_ROOT"

RG_SRC="$CARGO_ROOT/bin/rg"
[[ -f "$RG_SRC" ]] || die "cargo install did not produce $RG_SRC"
file "$RG_SRC"

rm -rf "$DIST"
mkdir -p "$DIST"
cp "$RG_SRC" "$DIST/rg"
chmod 0755 "$DIST/rg"

log "ldid ad-hoc signing (ripgrep needs no entitlements)"
ldid -S "$DIST/rg"
ldid -e "$DIST/rg" > "$DIST/entitlements-signed.xml" 2>&1 || true

log "static validation"
file "$DIST/rg" | tee "$DIST/file.txt"
grep -q 'Mach-O 64-bit executable arm64' "$DIST/file.txt" || die "ripgrep is not a thin arm64 Mach-O executable"
python3 "$CHECK_MACHO" "$DIST/rg" --max-minos 16.1.1 | tee "$DIST/check-macho.txt"
xcrun vtool -show-build "$DIST/rg" | tee "$DIST/vtool.txt"
grep -q 'platform IOS' "$DIST/vtool.txt" || die "ripgrep does not target platform IOS"
xcrun otool -L "$DIST/rg" | tee "$DIST/otool-L.txt"
bad="$(xcrun otool -L "$DIST/rg" | tail -n +2 | awk 'NF {print $1}' | grep -vE '^(/usr/lib/|/System/Library/Frameworks/)' || true)"
[[ -z "$bad" ]] || die "non-iOS-system dylib dependency: $bad"
if grep -qE '(/opt/homebrew|/usr/local/|/Library/Frameworks|@rpath)' "$DIST/otool-L.txt"; then
  die "macOS-only or non-system dependency found in otool -L output"
fi

python3 - "$DIST" "$RIPGREP_VERSION" "$TARGET" <<'PY'
import hashlib
import json
import pathlib
import subprocess
import sys

dist = pathlib.Path(sys.argv[1])
version = sys.argv[2]
target = sys.argv[3]
rg = dist / "rg"
sha = hashlib.sha256(rg.read_bytes()).hexdigest()
manifest = {
    "artifact": "ios-ripgrep",
    "tool": "ripgrep",
    "version": version,
    "target": {"platform": "iPhoneOS", "arch": "arm64", "rust_target": target},
    "binary": {"file": "rg", "size_bytes": rg.stat().st_size, "sha256": sha},
    "signing": {"tool": "ldid", "mode": "ad-hoc, no entitlements"},
    "cargo_install": {
        "command": f"cargo install ripgrep@{version} --target {target} --no-default-features",
        "features": "default features disabled (no pcre2 C dependency); Rust regex engine only",
    },
    "build_date_utc": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
    "device_status": "UNVERIFIED ON DEVICE",
    "notes": [
        "Optional stretch artifact: OpenCode's search tool uses rg if present.",
        "pcre2 is not available (default features disabled); regex syntax is the Rust regex engine.",
        "Static validation only; hosted macOS runners cannot execute iPhoneOS binaries.",
    ],
}
(dist / "ripgrep-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"version": version, "sha256": sha, "size": rg.stat().st_size}))
PY

(
  cd "$DIST"
  shasum -a 256 rg ripgrep-manifest.json > SHA256SUMS
  cat SHA256SUMS
)

log "artifact ready in $DIST"
ls -l "$DIST"
log "DEVICE EXECUTION: UNVERIFIED ON DEVICE - CI validation is static only."
